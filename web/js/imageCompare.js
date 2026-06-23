import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

/**
 * ComfyUI Image Compare - 节点内嵌图片对比组件
 * 支持滑块对比、并排对比、差异对比三种模式
 * 使用 /view API 按需加载图片，避免 base64 性能问题
 */

// ============================
// 工具函数
// ============================
function getViewUrl(urlObj) {
    return api.apiURL(
        `/view?filename=${encodeURIComponent(urlObj.filename)}&type=${urlObj.type || "temp"}&subfolder=${urlObj.subfolder || ""}&r=${Math.random()}`
    );
}

function loadImage(src) {
    return new Promise((resolve, reject) => {
        const img = new Image();
        img.crossOrigin = "anonymous";
        img.onload = () => resolve(img);
        img.onerror = reject;
        img.src = src;
    });
}

// ============================
// ImageCompareWidget 类
// ============================
class ImageCompareWidget {
    constructor(node) {
        this.node = node;
        this.urlsA = [];
        this.urlsB = [];
        this.mode = "slider";
        this.labelA = "A";
        this.labelB = "B";
        this.currentIndex = 0;
        this.totalPairs = 0;
        this.sliderPos = 0.5;
        this.isDragging = false;

        // 图片缓存（滑动窗口，只缓存 ±2）
        this.imageCache = {};
        this.CACHE_WINDOW = 2;

        // 当前加载的图片
        this.imgA = null;
        this.imgB = null;
        this.loading = false;

        // 创建 DOM
        this.element = document.createElement("div");
        this.element.style.cssText = "width:100%;display:flex;flex-direction:column;background:#111;border-radius:6px;overflow:hidden;";

        // 对比画布
        this.canvas = document.createElement("canvas");
        this.canvas.style.cssText = "width:100%;cursor:col-resize;display:block;background:#0a0a0a;";
        this.element.appendChild(this.canvas);

        // 导航栏
        this.navBar = document.createElement("div");
        this.navBar.style.cssText = "display:flex;align-items:center;gap:6px;padding:6px 8px;background:#1a1a2e;";
        this._buildNav();
        this.element.appendChild(this.navBar);

        // 缩略图条
        this.thumbStrip = document.createElement("div");
        this.thumbStrip.style.cssText = "display:flex;gap:3px;padding:4px 8px 6px;background:#1a1a2e;overflow-x:auto;scrollbar-width:thin;scrollbar-color:#3a3a5c #1a1a2e;border-top:1px solid #2a2a40;";
        this.element.appendChild(this.thumbStrip);

        // 绑定画布交互
        this._bindCanvasEvents();
    }

    _buildNav() {
        const n = this.navBar;
        n.innerHTML = "";

        // 左箭头
        const btnPrev = this._createBtn("◀", () => this.goTo(this.currentIndex - 1));
        n.appendChild(btnPrev);

        // 滑条
        this.navSlider = document.createElement("input");
        this.navSlider.type = "range";
        this.navSlider.min = "1";
        this.navSlider.max = "1";
        this.navSlider.value = "1";
        this.navSlider.style.cssText = "flex:1;height:4px;-webkit-appearance:none;appearance:none;background:#2a2a4a;border-radius:2px;outline:none;cursor:pointer;";
        this.navSlider.addEventListener("input", () => {
            this.goTo(parseInt(this.navSlider.value) - 1);
        });
        n.appendChild(this.navSlider);

        // 右箭头
        const btnNext = this._createBtn("▶", () => this.goTo(this.currentIndex + 1));
        n.appendChild(btnNext);

        // 数字输入
        this.navInput = document.createElement("input");
        this.navInput.type = "number";
        this.navInput.min = "1";
        this.navInput.value = "1";
        this.navInput.style.cssText = "width:36px;padding:2px 4px;border-radius:4px;border:1px solid #3a3a5c;background:#0e0e1a;color:#e0e0e0;font-size:11px;text-align:center;outline:none;";
        this.navInput.addEventListener("change", () => {
            this.goTo(parseInt(this.navInput.value) - 1);
        });
        this.navInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter") {
                this.goTo(parseInt(this.navInput.value) - 1);
                this.navInput.blur();
            }
            e.stopPropagation();
        });
        // 阻止 ComfyUI 拦截 input 事件
        this.navInput.addEventListener("keyup", (e) => e.stopPropagation());
        this.navInput.addEventListener("keypress", (e) => e.stopPropagation());
        n.appendChild(this.navInput);

        // 总数
        this.navTotal = document.createElement("span");
        this.navTotal.style.cssText = "font-size:11px;color:#666;white-space:nowrap;";
        this.navTotal.textContent = "/ 0";
        n.appendChild(this.navTotal);
    }

    _createBtn(text, onClick) {
        const btn = document.createElement("button");
        btn.textContent = text;
        btn.style.cssText = "width:22px;height:22px;border-radius:4px;border:1px solid #3a3a5c;background:transparent;color:#ccc;font-size:11px;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:all 0.15s;padding:0;";
        btn.addEventListener("mouseenter", () => {
            btn.style.background = "rgba(83,92,236,0.2)";
            btn.style.borderColor = "#535cec";
        });
        btn.addEventListener("mouseleave", () => {
            btn.style.background = "transparent";
            btn.style.borderColor = "#3a3a5c";
        });
        btn.addEventListener("click", onClick);
        return btn;
    }

    _bindCanvasEvents() {
        this.canvas.addEventListener("mousedown", (e) => {
            if (this.mode !== "slider") return;
            this.isDragging = true;
            this._updateSliderFromMouse(e);
        });

        // 全局 mousemove/mouseup 确保拖出画布仍生效
        document.addEventListener("mousemove", (e) => {
            if (!this.isDragging) return;
            this._updateSliderFromMouse(e);
        });

        document.addEventListener("mouseup", () => {
            this.isDragging = false;
        });
    }

    _updateSliderFromMouse(e) {
        const rect = this.canvas.getBoundingClientRect();
        this.sliderPos = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
        this.draw();
    }

    // ============================
    // 数据更新
    // ============================
    setData(urlsA, urlsB, mode, labelA, labelB) {
        this.urlsA = urlsA || [];
        this.urlsB = urlsB || [];
        this.mode = mode || "slider";
        this.labelA = labelA || "A";
        this.labelB = labelB || "B";
        this.totalPairs = Math.min(this.urlsA.length, this.urlsB.length);
        this.currentIndex = 0;
        this.sliderPos = 0.5;

        // 清空缓存
        this.imageCache = {};

        // 更新导航
        this.navSlider.max = String(Math.max(1, this.totalPairs));
        this.navSlider.value = "1";
        this.navInput.max = String(this.totalPairs);
        this.navInput.value = "1";
        this.navTotal.textContent = `/ ${this.totalPairs}`;

        // 更新画布模式光标
        this.canvas.style.cursor = this.mode === "slider" ? "col-resize" : "default";

        // 构建缩略图
        this._buildThumbs();

        // 加载第一对
        this._loadPair(0);
    }

    // ============================
    // 图片加载（带缓存窗口）
    // ============================
    async _loadPair(index) {
        if (index < 0 || index >= this.totalPairs) return;

        this.loading = true;
        this.draw(); // 显示 loading 状态

        const keyA = `a_${index}`;
        const keyB = `b_${index}`;

        try {
            // 并行加载 A 和 B
            const [imgA, imgB] = await Promise.all([
                this.imageCache[keyA]
                    ? Promise.resolve(this.imageCache[keyA])
                    : loadImage(getViewUrl(this.urlsA[index])),
                this.imageCache[keyB]
                    ? Promise.resolve(this.imageCache[keyB])
                    : loadImage(getViewUrl(this.urlsB[index])),
            ]);

            // 存入缓存
            this.imageCache[keyA] = imgA;
            this.imageCache[keyB] = imgB;

            // 当前对
            if (this.currentIndex === index) {
                this.imgA = imgA;
                this.imgB = imgB;
                this.loading = false;
                this.draw();
            }
        } catch (err) {
            console.warn(`[Image Compare] 加载图片失败 #${index}:`, err);
            this.loading = false;
            this.draw();
        }

        // 预加载相邻图片 & 清理远处缓存
        this._manageCache(index);
    }

    async _manageCache(centerIndex) {
        // 预加载 ±CACHE_WINDOW 范围的图片
        for (let offset = 1; offset <= this.CACHE_WINDOW; offset++) {
            for (const idx of [centerIndex + offset, centerIndex - offset]) {
                if (idx < 0 || idx >= this.totalPairs) continue;
                const kA = `a_${idx}`, kB = `b_${idx}`;
                if (!this.imageCache[kA]) {
                    try {
                        this.imageCache[kA] = await loadImage(getViewUrl(this.urlsA[idx]));
                    } catch (e) { /* ignore */ }
                }
                if (!this.imageCache[kB]) {
                    try {
                        this.imageCache[kB] = await loadImage(getViewUrl(this.urlsB[idx]));
                    } catch (e) { /* ignore */ }
                }
            }
        }

        // 清理远处缓存
        const keys = Object.keys(this.imageCache);
        for (const key of keys) {
            const parts = key.split("_");
            const idx = parseInt(parts[1]);
            if (Math.abs(idx - centerIndex) > this.CACHE_WINDOW + 1) {
                delete this.imageCache[key];
            }
        }
    }

    // ============================
    // 导航
    // ============================
    goTo(index) {
        index = Math.max(0, Math.min(this.totalPairs - 1, index));
        if (index === this.currentIndex && this.imgA && this.imgB) return;

        this.currentIndex = index;
        this.navSlider.value = String(index + 1);
        this.navInput.value = String(index + 1);

        // 更新缩略图高亮
        this.thumbStrip.querySelectorAll(".ic-thumb").forEach((el, i) => {
            el.style.borderColor = i === index ? "#535cec" : "transparent";
            el.style.opacity = i === index ? "1" : "0.5";
        });
        // 滚动到可见
        const activeThumb = this.thumbStrip.children[index];
        if (activeThumb) {
            activeThumb.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
        }

        this._loadPair(index);
    }

    // ============================
    // 缩略图条
    // ============================
    _buildThumbs() {
        this.thumbStrip.innerHTML = "";

        if (this.totalPairs <= 1) {
            this.thumbStrip.style.display = "none";
            return;
        }
        this.thumbStrip.style.display = "flex";

        for (let i = 0; i < this.totalPairs; i++) {
            const thumb = document.createElement("img");
            thumb.className = "ic-thumb";
            thumb.src = getViewUrl(this.urlsA[i]);
            thumb.style.cssText = `width:32px;height:32px;border-radius:3px;border:2px solid ${i === 0 ? "#535cec" : "transparent"};object-fit:cover;cursor:pointer;flex-shrink:0;opacity:${i === 0 ? "1" : "0.5"};transition:all 0.15s;`;
            thumb.addEventListener("click", () => this.goTo(i));
            thumb.addEventListener("mouseenter", () => {
                if (i !== this.currentIndex) thumb.style.opacity = "0.8";
            });
            thumb.addEventListener("mouseleave", () => {
                if (i !== this.currentIndex) thumb.style.opacity = "0.5";
            });
            // 缩略图加载失败时用占位
            thumb.onerror = () => {
                thumb.style.background = "#2a2a4a";
                thumb.alt = String(i + 1);
            };
            this.thumbStrip.appendChild(thumb);
        }
    }

    // ============================
    // 绘制
    // ============================
    draw() {
        const canvas = this.canvas;
        const containerWidth = canvas.parentElement?.offsetWidth || 400;
        const displayHeight = Math.round(containerWidth * 0.625); // 16:10 比例

        // 设置 canvas 实际像素（用于清晰绘制）
        const dpr = window.devicePixelRatio || 1;
        canvas.width = containerWidth * dpr;
        canvas.height = displayHeight * dpr;
        canvas.style.height = displayHeight + "px";

        const ctx = canvas.getContext("2d");
        ctx.scale(dpr, dpr);
        const w = containerWidth;
        const h = displayHeight;

        // 清空
        ctx.fillStyle = "#0a0a0a";
        ctx.fillRect(0, 0, w, h);

        if (this.loading || !this.imgA || !this.imgB) {
            // Loading 状态
            ctx.fillStyle = "#555";
            ctx.font = "14px system-ui, sans-serif";
            ctx.textAlign = "center";
            ctx.fillText(this.loading ? "加载中..." : "等待执行...", w / 2, h / 2);
            return;
        }

        if (this.mode === "slider") {
            this._drawSlider(ctx, w, h);
        } else if (this.mode === "side_by_side") {
            this._drawSideBySide(ctx, w, h);
        } else {
            this._drawDifference(ctx, w, h);
        }
    }

    _drawSlider(ctx, w, h) {
        const splitX = Math.round(w * this.sliderPos);

        // 计算图片绘制区域（保持比例 contain）
        const drawA = this._fitImage(this.imgA, w, h);
        const drawB = this._fitImage(this.imgB, w, h);

        // 先画 B（完整）
        ctx.drawImage(this.imgB, drawB.x, drawB.y, drawB.w, drawB.h);

        // 再画 A（左半裁剪）
        ctx.save();
        ctx.beginPath();
        ctx.rect(0, 0, splitX, h);
        ctx.clip();
        ctx.drawImage(this.imgA, drawA.x, drawA.y, drawA.w, drawA.h);
        ctx.restore();

        // 分割线
        ctx.strokeStyle = "#fff";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(splitX, 0);
        ctx.lineTo(splitX, h);
        ctx.stroke();

        // 滑块手柄
        ctx.beginPath();
        ctx.arc(splitX, h / 2, 14, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(255,255,255,0.9)";
        ctx.fill();
        ctx.strokeStyle = "#535cec";
        ctx.lineWidth = 2;
        ctx.stroke();
        ctx.fillStyle = "#535cec";
        ctx.font = "bold 12px sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText("⇔", splitX, h / 2);

        // 标签
        this._drawLabels(ctx, w);
    }

    _drawSideBySide(ctx, w, h) {
        const halfW = Math.floor(w / 2) - 1;

        // A 在左
        const dA = this._fitImage(this.imgA, halfW, h);
        ctx.drawImage(this.imgA, dA.x, dA.y, dA.w, dA.h);

        // 分隔线
        ctx.fillStyle = "#3a3a5c";
        ctx.fillRect(halfW, 0, 2, h);

        // B 在右
        ctx.save();
        ctx.translate(halfW + 2, 0);
        const dB = this._fitImage(this.imgB, halfW, h);
        ctx.drawImage(this.imgB, dB.x, dB.y, dB.w, dB.h);
        ctx.restore();

        // 标签
        this._drawLabel(ctx, this.labelA, 8, "#535cec");
        this._drawLabel(ctx, this.labelB, halfW + 10, "#4caf50");
    }

    _drawDifference(ctx, w, h) {
        // 先画 A
        const dA = this._fitImage(this.imgA, w, h);
        ctx.drawImage(this.imgA, dA.x, dA.y, dA.w, dA.h);

        // 获取 A 的像素
        const dataA = ctx.getImageData(0, 0, w * (window.devicePixelRatio || 1), h * (window.devicePixelRatio || 1));

        // 画 B
        ctx.drawImage(this.imgB, dA.x, dA.y, dA.w, dA.h);
        const dataB = ctx.getImageData(0, 0, w * (window.devicePixelRatio || 1), h * (window.devicePixelRatio || 1));

        // 计算差异
        const pixels = dataA.data;
        const pixelsB = dataB.data;
        for (let i = 0; i < pixels.length; i += 4) {
            const dr = Math.abs(pixels[i] - pixelsB[i]);
            const dg = Math.abs(pixels[i + 1] - pixelsB[i + 1]);
            const db = Math.abs(pixels[i + 2] - pixelsB[i + 2]);
            const diff = Math.min(255, (dr + dg + db) * 2);
            pixels[i] = diff;
            pixels[i + 1] = diff > 80 ? 255 : diff * 2;
            pixels[i + 2] = 30;
            pixels[i + 3] = 255;
        }
        ctx.putImageData(dataA, 0, 0);

        // DIFF 标签
        this._drawLabel(ctx, "DIFF", 8, "#ff9800");
    }

    _fitImage(img, containerW, containerH) {
        const imgRatio = img.naturalWidth / img.naturalHeight;
        const containerRatio = containerW / containerH;
        let w, h, x, y;
        if (imgRatio > containerRatio) {
            w = containerW;
            h = containerW / imgRatio;
            x = 0;
            y = (containerH - h) / 2;
        } else {
            h = containerH;
            w = containerH * imgRatio;
            x = (containerW - w) / 2;
            y = 0;
        }
        return { x, y, w, h };
    }

    _drawLabels(ctx, w) {
        this._drawLabel(ctx, this.labelA, 8, "#535cec");
        this._drawLabel(ctx, this.labelB, w - 8, "#4caf50", true);
    }

    _drawLabel(ctx, text, x, bgColor, alignRight = false) {
        ctx.font = "bold 11px system-ui, sans-serif";
        const metrics = ctx.measureText(text);
        const padX = 8, padY = 4;
        const textW = metrics.width;
        const drawX = alignRight ? x - textW - padX * 2 : x;

        ctx.fillStyle = bgColor;
        ctx.globalAlpha = 0.85;
        ctx.beginPath();
        ctx.roundRect(drawX, 6, textW + padX * 2, 20, 4);
        ctx.fill();
        ctx.globalAlpha = 1;

        ctx.fillStyle = "#fff";
        ctx.textAlign = "left";
        ctx.textBaseline = "middle";
        ctx.fillText(text, drawX + padX, 16);
    }

    // ============================
    // 尺寸计算（给 ComfyUI widget 系统用）
    // ============================
    computeSize() {
        const w = this.node.size[0];
        // 画布高度 + 导航栏 + 缩略图条
        const canvasH = Math.round(w * 0.625);
        const navH = 34;
        const thumbH = this.totalPairs > 1 ? 42 : 0;
        return [w, canvasH + navH + thumbH + 8];
    }
}

// ============================
// 注册 ComfyUI 扩展
// ============================
app.registerExtension({
    name: "comfyui.image_compare",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "IS_ImageCompare") return;

        // 在节点执行完成后接收图片 URL 并渲染对比
        const origOnExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            origOnExecuted?.apply(this, arguments);

            const urlsA = message.images_a;
            const urlsB = message.images_b;
            const mode = message.mode || "slider";
            const labelA = message.label_a || "A";
            const labelB = message.label_b || "B";

            if (!urlsA || !urlsB || urlsA.length === 0 || urlsB.length === 0) return;

            // 初始化或获取已有的 widget
            if (!this._compareWidget) {
                const widget = new ImageCompareWidget(this);
                // 添加为 ComfyUI DOM widget
                this._compareWidget = this.addDOMWidget(
                    "compare_view",
                    "custom",
                    widget.element,
                    {
                        serialize: false,
                        getMinHeight: () => {
                            return widget.computeSize()[1];
                        },
                    }
                );
                this._compareWidget._widget = widget;

                // 监听节点大小变化重绘
                const origOnResize = this.onResize;
                this.onResize = function () {
                    origOnResize?.apply(this, arguments);
                    widget.draw();
                };
            }

            // 更新数据
            this._compareWidget._widget.setData(urlsA, urlsB, mode, labelA, labelB);
        };
    },

    async nodeCreated(node) {
        if (node.comfyClass === "IS_ImageCompare") {
            node.color = "#1a1a2e";
            node.bgcolor = "#16213e";
            // 设置初始大小
            node.size = [400, 340];
        }
    },
});
