"""
ComfyUI Image Compare - 图片对比节点
使用 PreviewImage 保存临时图片，前端通过 /view API 按需加载
"""

from nodes import PreviewImage


class ImageCompare:
    """
    图片对比节点
    接收两组图片，在节点内提供滑块/并排/差异三种对比模式
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

    def compare(self, images_a, images_b, prompt=None, extra_pnginfo=None):
        """
        保存两组图片到临时目录，返回 URL 元数据给前端
        """
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

        return {
            "ui": {
                "images_a": result_a["ui"]["images"],
                "images_b": result_b["ui"]["images"],
            },
            "result": (images_a, images_b),
        }


NODE_CLASS_MAPPINGS = {
    "IS_ImageCompare": ImageCompare,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "IS_ImageCompare": "Image Compare | 图片对比",
}
