"""ComfyUI 0.29 execution-time metadata collection for SaveImagePlus.

The hidden PROMPT value contains graph links, not the values produced by those
links.  Sampling metadata therefore has to be captured after ComfyUI resolves
node inputs.  This module keeps only small metadata-relevant values and never
retains model, conditioning, latent, or image tensors.
"""

from __future__ import annotations

import contextvars
import functools
import logging
import threading
from collections import OrderedDict


logger = logging.getLogger("comfyui-image-tools.metadata")

_STORE_ATTR = "_image_tools_execution_metadata_store"
_CONTEXT_ATTR = "_image_tools_execution_metadata_context"
_HOOK_MARKER = "_image_tools_execution_metadata_hook"


def _unwrap_single(value):
    """Unwrap ComfyUI's per-batch one-item input container."""
    while isinstance(value, (list, tuple)) and len(value) == 1:
        value = value[0]
    return value


def _small_value(name, value):
    """Return a metadata-safe value, or None for large runtime objects."""
    value = _unwrap_single(value)

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value

    if name == "noise" and hasattr(value, "seed"):
        seed = getattr(value, "seed", None)
        if isinstance(seed, (int, float)):
            return {"seed": int(seed)}

    if name in ("latent_image", "latent", "samples"):
        latent = value
        if isinstance(latent, dict):
            latent = latent.get("samples")
        shape = getattr(latent, "shape", None)
        if shape is not None and len(shape) >= 4:
            return {"size": f"{int(shape[-1]) * 8}x{int(shape[-2]) * 8}"}

    if isinstance(value, (list, tuple)) and len(value) <= 32:
        items = []
        for item in value:
            item = _unwrap_single(item)
            if not isinstance(item, (str, int, float, bool, type(None))):
                return None
            items.append(item)
        return items

    return None


class ExecutionMetadataStore:
    """Thread-safe, bounded metadata snapshots keyed by prompt id."""

    def __init__(self, max_prompts=4):
        self._lock = threading.RLock()
        self._max_prompts = max_prompts
        self._prompts = OrderedDict()
        self._node_cache = {}

    def _prompt(self, prompt_id):
        prompt_id = str(prompt_id)
        data = self._prompts.get(prompt_id)
        if data is None:
            data = {"records": {}, "order": []}
            self._prompts[prompt_id] = data
            while len(self._prompts) > self._max_prompts:
                self._prompts.popitem(last=False)
        else:
            self._prompts.move_to_end(prompt_id)
        return data

    def record(self, prompt_id, node_id, class_name, input_data_all):
        if prompt_id is None or node_id is None:
            return

        inputs = {}
        for name, value in input_data_all.items():
            safe_value = _small_value(name, value)
            if safe_value is not None:
                inputs[name] = safe_value

        record = {
            "node_id": str(node_id),
            "class_name": str(class_name),
            "inputs": inputs,
        }

        with self._lock:
            data = self._prompt(prompt_id)
            node_key = str(node_id)
            if node_key not in data["records"]:
                data["order"].append(node_key)
            data["records"][node_key] = record
            self._node_cache[(node_key, str(class_name))] = record

    def snapshot(self, prompt_id):
        if prompt_id is None:
            return {"records": [], "cache": {}}

        with self._lock:
            data = self._prompts.get(str(prompt_id), {"records": {}, "order": []})
            records = [
                dict(data["records"][node_id])
                for node_id in data["order"]
                if node_id in data["records"]
            ]
            cache = {
                key: dict(value)
                for key, value in self._node_cache.items()
            }
            return {"records": records, "cache": cache}


def install_execution_metadata_hook():
    """Install a chain-safe hook on ComfyUI 0.29's resolved-input entrypoint."""
    try:
        import execution
    except ImportError:
        logger.warning("ComfyUI execution module unavailable; metadata hook disabled")
        return False

    if not hasattr(execution, _STORE_ATTR):
        setattr(execution, _STORE_ATTR, ExecutionMetadataStore())
    if not hasattr(execution, _CONTEXT_ATTR):
        setattr(
            execution,
            _CONTEXT_ATTR,
            contextvars.ContextVar("image_tools_prompt_id", default=None),
        )

    current = getattr(execution, "get_output_data", None)
    if current is None:
        logger.warning("ComfyUI get_output_data unavailable; metadata hook disabled")
        return False
    if getattr(current, _HOOK_MARKER, False):
        return True

    @functools.wraps(current)
    async def get_output_data_with_metadata(
        prompt_id,
        unique_id,
        obj,
        input_data_all,
        *args,
        **kwargs,
    ):
        context = getattr(execution, _CONTEXT_ATTR)
        token = context.set(str(prompt_id) if prompt_id is not None else None)
        try:
            store = getattr(execution, _STORE_ATTR)
            class_name = getattr(obj, "__name__", None)
            if class_name is None:
                class_name = obj.__class__.__name__
            store.record(prompt_id, unique_id, class_name, input_data_all)
            return await current(
                prompt_id,
                unique_id,
                obj,
                input_data_all,
                *args,
                **kwargs,
            )
        finally:
            context.reset(token)

    setattr(get_output_data_with_metadata, _HOOK_MARKER, True)
    execution.get_output_data = get_output_data_with_metadata
    logger.info("ComfyUI 0.29 execution metadata hook installed")
    return True


def get_current_execution_metadata():
    """Return the metadata snapshot for the node currently being executed."""
    try:
        import execution
    except ImportError:
        return {"records": [], "cache": {}}

    store = getattr(execution, _STORE_ATTR, None)
    context = getattr(execution, _CONTEXT_ATTR, None)
    if store is None or context is None:
        return {"records": [], "cache": {}}
    return store.snapshot(context.get())


def _python_class_name(class_type):
    try:
        import nodes as comfy_nodes

        node_class = comfy_nodes.NODE_CLASS_MAPPINGS.get(class_type)
        return getattr(node_class, "__name__", None)
    except Exception:
        return None


def _records_with_cache(snapshot, prompt_obj):
    records = list(snapshot.get("records", []))
    seen = {record["node_id"] for record in records}
    cache = snapshot.get("cache", {})

    if not isinstance(prompt_obj, dict):
        return records

    cached_records = []
    for node_id, node_data in prompt_obj.items():
        node_id = str(node_id)
        if node_id in seen or not isinstance(node_data, dict):
            continue
        class_name = _python_class_name(node_data.get("class_type", ""))
        if class_name and (node_id, class_name) in cache:
            cached_records.append(cache[(node_id, class_name)])

    return cached_records + records


def _ancestor_ids(prompt_obj, node_id):
    if not isinstance(prompt_obj, dict) or node_id is None:
        return set()

    ancestors = set()
    pending = [str(node_id)]
    while pending:
        current = pending.pop()
        if current in ancestors:
            continue
        ancestors.add(current)
        node = prompt_obj.get(current)
        if not isinstance(node, dict):
            continue
        for value in node.get("inputs", {}).values():
            if (
                isinstance(value, list)
                and len(value) == 2
                and isinstance(value[0], (str, int))
            ):
                pending.append(str(value[0]))
    return ancestors


def _class_label(record, prompt_obj):
    node = prompt_obj.get(record["node_id"], {}) if isinstance(prompt_obj, dict) else {}
    return f"{record.get('class_name', '')} {node.get('class_type', '')}".lower()


def _is_sampler_record(record, prompt_obj):
    label = _class_label(record, prompt_obj)
    inputs = record.get("inputs", {})
    excluded = ("config", "select", "scheduler", "provider")
    return (
        "sampler" in label
        and not any(word in label for word in excluded)
        and (
            "steps" in inputs
            or "cfg" in inputs
            or "seed" in inputs
            or "noise_seed" in inputs
            or "noise" in inputs
        )
    )


def _latest_value(records, prompt_obj, keys, label_words=()):
    for record in reversed(records):
        label = _class_label(record, prompt_obj)
        if label_words and not any(word in label for word in label_words):
            continue
        inputs = record.get("inputs", {})
        for key in keys:
            if key in inputs:
                return inputs[key]
    return None


def extract_execution_parameters(prompt_obj=None, save_node_id=None):
    """Build A1111 generation fields from resolved ComfyUI execution inputs."""
    snapshot = get_current_execution_metadata()
    records = _records_with_cache(snapshot, prompt_obj)
    if not records:
        return {}

    ancestors = _ancestor_ids(prompt_obj, save_node_id)
    relevant = [record for record in records if record["node_id"] in ancestors]
    if not any(_is_sampler_record(record, prompt_obj) for record in relevant):
        relevant = records

    sampler = None
    for record in reversed(relevant):
        if _is_sampler_record(record, prompt_obj):
            sampler = record
            break

    params = {}
    sampler_inputs = sampler.get("inputs", {}) if sampler else {}
    if sampler:
        params["sampler_node_id"] = sampler["node_id"]

    seed = sampler_inputs.get("seed", sampler_inputs.get("noise_seed"))
    noise = sampler_inputs.get("noise")
    if seed is None and isinstance(noise, dict):
        seed = noise.get("seed")
    if seed is None:
        seed = _latest_value(relevant, prompt_obj, ("seed", "noise_seed"))

    steps = sampler_inputs.get("steps")
    if steps is None:
        steps = _latest_value(relevant, prompt_obj, ("steps",), ("scheduler", "config"))

    cfg = sampler_inputs.get("cfg")
    if cfg is None:
        cfg = _latest_value(relevant, prompt_obj, ("cfg",), ("guider", "sampler", "config"))
    if cfg is None:
        cfg = _latest_value(relevant, prompt_obj, ("guidance",), ("guidance", "textencode"))

    sampler_name = sampler_inputs.get("sampler_name")
    if sampler_name is None:
        sampler_name = _latest_value(
            relevant, prompt_obj, ("sampler_name",), ("select", "sampler", "config")
        )

    scheduler = sampler_inputs.get("scheduler")
    if scheduler is None:
        scheduler = _latest_value(
            relevant, prompt_obj, ("scheduler",), ("scheduler", "sampler", "config")
        )

    size = sampler_inputs.get("latent_image")
    if isinstance(size, dict):
        size = size.get("size")

    for key, value in (
        ("seed", seed),
        ("steps", steps),
        ("cfg_scale", cfg),
        ("sampler", sampler_name),
        ("scheduler", scheduler),
        ("size", size),
    ):
        if value is not None:
            params[key] = value

    model_keys = ("ckpt_name", "unet_name", "gguf_name", "model_path")
    checkpoint = _latest_value(relevant, prompt_obj, model_keys)
    if checkpoint is None:
        for record in reversed(relevant):
            label = _class_label(record, prompt_obj)
            if (
                "loader" in label
                and not any(
                    word in label
                    for word in (
                        "upscale", "vae", "clip", "lora", "control",
                        "detector", "samloader",
                    )
                )
                and "model_name" in record.get("inputs", {})
            ):
                checkpoint = record["inputs"]["model_name"]
                break
    if checkpoint:
        params["checkpoint"] = checkpoint

    loras = []
    for record in relevant:
        inputs = record.get("inputs", {})
        lora_name = inputs.get("lora_name")
        if lora_name:
            strength = inputs.get("strength_model", inputs.get("strength", 1.0))
            loras.append(f"<lora:{lora_name}:{strength}>")
    if loras:
        params["loras"] = " ".join(dict.fromkeys(loras))

    return params
