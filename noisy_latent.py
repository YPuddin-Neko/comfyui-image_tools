"""
噪声潜空间合成器 - 噪声潜空间生成节点
对齐 ComfyUI v0.29 核心 prepare_noise 写法
"""

import random
import torch
from nodes import MAX_RESOLUTION

MAX_SEED = 1125899906842624


class NoisyLatentImage:

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "seed": ("INT", {
                    "default": -1,
                    "min": -1,
                    "max": 0xffffffffffffffff,
                }),
                "width": ("INT", {
                    "default": 1024,
                    "min": 64,
                    "max": MAX_RESOLUTION,
                    "step": 8,
                }),
                "height": ("INT", {
                    "default": 1024,
                    "min": 64,
                    "max": MAX_RESOLUTION,
                    "step": 8,
                }),
                "batch_size": ("INT", {
                    "default": 1,
                    "min": 1,
                    "max": 64,
                }),
            },
        }

    RETURN_TYPES = ("LATENT", "INT")
    RETURN_NAMES = ("LATENT", "SEED")
    OUTPUT_NODE = True
    FUNCTION = "create_noisy_latent"
    CATEGORY = "latent/noise"

    @classmethod
    def IS_CHANGED(cls, seed=-1, **kwargs):
        if seed < 0:
            return float("nan")
        return seed

    def create_noisy_latent(self, seed, width, height, batch_size):
        if seed < 0:
            seed = random.randint(0, MAX_SEED)

        # 和 ComfyUI 内置 EmptyLatentImage 一样输出全零 latent
        # KSampler 的 fix_empty_latent_channels 会自动匹配模型通道数
        latent = torch.zeros(
            [batch_size, 4, height // 8, width // 8],
            dtype=torch.float32,
        )

        return {"ui": {"SEED": [seed]}, "result": ({"samples": latent}, seed)}


NODE_CLASS_MAPPINGS = {
    "IS_NoisyLatentImage": NoisyLatentImage,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "IS_NoisyLatentImage": "潜空间生成器",
}
