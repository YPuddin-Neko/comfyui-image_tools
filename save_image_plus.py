"""
ComfyUI Image Selector - 保存图像增强版节点 (Save Image Plus)

移植自 ComfyUI-Danbooru-Gallery (https://github.com/Aaalice233/ComfyUI-Danbooru-Gallery)
在原版基础上进行了独立实现和改进：
- 内置适配 ComfyUI 0.29 的轻量执行期元数据收集器
- 保留独立哈希计算，不依赖原插件的 metadata_collector / hash_cache_manager
- 支持标准采样器与高级自定义采样器的真实运行参数
- 修复子工作流 (Group Node) 中无法保存的问题

支持直接传入提示词和 LoRA 语法，自动生成 A1111 格式的元数据
"""

import hashlib
import json
import os
import re
from pathlib import Path
from datetime import datetime
from PIL import Image
from PIL.PngImagePlugin import PngInfo
import numpy as np
import folder_paths
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    from .execution_metadata import extract_execution_parameters
except ImportError:
    def extract_execution_parameters(prompt_obj=None, save_node_id=None):
        return {}


class SaveImagePlus:
    """
    保存图像增强版节点
    支持直接传入提示词和 LoRA 语法，自动生成 A1111 格式的元数据
    支持 PNG/JPEG/WEBP 格式，支持文件名占位符
    """

    def __init__(self):
        self.output_dir = folder_paths.get_output_directory()
        self.type = "output"
        self.prefix_append = ""
        self.compress_level = 4

        # 占位符正则表达式模式
        self.pattern_format = re.compile(r"(%[^%]+%)")

        # Sampler 名称映射表（ComfyUI 内部名 → A1111 用户友好名）
        self.sampler_mapping = {
            'euler': 'Euler',
            'euler_ancestral': 'Euler a',
            'heun': 'Heun',
            'dpm_2': 'DPM2',
            'dpm_2_ancestral': 'DPM2 a',
            'lms': 'LMS',
            'dpm_fast': 'DPM fast',
            'dpm_adaptive': 'DPM adaptive',
            'dpmpp_2s_ancestral': 'DPM++ 2S a',
            'dpmpp_sde': 'DPM++ SDE',
            'dpmpp_2m': 'DPM++ 2M',
            'ddim': 'DDIM',
            'uni_pc': 'UniPC',
        }

        # Scheduler 名称映射表（ComfyUI 内部名 → A1111 后缀）
        self.scheduler_mapping = {
            'normal': 'Simple',
            'karras': 'Karras',
            'exponential': 'Exponential',
            'sgm_uniform': 'SGM Uniform',
        }

        # 初始化线程池（用于并行计算哈希）
        self.hash_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="HashCalc")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE", {
                    "tooltip": "要保存的图像"
                }),
                "enable": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "是否保存图像（关闭时节点不执行）"
                }),
                "filename_prefix": ("STRING", {
                    "default": "ComfyUI",
                    "tooltip": "文件名前缀，支持占位符: %date:yyyyMMdd%, %seed%, %model%"
                }),
                "file_format": (["PNG", "JPEG", "WEBP"], {
                    "default": "PNG",
                    "tooltip": "图像保存格式"
                }),
                "quality": ("INT", {
                    "default": 100,
                    "min": 1,
                    "max": 100,
                    "step": 1,
                    "tooltip": "JPEG/WebP 质量（1-100）"
                }),
                "embed_workflow": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "是否嵌入 ComfyUI 工作流数据（仅 PNG 格式支持）"
                }),
                "save_clean_copy": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "额外保存无工作流和元数据的纯净副本"
                }),
                "enable_preview": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "是否在界面显示预览（关闭后仅保存文件）"
                }),
                "save_prompt_txt": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "保存同名 .txt 文件，包含正向提示词（适合训练数据集）"
                }),
                "use_custom_path": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "开启后使用自定义保存路径，关闭时使用 ComfyUI 默认输出目录"
                }),
                "custom_save_path": ("STRING", {
                    "default": "",
                    "tooltip": "自定义保存路径（仅当 use_custom_path 开启时生效），支持绝对路径"
                }),
            },
            "optional": {
                "positive_prompt": ("STRING", {
                    "forceInput": True,
                    "tooltip": "正面提示词（可选直接输入）"
                }),
                "negative_prompt": ("STRING", {
                    "forceInput": True,
                    "tooltip": "负面提示词（可选直接输入）"
                }),
                "lora_syntax": ("STRING", {
                    "forceInput": True,
                    "tooltip": "LoRA 语法字符串（可选直接输入）"
                }),
                "checkpoint_name": ("STRING", {
                    "forceInput": True,
                    "tooltip": "手动传入 checkpoint 模型名称（优先级最高）"
                }),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    RETURN_TYPES = ()
    FUNCTION = "save_images"
    OUTPUT_NODE = True
    CATEGORY = "image/utils"
    DESCRIPTION = "保存图像并嵌入 A1111 格式元数据，支持直接传入提示词和 LoRA 语法"

    # ============================
    # 文件名处理
    # ============================

    def _sanitize_filename(self, name):
        """清理文件名中的非法字符，确保跨平台兼容性"""
        if not name:
            return ""
        name = name.replace("/", "_").replace("\\", "_")
        name = os.path.splitext(name)[0]
        name = re.sub(r'[^\w\-\u4e00-\u9fff]+', '_', name)
        name = re.sub(r'_+', '_', name)
        name = name.strip('_')
        return name

    def format_filename(self, filename, prompt_obj=None, metadata=None):
        """
        解析文件名中的占位符
        支持: %date%, %date:yyyyMMdd%, %seed%, %model%
        """
        result = re.findall(self.pattern_format, filename)

        for segment in result:
            parts = segment.replace("%", "").split(":")
            key = parts[0]

            if key == "date":
                now = datetime.now()
                date_table = {
                    "yyyy": f"{now.year:04d}",
                    "yy": f"{now.year % 100:02d}",
                    "MM": f"{now.month:02d}",
                    "dd": f"{now.day:02d}",
                    "hh": f"{now.hour:02d}",
                    "mm": f"{now.minute:02d}",
                    "ss": f"{now.second:02d}",
                }
                date_format = parts[1] if len(parts) >= 2 else "yyyyMMddhhmmss"
                for k, v in date_table.items():
                    date_format = date_format.replace(k, v)
                filename = filename.replace(segment, date_format)

            elif key == "seed" and prompt_obj:
                seed = self._extract_seed_from_prompt(prompt_obj)
                if seed is not None:
                    filename = filename.replace(segment, str(seed))

            elif key == "model" and metadata:
                checkpoint = metadata.get("checkpoint")
                if checkpoint:
                    model_name = self._sanitize_filename(os.path.basename(checkpoint))
                    filename = filename.replace(segment, model_name or "unknown_model")
                else:
                    filename = filename.replace(segment, "unknown_model")

        return filename

    def _resolve_value(self, prompt_obj, value, depth=0, field=None):
        """
        解析值引用链
        在 ComfyUI 的 prompt 中，输入值可能是:
        - 直接值: 12345
        - 引用: ["node_id", output_index] 指向另一个节点的输出
        解析时优先使用引用的 output_index 和目标字段语义，避免从多输出
        节点中随意取第一个数值。
        """
        # 防止无限递归
        if depth > 10:
            return value

        # 如果是引用格式 ["node_id", output_index]
        if isinstance(value, list) and len(value) == 2:
            ref_node_id = str(value[0])
            if ref_node_id in prompt_obj and isinstance(prompt_obj[ref_node_id], dict):
                ref_node = prompt_obj[ref_node_id]
                ref_inputs = ref_node.get("inputs", {})

                # ComfyUI 链接的第二项是输出槽索引。优先读取节点声明的
                # RETURN_NAMES，才能正确区分 KSampler Config 等多输出节点。
                output_name = None
                try:
                    import nodes as comfy_nodes

                    node_class = comfy_nodes.NODE_CLASS_MAPPINGS.get(
                        ref_node.get("class_type", "")
                    )
                    return_names = getattr(node_class, "RETURN_NAMES", ())
                    output_index = int(value[1])
                    if 0 <= output_index < len(return_names):
                        output_name = str(return_names[output_index])
                except Exception:
                    output_name = None

                alias_groups = (
                    ("seed", "noise_seed", "seed_num"),
                    ("steps", "steps_total", "step"),
                    ("refiner_step", "refiner_steps"),
                    ("cfg", "cfg_scale", "guidance", "guidance_scale", "scale"),
                    ("sampler", "sampler_name"),
                    ("scheduler", "scheduler_name"),
                    ("checkpoint", "ckpt_name", "model_name", "unet_name"),
                )

                def aliases_for(name):
                    if not name:
                        return ()
                    normalized = str(name).lower()
                    for aliases in alias_groups:
                        if normalized in {alias.lower() for alias in aliases}:
                            return aliases
                    return (name,)

                candidate_fields = []
                generic_fields = (
                    "value", "number", "int", "float", "string", "text",
                    "Value", "SEED",
                )
                for candidate in (
                    aliases_for(output_name) + aliases_for(field) + generic_fields
                ):
                    if candidate not in candidate_fields:
                        candidate_fields.append(candidate)

                for key in candidate_fields:
                    if key in ref_inputs:
                        return self._resolve_value(
                            prompt_obj,
                            ref_inputs[key],
                            depth + 1,
                            field=field or output_name,
                        )

                # 单输入 Primitive 节点可以安全回退；多输入节点解析不明确时
                # 保留原链接，不再猜测第一个数字。
                scalar_values = [
                    val for val in ref_inputs.values()
                    if isinstance(val, (str, int, float, bool))
                ]
                if len(scalar_values) == 1:
                    return scalar_values[0]
            return value

        return value

    def _extract_seed_from_prompt(self, prompt_obj):
        """从 prompt 对象中提取 seed 值，支持引用链追踪"""
        if not prompt_obj:
            return None

        actual_prompt = prompt_obj
        if isinstance(prompt_obj, dict) and 'original_prompt' in prompt_obj:
            actual_prompt = prompt_obj['original_prompt']

        # 支持的采样器节点类型（包括常见的自定义采样器）
        sampler_types = [
            'KSampler', 'KSamplerAdvanced', 'SamplerCustom', 'SamplerCustomAdvanced',
            # Easy-use 系列
            'easy kSampler', 'easy kSamplerSDTurbo', 'easy fullkSampler',
            'easy kSamplerInpainting', 'easy kSamplerDownscaleUnet',
            # Efficiency 系列
            'KSampler (Efficient)', 'KSampler Adv. (Efficient)',
            # Impact 系列
            'KSamplerProvider', 'BasicScheduler',
        ]

        seed_fields = ['seed', 'noise_seed', 'seed_num']

        # 第一轮：优先查找采样器节点的 seed
        for node_id, node_data in actual_prompt.items():
            if isinstance(node_data, dict):
                class_type = node_data.get("class_type", "")
                if class_type in sampler_types and "inputs" in node_data:
                    inputs = node_data.get("inputs", {})
                    for field in seed_fields:
                        if field in inputs:
                            resolved = self._resolve_value(
                                actual_prompt, inputs[field], field="seed"
                            )
                            if isinstance(resolved, (int, float)) and int(resolved) >= 0:
                                return int(resolved)

        # 第二轮：查找全局种子节点（如 easy globalSeed, Seed 等）
        global_seed_types = [
            'easy globalSeed', 'Seed', 'SeedNode', 'CR Seed',
            'Seed (rgthree)', 'GlobalSeed',
        ]
        for node_id, node_data in actual_prompt.items():
            if isinstance(node_data, dict):
                class_type = node_data.get("class_type", "")
                if class_type in global_seed_types and "inputs" in node_data:
                    inputs = node_data.get("inputs", {})
                    for field in seed_fields + ['value', 'Value']:
                        if field in inputs:
                            resolved = self._resolve_value(
                                actual_prompt, inputs[field], field="seed"
                            )
                            if isinstance(resolved, (int, float)) and int(resolved) >= 0:
                                return int(resolved)

        # 第三轮：查找任何包含 seed 的节点
        for node_id, node_data in actual_prompt.items():
            if isinstance(node_data, dict) and "inputs" in node_data:
                inputs = node_data.get("inputs", {})
                for field in seed_fields:
                    if field in inputs:
                        resolved = self._resolve_value(
                            actual_prompt, inputs[field], field="seed"
                        )
                        if isinstance(resolved, (int, float)) and int(resolved) >= 0:
                            return int(resolved)

        return None

    # ============================
    # 哈希计算
    # ============================

    def _get_lora_hash(self, lora_name):
        """获取 LoRA 哈希值"""
        return self._calculate_lora_hash(lora_name)

    def _get_checkpoint_hash(self, checkpoint_name):
        """获取 checkpoint 哈希值"""
        return self._calculate_checkpoint_hash(checkpoint_name)

    def _calculate_lora_hash(self, lora_name):
        """
        计算 LoRA 文件的 SHA256 哈希，取前 10 个字符
        与 A1111/LoRA Manager 格式一致
        """
        try:
            lora_paths = folder_paths.get_filename_list("loras")
            lora_file = None

            for path in lora_paths:
                if os.path.splitext(os.path.basename(path))[0] == lora_name:
                    lora_file = folder_paths.get_full_path("loras", path)
                    break

            if not lora_file or not os.path.exists(lora_file):
                return ""

            sha256_hash = hashlib.sha256()
            with open(lora_file, "rb") as f:
                for byte_block in iter(lambda: f.read(128 * 1024), b""):
                    sha256_hash.update(byte_block)

            return sha256_hash.hexdigest()[:10]

        except Exception:
            return ""

    def _calculate_checkpoint_hash(self, checkpoint_name):
        """
        计算 checkpoint 文件的 SHA256 哈希，取前 10 个字符
        """
        try:
            if os.path.isabs(checkpoint_name) and os.path.exists(checkpoint_name):
                checkpoint_file = checkpoint_name
            else:
                checkpoint_file = None
                base_name = os.path.splitext(os.path.basename(checkpoint_name))[0].lower()

                for folder_type in ("checkpoints", "diffusion_models", "unet"):
                    try:
                        paths = folder_paths.get_filename_list(folder_type)
                    except Exception:
                        continue
                    for path in paths:
                        if os.path.splitext(os.path.basename(path))[0].lower() == base_name:
                            checkpoint_file = folder_paths.get_full_path(folder_type, path)
                            break
                    if checkpoint_file:
                        break

            if not checkpoint_file or not os.path.exists(checkpoint_file):
                return ""

            sha256_hash = hashlib.sha256()
            with open(checkpoint_file, "rb") as f:
                for byte_block in iter(lambda: f.read(128 * 1024), b""):
                    sha256_hash.update(byte_block)

            return sha256_hash.hexdigest()[:10]

        except Exception:
            return ""

    def _calculate_lora_hashes_parallel(self, lora_names):
        """并行计算多个 LoRA 的哈希值"""
        if not lora_names:
            return {}

        result = {}

        if len(lora_names) == 1:
            hash_value = self._calculate_lora_hash(lora_names[0])
            if hash_value:
                result[lora_names[0]] = hash_value
            return result

        futures = {}
        for lora_name in lora_names:
            future = self.hash_executor.submit(self._calculate_lora_hash, lora_name)
            futures[future] = lora_name

        for future in as_completed(futures):
            lora_name = futures[future]
            try:
                hash_value = future.result()
                if hash_value:
                    result[lora_name] = hash_value
            except Exception:
                pass

        return result

    # ============================
    # 元数据收集
    # ============================

    def _collect_metadata(self, positive_prompt=None, negative_prompt=None,
                          lora_syntax=None, checkpoint_name=None, prompt_obj=None,
                          unique_id=None):
        """
        收集元数据（五级降级策略）
        级别0: 手动传入 checkpoint
        级别1: 直接传入的 prompt/lora
        级别2: 从 ComfyUI 执行期已解析输入收集参数
        级别3: 从 prompt_obj 解析字面量作为兜底
        级别4: 从 prompt 文本提取 LoRA
        """
        result = {
            "prompt": "",
            "negative_prompt": "",
            "loras": "",
            "steps": None,
            "sampler": None,
            "scheduler": None,
            "cfg_scale": None,
            "seed": None,
            "size": None,
            "checkpoint": None,
        }

        # 级别 0: 手动传入的 checkpoint 名称（最高优先级）
        if checkpoint_name:
            result["checkpoint"] = checkpoint_name

        # 级别 1: 直接传入的值
        if positive_prompt:
            result["prompt"] = positive_prompt
        if negative_prompt:
            result["negative_prompt"] = negative_prompt
        if lora_syntax:
            result["loras"] = lora_syntax

        # 级别 2: 执行期输入已经由 ComfyUI 解析为真实值。
        runtime_params = extract_execution_parameters(prompt_obj, unique_id)
        runtime_fields = {
            "prompt": "prompt",
            "negative_prompt": "negative_prompt",
            "loras": "loras",
            "steps": "steps",
            "sampler": "sampler",
            "scheduler": "scheduler",
            "cfg_scale": "cfg_scale",
            "seed": "seed",
            "size": "size",
            "checkpoint": "checkpoint",
        }
        for result_key, runtime_key in runtime_fields.items():
            value = runtime_params.get(runtime_key)
            if value is None or value == "":
                continue
            if result_key in ("prompt", "negative_prompt", "loras"):
                if not result[result_key]:
                    result[result_key] = value
            elif result[result_key] is None:
                result[result_key] = value

        # 级别 3: prompt 图只用于字面量和旧版 ComfyUI 的降级路径。
        if prompt_obj:
            self._extract_params_from_prompt(prompt_obj, result)

        # 级别 4: 从正面提示词中提取 LoRA
        if not result["loras"] and result["prompt"]:
            lora_pattern = r'<lora:[^>]+>'
            loras_found = re.findall(lora_pattern, result["prompt"])
            if loras_found:
                result["loras"] = ", ".join(loras_found)

        return result

    def _extract_params_from_prompt(self, prompt_obj, result):
        """
        从 ComfyUI prompt 对象中独立解析生成参数
        扫描所有节点，提取 KSampler、CheckpointLoader 等节点的参数
        """
        actual_prompt = prompt_obj
        if isinstance(prompt_obj, dict) and 'original_prompt' in prompt_obj:
            actual_prompt = prompt_obj['original_prompt']

        for node_id, node_data in actual_prompt.items():
            if not isinstance(node_data, dict):
                continue

            class_type = node_data.get("class_type", "")
            inputs = node_data.get("inputs", {})

            # 提取 KSampler 参数（支持多种采样器节点）
            sampler_class_types = (
                'KSampler', 'KSamplerAdvanced', 'SamplerCustom', 'SamplerCustomAdvanced',
                'easy kSampler', 'easy kSamplerSDTurbo', 'easy fullkSampler',
                'easy kSamplerInpainting', 'easy kSamplerDownscaleUnet',
                'KSampler (Efficient)', 'KSampler Adv. (Efficient)',
            )
            if class_type in sampler_class_types:
                if result["steps"] is None and "steps" in inputs:
                    val = self._resolve_value(
                        actual_prompt, inputs["steps"], field="steps"
                    )
                    if isinstance(val, (int, float)):
                        result["steps"] = int(val)
                if result["sampler"] is None and "sampler_name" in inputs:
                    val = self._resolve_value(
                        actual_prompt, inputs["sampler_name"], field="sampler_name"
                    )
                    if isinstance(val, str):
                        result["sampler"] = val
                if result["scheduler"] is None and "scheduler" in inputs:
                    val = self._resolve_value(
                        actual_prompt, inputs["scheduler"], field="scheduler"
                    )
                    if isinstance(val, str):
                        result["scheduler"] = val
                if result["seed"] is None:
                    for field in ["seed", "noise_seed", "seed_num"]:
                        if field in inputs:
                            val = self._resolve_value(
                                actual_prompt, inputs[field], field="seed"
                            )
                            if isinstance(val, (int, float)) and int(val) >= 0:
                                result["seed"] = int(val)
                                break
                if result["cfg_scale"] is None and "cfg" in inputs:
                    val = self._resolve_value(
                        actual_prompt, inputs["cfg"], field="cfg"
                    )
                    if isinstance(val, (int, float)):
                        result["cfg_scale"] = val

            # 提取 Checkpoint 名称
            if class_type in ('CheckpointLoaderSimple', 'CheckpointLoader') and result["checkpoint"] is None:
                if "ckpt_name" in inputs:
                    result["checkpoint"] = inputs["ckpt_name"]

            # 提取 CLIP Text Encode 的提示词
            if class_type == 'CLIPTextEncode' and "text" in inputs:
                text = inputs["text"]
                if isinstance(text, str) and text.strip():
                    # 简单启发式：较长的文本视为正面提示词
                    if not result["prompt"]:
                        result["prompt"] = text

    # ============================
    # 元数据格式化
    # ============================

    def _format_metadata(self, metadata):
        """格式化元数据为 A1111 文本格式"""
        if not metadata:
            return ""

        prompt = metadata.get("prompt", "")
        negative_prompt = metadata.get("negative_prompt", "")
        loras_text = metadata.get("loras", "")

        # 计算 LoRA hashes
        lora_hashes = {}
        if loras_text:
            lora_matches = re.findall(r'<lora:([^:>]+)(?::([^>]+))?>', loras_text)
            lora_names = [match[0] for match in lora_matches]

            if len(lora_names) > 1:
                lora_hashes = self._calculate_lora_hashes_parallel(lora_names)
            else:
                for lora_name in lora_names:
                    hash_value = self._get_lora_hash(lora_name)
                    if hash_value:
                        lora_hashes[lora_name] = hash_value

        # 第一部分：prompt（含 LoRA）
        metadata_parts = []
        if loras_text:
            prompt_with_loras = f"{prompt}\n{loras_text}" if prompt else loras_text
            metadata_parts.append(prompt_with_loras)
        else:
            metadata_parts.append(prompt)

        # 第二部分：Negative prompt
        metadata_parts.append(f"Negative prompt: {negative_prompt}")

        # 第三部分：参数列表
        params = []

        if metadata.get("steps") is not None:
            params.append(f"Steps: {metadata['steps']}")

        # Sampler（合并 Scheduler）
        sampler_name = None
        scheduler_name = None
        if metadata.get("sampler"):
            sampler_name = self.sampler_mapping.get(metadata["sampler"], metadata["sampler"])
        if metadata.get("scheduler"):
            scheduler_name = self.scheduler_mapping.get(metadata["scheduler"], metadata["scheduler"])
        if sampler_name:
            if scheduler_name:
                params.append(f"Sampler: {sampler_name} {scheduler_name}")
            else:
                params.append(f"Sampler: {sampler_name}")

        if metadata.get("cfg_scale") is not None:
            params.append(f"CFG scale: {metadata['cfg_scale']}")

        if metadata.get("seed") is not None:
            params.append(f"Seed: {metadata['seed']}")

        if metadata.get("size"):
            params.append(f"Size: {metadata['size']}")

        # Model hash 和 Model name
        if metadata.get("checkpoint"):
            checkpoint = metadata["checkpoint"]
            model_hash = self._get_checkpoint_hash(checkpoint)
            checkpoint_name = os.path.splitext(os.path.basename(checkpoint))[0]
            if model_hash:
                params.append(f"Model hash: {model_hash[:10]}, Model: {checkpoint_name}")
            else:
                params.append(f"Model: {checkpoint_name}")

        # Lora hashes
        if lora_hashes:
            lora_hash_parts = [f"{name}: {h[:10]}" for name, h in lora_hashes.items()]
            if lora_hash_parts:
                params.append(f"Lora hashes: \"{', '.join(lora_hash_parts)}\"")

        if params:
            metadata_parts.append(", ".join(params))

        return "\n".join(metadata_parts)

    # ============================
    # 主保存方法
    # ============================

    def save_images(self, images, enable=True, filename_prefix="ComfyUI",
                    file_format="PNG", quality=100, embed_workflow=True,
                    save_clean_copy=False, enable_preview=False,
                    save_prompt_txt=False,
                    use_custom_path=False, custom_save_path="",
                    positive_prompt=None, negative_prompt=None,
                    lora_syntax=None, checkpoint_name=None,
                    unique_id=None, prompt=None, extra_pnginfo=None):
        """
        保存图像主方法
        支持 PNG/JPEG/WEBP 格式，可嵌入 A1111 元数据和工作流
        """
        if not enable:
            return {"ui": {"images": []}}

        # 收集元数据
        metadata = self._collect_metadata(
            positive_prompt=positive_prompt,
            negative_prompt=negative_prompt,
            lora_syntax=lora_syntax,
            checkpoint_name=checkpoint_name,
            prompt_obj=prompt,
            unique_id=unique_id,
        )

        if metadata["size"] is None and len(images) > 0:
            metadata["size"] = f"{int(images[0].shape[1])}x{int(images[0].shape[0])}"

        # 格式化元数据
        formatted_metadata = self._format_metadata(metadata)

        # 准备保存目录
        filename_prefix += self.prefix_append
        filename_prefix = self.format_filename(filename_prefix, prompt_obj=prompt, metadata=metadata)

        # 根据开关选择保存目录
        if use_custom_path and custom_save_path.strip():
            # 使用用户指定的自定义路径
            output_dir = custom_save_path.strip()
            os.makedirs(output_dir, exist_ok=True)
            # 自定义路径模式：直接在指定目录下保存
            full_output_folder = output_dir
            filename = filename_prefix
            subfolder = ""
            # 查找已存在的文件数来确定 counter
            existing = [f for f in os.listdir(full_output_folder) if f.startswith(filename)] if os.path.exists(full_output_folder) else []
            counter = len(existing) + 1
        else:
            # 使用 ComfyUI 默认输出目录
            output_dir = folder_paths.get_output_directory()
            try:
                full_output_folder, filename, counter, subfolder, filename_prefix = \
                    folder_paths.get_save_image_path(filename_prefix, output_dir, images[0].shape[1], images[0].shape[0])
            except Exception:
                full_output_folder = output_dir
                filename = filename_prefix
                counter = 1
                subfolder = ""
                existing = [f for f in os.listdir(full_output_folder) if f.startswith(filename)] if os.path.exists(full_output_folder) else []
                counter = len(existing) + 1

        os.makedirs(full_output_folder, exist_ok=True)

        results = []

        for batch_number, image in enumerate(images):
            # 转换图像格式
            i = 255. * image.cpu().numpy()
            img = Image.fromarray(np.clip(i, 0, 255).astype(np.uint8))

            # 构建文件名
            file = f"{filename}_{counter:05}_.{file_format.lower()}"
            file_path = os.path.join(full_output_folder, file)

            # 根据格式保存
            if file_format == "PNG":
                metadata_png = PngInfo()
                if formatted_metadata:
                    metadata_png.add_text("parameters", formatted_metadata)
                if embed_workflow and extra_pnginfo is not None:
                    for key, value in extra_pnginfo.items():
                        metadata_png.add_text(key, json.dumps(value))
                img.save(file_path, format="PNG", pnginfo=metadata_png, compress_level=self.compress_level)

            elif file_format in ["JPEG", "WEBP"]:
                exif_data = img.getexif()
                if formatted_metadata:
                    exif_data[0x9286] = formatted_metadata.encode('utf-16')
                if file_format == "JPEG":
                    img.save(file_path, quality=quality, exif=exif_data)
                else:
                    img.save(file_path, quality=quality, exif=exif_data, method=6)

            results.append({
                "filename": file,
                "subfolder": subfolder,
                "type": self.type
            })

            # 保存纯净副本
            if save_clean_copy:
                clean_file = f"{filename}_{counter:05}_no_metadata.{file_format.lower()}"
                clean_path = os.path.join(full_output_folder, clean_file)
                if file_format == "PNG":
                    img.save(clean_path, compress_level=self.compress_level)
                elif file_format == "JPEG":
                    img.save(clean_path, quality=quality)
                else:
                    img.save(clean_path, quality=quality, method=6)
                results.append({
                    "filename": clean_file,
                    "subfolder": subfolder,
                    "type": self.type
                })

            # 保存提示词 txt 文件
            if save_prompt_txt:
                prompt_text = metadata.get("prompt", "")
                if prompt_text:
                    txt_file = f"{filename}_{counter:05}_.txt"
                    txt_path = os.path.join(full_output_folder, txt_file)
                    with open(txt_path, "w", encoding="utf-8") as f:
                        f.write(prompt_text)

            counter += 1

        if enable_preview:
            return {"ui": {"images": results}}
        else:
            return {"ui": {"images": []}}


# ============================
# 节点注册
# ============================
NODE_CLASS_MAPPINGS = {
    "IS_SaveImagePlus": SaveImagePlus,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "IS_SaveImagePlus": "Save Image Plus | 保存图像增强版",
}
