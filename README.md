# 🛠️ ComfyUI Image Tools | 图片工具箱

一个 ComfyUI 自定义节点插件(代码均为AI生成)，包含图片选择器、图片对比、潜空间生成器和增强版图片保存等实用工具。

## 🖼️ 例图

<img width="2560" height="1316" alt="image" src="https://github.com/user-attachments/assets/1f4ce2ed-0c81-4384-bbcf-cdf80d028100" />


## ✨ 功能特点

### Image Selector | 图片选择器

- **始终弹窗** - 无论输入是单张还是多张图片，都会弹出选择窗口
- **大图预览** - 图片以大尺寸完整展示；点击 🔍 按钮或双击可查看原尺寸大图
- **卡片大小可调** - 工具栏提供滑块，可自由拖动调整图片卡片大小（150px~600px）
- **多选操作** - 支持全选、取消全选、反选快捷操作
- **提示音通知** - 弹窗时播放提示音，支持开关和音量调节
- **自定义提示音** - 提示音文件硬编码为 `sound/din.wav`，可替换为自己的音频
- **超时可配置** - 支持在节点上手动设置选择超时时间（10~3600秒）
- **安全中断** - 取消选择或不选择任何图片时，工作流会自动中断，不会继续执行
- **页面切换恢复** - 切换到其他工作流再切回来，待处理的选择弹窗会自动恢复
- **多用户隔离** - 多用户/多标签页场景下弹窗只在对应工作流页面显示
- **优雅动画** - 流畅的弹窗动画和交互效果

### Image Compare | 图片对比

- **多图导航** - 支持多对图片对比：底部页码显示 + 滑条拖动 + 左右箭头切换

### Save Image Plus | 保存图像增强版

> 📌 此节点的图片保存功能移植自 [ComfyUI-Danbooru-Gallery](https://github.com/Aaalice233/ComfyUI-Danbooru-Gallery) 的 SaveImagePlus 节点，在此基础上进行了独立实现和改进（移除外部依赖、增强种子读取兼容性、修复子工作流保存等）。感谢原作者的工作！

- **多格式保存** - 支持 PNG / JPEG / WEBP 三种格式
- **A1111 元数据** - 自动生成 A1111 格式的元数据（提示词、生成参数、模型信息等）
- **LoRA/Checkpoint 哈希** - 自动计算模型 SHA256 哈希，多 LoRA 并行计算
- **文件名占位符** - 支持 `%date:yyyyMMdd%`、`%seed%`、`%model%` 动态文件名
- **工作流嵌入** - PNG 格式可嵌入完整 ComfyUI 工作流数据
- **纯净副本** - 可额外保存无元数据的纯净图片副本
- **元数据智能收集** - 四级降级策略：手动传入 → 直接输入 → 自动解析节点 → 提取文本
- **子工作流兼容** - 在 Group Node（子工作流）中也能正常保存图片
- **广泛的种子读取** - 支持标准 KSampler、Easy-use、Efficiency、Impact 等多种采样器节点的种子提取

### 潜空间生成器

> 📌 种子控制 UI 参考自 [rgthree-comfy](https://github.com/rgthree/rgthree-comfy)。

- **全模型兼容** - 输出全零 latent，KSampler 自动匹配模型通道数（SD/SDXL/FLUX/SD3 通用）
- **种子控制** - Canvas 绘制三按钮：🎲 每次随机 / 🎲 新固定随机 / ♻️ 使用上次种子
- **种子回收** - 执行后「使用上次种子」按钮自动亮起并显示实际种子值
- **单独 SEED 输出** - SEED 作为独立 INT 输出端，方便接线到其他节点
- **零延迟交互** - 按钮使用 Canvas 绘制 + onMouseDown 直接处理，无 DOM 延迟

## 📦 安装

将此文件夹复制到 ComfyUI 的 `custom_nodes` 目录下：

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/YPuddin-Neko/comfyui-image_tools
```

重启 ComfyUI 即可使用。

## 🚀 使用方法

### 图片选择器

1. 在 ComfyUI 中，右键画布 → 添加节点 → `image/utils` → `Image Selector | 图片选择器`
2. 将图片输出连接到该节点的 `images` 输入端
3. 可选：调整提示音开关、音量和超时时间
4. 运行工作流，弹出图片选择窗口
5. 选择需要的图片后点击「✓ 确认选择」
6. 选中的图片会通过 `images` 输出端传递给下游节点

> ⚠️ **注意**：点击「✕ 取消」或不选择任何图片将**中断工作流**，不会继续执行。

### 图片对比

1. 右键画布 → 添加节点 → `image/utils` → `Image Compare | 图片对比`
2. 将两组图片分别连接到 `images_a` 和 `images_b` 输入端
3. 运行工作流，节点内直接显示对比图
4. 将鼠标移入节点区域，分界线跟随鼠标移动，左侧显示 B 图、右侧显示 A 图
5. 多张图片时，使用底部滑条或左右箭头切换不同对比

### 保存图像增强版

1. 右键画布 → 添加节点 → `image/utils` → `Save Image Plus | 保存图像增强版`
2. 将图片连接到 `images` 输入端（可搭配图片选择器使用）
3. 可选：连接 `positive_prompt`、`negative_prompt`、`lora_syntax`、`checkpoint_name` 输入
4. 设置文件名前缀（支持占位符）、保存格式和质量
5. 运行工作流，图片自动保存到 ComfyUI 输出目录

### 潜空间生成器

1. 右键画布 → 添加节点 → `latent/noise` → `潜空间生成器`
2. 设置宽度、高度和批量大小
3. 点击底部按钮选择种子模式（🎲 每次随机 / 🎲 新固定随机 / ♻️ 使用上次种子）
4. 连接 LATENT 输出到 KSampler，SEED 输出可接到其他节点
5. 兼容所有模型（SD/SDXL/FLUX/SD3），无需手动选择通道数

## 📸 节点参数

### Image Selector

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| images | IMAGE | - | 输入的图片（支持单张或批量） |
| sound_enabled | BOOLEAN | True | 是否开启弹窗提示音 |
| sound_volume | FLOAT | 0.5 | 提示音音量（0.0 ~ 1.0） |
| timeout | INT | 300 | 图片选择超时时间（秒），范围 10 ~ 3600 |

**输出端**：`images`（IMAGE 类型）- 用户选中的图片

### Image Compare

| 参数 | 类型 | 说明 |
|------|------|------|
| images_a | IMAGE | 第一组图片（A 组） |
| images_b | IMAGE | 第二组图片（B 组） |

**输出端**：`images_a`（IMAGE）、`images_b`（IMAGE）- 直通输出原始图片

### 潜空间生成器

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| seed | INT | 0 | 种子值（-1 = 每次随机） |
| width | INT | 1024 | 宽度（步长 8） |
| height | INT | 1024 | 高度（步长 8） |
| batch_size | INT | 1 | 批量大小 |

**输出端**：`LATENT`（全零潜空间，KSampler 自动匹配通道）、`SEED`（INT）- 实际使用的种子值

### Save Image Plus

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| images | IMAGE | - | 要保存的图片 |
| enable | BOOLEAN | True | 是否启用保存 |
| filename_prefix | STRING | "ComfyUI" | 文件名前缀，支持 `%date%` `%seed%` `%model%` 占位符 |
| file_format | COMBO | "PNG" | 保存格式：PNG / JPEG / WEBP |
| quality | INT | 100 | JPEG/WEBP 质量（1-100） |
| embed_workflow | BOOLEAN | True | 是否嵌入工作流数据（仅 PNG） |
| save_clean_copy | BOOLEAN | False | 额外保存无元数据的纯净副本 |
| enable_preview | BOOLEAN | False | 是否在界面显示预览 |
| positive_prompt | STRING | - | 正面提示词（可选，连线输入） |
| negative_prompt | STRING | - | 负面提示词（可选，连线输入） |
| lora_syntax | STRING | - | LoRA 语法字符串（可选，连线输入） |
| checkpoint_name | STRING | - | 手动指定 Checkpoint 名称（最高优先级） |

#### 文件名占位符

| 占位符 | 说明 | 示例 |
|--------|------|------|
| `%date%` | 日期时间（默认 yyyyMMddhhmmss） | 20250520204500 |
| `%date:yyyyMMdd%` | 自定义日期格式 | 20250520 |
| `%seed%` | 生成 Seed 值 | 1234567890 |
| `%model%` | Checkpoint 模型名称 | animagine-xl |

## 🎛️ 弹窗操作说明

| 操作 | 说明 |
|------|------|
| 点击图片卡片 | 选中/取消选中该图片 |
| 点击 🔍 按钮 | 查看原尺寸大图 |
| 双击图片 | 查看原尺寸大图 |
| 拖动 🔲 滑块 | 调整图片卡片显示大小 |
| 全选 / 取消全选 / 反选 | 工具栏快捷批量操作 |
| ESC 键 | 关闭大图预览 |
| ✓ 确认选择 | 提交选中图片，继续工作流 |
| ✕ 取消 | 中断工作流 |

## 🔊 自定义提示音

提示音文件位于 `sound/din.wav`，你可以替换为自己喜欢的音频文件（保持 WAV 格式和相同文件名）。

## 📁 文件结构

```
comfyui-image_tools/
├── __init__.py              # 插件入口
├── nodes.py                 # 图片选择器节点 & 后端逻辑
├── image_compare.py         # 图片对比节点
├── noisy_latent.py          # 潜空间生成器节点
├── save_image_plus.py       # 保存图像增强版节点
├── web/
│   └── js/
│       ├── imageSelector.js # 图片选择器前端 UI
│       ├── imageCompare.js  # 图片对比前端 UI
│       └── noisyLatent.js   # 潜空间生成器种子控制 UI
├── sound/
│   └── din.wav              # 提示音文件
├── pyproject.toml           # 项目配置
└── README.md                # 说明文档
```

## 📝 License

MIT
