"""
ComfyUI Image Compare - 图片对比节点
使用 ComfyUI 标准的 PreviewImage 机制保存临时图片，通过 /view API 按需加载
"""

from nodes import PreviewImage


class ImageCompare:
    """
    图片对比节点
    接收两组图片，在节点内提供滑块/并排/差异三种对比模式
    使用 PreviewImage 保存临时文件，前端通过 /view URL 按需加载
    """

    _preview = PreviewImage()

    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "images_a": ("IMAGE",),
                "images_b": ("IMAGE",),
                "mode": (["slider", "side_by_side", "difference"], {
                    "default": "slider",
                    "tooltip": "对比模式：slider=滑块对比 | side_by_side=并排对比 | difference=差异对比"
                }),
            },
            "optional": {
                "label_a": ("STRING", {
                    "default": "A",
                    "tooltip": "A 组标签名称"
                }),
                "label_b": ("STRING", {
                    "default": "B",
                    "tooltip": "B 组标签名称"
                }),
            },
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    RETURN_TYPES = ("IMAGE", "IMAGE")
    RETURN_NAMES = ("images_a", "images_b")

    OUTPUT_NODE = True

    FUNCTION = "compare"

    CATEGORY = "image/utils"

    def compare(self, images_a, images_b, mode="slider",
                label_a="A", label_b="B",
                prompt=None, extra_pnginfo=None):
        """
        对比两组图片
        将图片保存为临时文件，返回 URL 元数据给前端按需加载
        """
        # 使用 PreviewImage 保存到 temp/ 目录
        result_a = self._preview.save_images(
            images_a,
            filename_prefix="compare_a",
            prompt=prompt,
            extra_pnginfo=extra_pnginfo,
        )
        result_b = self._preview.save_images(
            images_b,
            filename_prefix="compare_b",
            prompt=prompt,
            extra_pnginfo=extra_pnginfo,
        )

        # 提取 URL 元数据 [{filename, subfolder, type}, ...]
        urls_a = result_a["ui"]["images"]
        urls_b = result_b["ui"]["images"]

        return {
            "ui": {
                "images_a": urls_a,
                "images_b": urls_b,
                "mode": mode,
                "label_a": label_a,
                "label_b": label_b,
            },
            "result": (images_a, images_b),
        }


NODE_CLASS_MAPPINGS = {
    "IS_ImageCompare": ImageCompare,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "IS_ImageCompare": "🔍 Image Compare | 图片对比",
}
