"""
ComfyUI Image Tools - 图片工具箱
包含图片选择器、图片对比、潜空间生成器、保存图像增强版、性能监控等功能
"""

from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

WEB_DIRECTORY = "./web/js"

# ComfyUI 0.29: collect resolved runtime inputs for SaveImagePlus metadata.
try:
    from .execution_metadata import install_execution_metadata_hook
    install_execution_metadata_hook()
except Exception as e:
    print(f"[ImageTools] 生成参数收集器启动失败: {e}")

# 启动性能监控
try:
    from .monitor import setup_monitor
    setup_monitor()
except Exception as e:
    print(f"[ImageTools] 性能监控启动失败: {e}")

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS', 'WEB_DIRECTORY']
