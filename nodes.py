"""
ComfyUI Image Selector - 节点定义
提供图片选择器节点，支持用户在前端弹窗中手动选择图片
"""

import torch
import numpy as np
import base64
import json
import io
import os
import uuid
import asyncio
from PIL import Image
from aiohttp import web

from server import PromptServer
from nodes import interrupt_processing

# ============================
# 全局图片缓存（用于前后端通信）
# ============================
IMAGE_CACHE = {}  # session_id -> { "images": tensor, "selected": None or list }
SELECTION_EVENTS = {}  # session_id -> asyncio.Event

# 插件根目录（用于定位提示音文件）
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))


def tensor_to_base64(tensor_image):
    """将单张图片 tensor [H, W, C] 转为 base64 字符串"""
    # tensor 值域 [0, 1], 转 uint8
    img_np = (tensor_image.cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
    img = Image.fromarray(img_np)
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


# ============================
# 自定义 API 路由
# ============================
@PromptServer.instance.routes.post("/image_selector/get_images")
async def get_images(request):
    """前端获取待选图片列表"""
    data = await request.json()
    session_id = data.get("session_id", "")
    
    if session_id not in IMAGE_CACHE:
        return web.json_response({"error": "Session not found"}, status=404)
    
    cache = IMAGE_CACHE[session_id]
    images_tensor = cache["images"]
    batch_size = images_tensor.shape[0]
    
    # 转换所有图片为 base64
    images_b64 = []
    for i in range(batch_size):
        b64 = tensor_to_base64(images_tensor[i])
        images_b64.append({
            "index": i,
            "data": f"data:image/jpeg;base64,{b64}",
            "width": int(images_tensor[i].shape[1]),
            "height": int(images_tensor[i].shape[0]),
        })
    
    return web.json_response({"images": images_b64, "total": batch_size})


@PromptServer.instance.routes.post("/image_selector/submit_selection")
async def submit_selection(request):
    """前端提交用户选择结果"""
    data = await request.json()
    session_id = data.get("session_id", "")
    selected_indices = data.get("selected_indices", [])
    cancelled = data.get("cancelled", False)
    
    if session_id not in IMAGE_CACHE:
        return web.json_response({"error": "Session not found"}, status=404)
    
    if cancelled:
        # 用户取消或未选择任何图片 -> 标记为取消
        IMAGE_CACHE[session_id]["cancelled"] = True
        IMAGE_CACHE[session_id]["selected"] = []
    else:
        IMAGE_CACHE[session_id]["cancelled"] = False
        IMAGE_CACHE[session_id]["selected"] = selected_indices
    
    # 通知等待中的节点
    if session_id in SELECTION_EVENTS:
        SELECTION_EVENTS[session_id].set()
    
    return web.json_response({"status": "ok"})


@PromptServer.instance.routes.get("/image_selector/pending_sessions")
async def get_pending_sessions(request):
    """返回所有待处理的选择会话（selected 仍为 None 的会话）"""
    pending = []
    for session_id, cache in IMAGE_CACHE.items():
        if cache["selected"] is None and not cache.get("cancelled", False):
            params = cache.get("dialog_params")
            if params:
                pending.append(params)
    return web.json_response({"sessions": pending})


@PromptServer.instance.routes.get("/image_selector/sound/{filename}")
async def get_sound_file(request):
    """提供提示音文件的访问"""
    filename = request.match_info["filename"]
    # 安全性：只允许 wav/mp3 文件，防止路径穿越
    if ".." in filename or "/" in filename or "\\" in filename:
        return web.Response(status=403)
    
    sound_path = os.path.join(PLUGIN_DIR, "sound", filename)
    if not os.path.exists(sound_path):
        return web.Response(status=404, text="Sound file not found")
    
    return web.FileResponse(sound_path)


# ============================
# 图片选择器节点
# ============================
class ImageSelector:
    """
    图片选择器节点
    接收一个图片批次输入，弹出选择窗口让用户选择需要的图片
    未选择或取消时将中断工作流
    """
    
    def __init__(self):
        pass
    
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "images": ("IMAGE",),
            },
            "optional": {
                "sound_enabled": ("BOOLEAN", {
                    "default": True,
                    "label_on": "开启提示音",
                    "label_off": "关闭提示音",
                    "tooltip": "弹窗时是否播放提示音"
                }),
                "sound_volume": ("FLOAT", {
                    "default": 0.5,
                    "min": 0.0,
                    "max": 1.0,
                    "step": 0.05,
                    "tooltip": "提示音音量 (0.0~1.0)"
                }),
                "timeout": ("INT", {
                    "default": 300,
                    "min": 10,
                    "max": 3600,
                    "step": 10,
                    "tooltip": "图片选择超时时间（秒），超时将中断工作流"
                }),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
                "prompt": "PROMPT",
            },
        }
    
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    
    FUNCTION = "select_images"
    
    CATEGORY = "image/utils"
    
    OUTPUT_NODE = False
    
    def select_images(self, images, sound_enabled=True, sound_volume=0.5, timeout=300, unique_id=None, prompt=None):
        """
        主函数：缓存图片，通知前端弹窗，等待用户选择，返回选中图片
        取消或未选择时中断工作流
        """
        batch_size = images.shape[0]
        
        # 生成会话 ID
        session_id = f"{unique_id}_{uuid.uuid4().hex[:8]}"
        
        # 缓存图片和弹窗参数
        IMAGE_CACHE[session_id] = {
            "images": images,
            "selected": None,
            "cancelled": False,
            "dialog_params": {
                "session_id": session_id,
                "total_images": batch_size,
                "node_id": unique_id,
                "sound_enabled": sound_enabled,
                "sound_volume": sound_volume,
                "sound_file": "din.wav",
                "timeout": timeout,
            },
        }
        
        # 创建异步事件
        event = asyncio.Event()
        SELECTION_EVENTS[session_id] = event
        
        # 通知前端弹出选择窗口
        PromptServer.instance.send_sync(
            "image_selector.show_dialog",
            {
                "session_id": session_id,
                "total_images": batch_size,
                "node_id": unique_id,
                "sound_enabled": sound_enabled,
                "sound_volume": sound_volume,
                "sound_file": "din.wav",
                "timeout": timeout,
            }
        )
        
        # 同步等待用户选择（使用 polling + tick 广播）
        import time
        start_time = time.time()
        last_tick_time = 0
        TICK_INTERVAL = 2  # 每2秒广播一次 tick，确保切换回来时前端能恢复弹窗
        
        while IMAGE_CACHE[session_id]["selected"] is None:
            elapsed = time.time() - start_time
            if elapsed > timeout:
                # 清理缓存
                self._cleanup(session_id)
                PromptServer.instance.send_sync(
                    "image_selector.interrupted",
                    {"reason": f"图片选择超时（{timeout}秒），工作流已中断", "node_id": unique_id}
                )
                interrupt_processing()
                return (torch.zeros(1, 1, 1, 3),)
            
            # 定期广播 tick 消息，前端收到后会检查弹窗是否已打开
            # 这是确保用户切换工作流再切回来时弹窗能恢复的关键机制
            if time.time() - last_tick_time >= TICK_INTERVAL:
                remaining = int(timeout - elapsed)
                PromptServer.instance.send_sync(
                    "image_selector.tick",
                    {
                        "session_id": session_id,
                        "node_id": unique_id,
                        "remaining": remaining,
                        "total_images": batch_size,
                        "sound_enabled": sound_enabled,
                        "sound_volume": sound_volume,
                        "sound_file": "din.wav",
                        "timeout": timeout,
                    }
                )
                last_tick_time = time.time()
            
            time.sleep(0.1)
        
        # 检查是否取消
        cancelled = IMAGE_CACHE[session_id].get("cancelled", False)
        selected_indices = IMAGE_CACHE[session_id]["selected"]
        
        # 清理缓存
        self._cleanup(session_id)
        
        if cancelled or not selected_indices:
            # 用户取消或未选择任何图片 -> 静默中断整个工作流
            PromptServer.instance.send_sync(
                "image_selector.interrupted",
                {"reason": "没有图片被选择，工作流已中断", "node_id": unique_id}
            )
            interrupt_processing()
            return (torch.zeros(1, 1, 1, 3),)
        
        # 根据选择索引提取图片
        selected_images = torch.stack([images[i] for i in selected_indices])
        
        return (selected_images,)
    
    def _cleanup(self, session_id):
        """清理缓存"""
        if session_id in IMAGE_CACHE:
            del IMAGE_CACHE[session_id]
        if session_id in SELECTION_EVENTS:
            del SELECTION_EVENTS[session_id]


# ============================
# 节点注册
# ============================
from .save_image_plus import NODE_CLASS_MAPPINGS as SAVE_CLASS_MAPPINGS
from .save_image_plus import NODE_DISPLAY_NAME_MAPPINGS as SAVE_DISPLAY_MAPPINGS
from .image_compare import NODE_CLASS_MAPPINGS as COMPARE_CLASS_MAPPINGS
from .image_compare import NODE_DISPLAY_NAME_MAPPINGS as COMPARE_DISPLAY_MAPPINGS

NODE_CLASS_MAPPINGS = {
    "ImageSelector": ImageSelector,
    **SAVE_CLASS_MAPPINGS,
    **COMPARE_CLASS_MAPPINGS,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ImageSelector": "🖼️ Image Selector | 图片选择器",
    **SAVE_DISPLAY_MAPPINGS,
    **COMPARE_DISPLAY_MAPPINGS,
}
