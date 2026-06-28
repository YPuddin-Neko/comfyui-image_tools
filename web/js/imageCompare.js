import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

/**
 * ComfyUI Image Compare - 图片对比节点
 * 参考 ComfyUI-Danbooru-Gallery 的 SimpleImageCompare 实现
 * 使用 addCustomWidget + onMouseEnter/Leave/Move 实现鼠标悬停滑动对比
 */

// 工具函数：节流
function throttle(func, delay) {
    let lastCall = 0;
    return function (...args) {
        const now = Date.now();
        if (now - lastCall >= delay) {
            lastCall = now;
            func.apply(this, args);
        }
    };
}

// 图像数据转 URL
function imageDataToUrl(data) {
    return api.apiURL(
        `/view?filename=${encodeURIComponent(data.filename)}&type=${data.type || "temp"}&subfolder=${data.subfolder || ""}${app.getPreviewFormatParam()}${app.getRandParam()}`
    );
}

// ============================
// ImageCompareWidget 类
// ============================
class ImageCompareWidget {
    constructor(node) {
        this.node = node;
        this.name = "image_compare_widget";
        this.type = "custom";

        // 鼠标状态
        this.isPointerOver = false;
        this.pointerOverPos = [0, 0];

        // 图片
        this.imgObjA = null;
        this.imgObjB = null;

        // 多图导航
        this.urlsA = [];
        this.urlsB = [];
        this.currentIndex = 0;
        this.totalPairs = 0;
        this.imageCache = {};
        this.draggingNav = false; // 导航条拖动状态

        // 布局缓存
        this.cachedDrawData = null;
        this.lastNodeSize = null;
        this.lastDrawY = 0; // 记住 draw 时的 y 起始位置

        // 选择器 hitAreas
        this.hitAreas = {};

        // 导航条布局（缓存给拖动用）
        this.navBarX = 0;
        this.navBarW = 0;

        // 性能优化：节流
        this.throttledMouseMove = throttle(this.handleMouseMove.bind(this), 16);
    }

    // 执行完成后接收数据
    onExecuted(output) {
        const urlsA = output?.images_a || [];
        const urlsB = output?.images_b || [];
        if (!urlsA.length || !urlsB.length) return;

        this.urlsA = urlsA;
        this.urlsB = urlsB;
        this.totalPairs = Math.min(urlsA.length, urlsB.length);
        this.currentIndex = 0;
        this.imageCache = {};
        this.cachedDrawData = null;

        this._loadPair(0);
    }

    // 加载一对图片
    _loadPair(index) {
        if (index < 0 || index >= this.totalPairs) return;

        const cacheKey = `pair_${index}`;
        if (this.imageCache[cacheKey]) {
            this.imgObjA = this.imageCache[cacheKey].a;
            this.imgObjB = this.imageCache[cacheKey].b;
            this.cachedDrawData = null;
            this.node.setDirtyCanvas(true, false);
            return;
        }

        const imgA = new Image();
        const imgB = new Image();
        let loaded = 0;
        const self = this;

        const onLoad = () => {
            loaded++;
            if (loaded === 2) {
                self.imageCache[cacheKey] = { a: imgA, b: imgB };
                if (self.currentIndex === index) {
                    self.imgObjA = imgA;
                    self.imgObjB = imgB;
                    self.cachedDrawData = null;
                    self.node.setDirtyCanvas(true, false);
                }
                // 预加载相邻 & 清理远处
                self._preloadAndClean(index);
            }
        };

        imgA.onload = onLoad;
        imgB.onload = onLoad;
        imgA.onerror = () => console.warn("[IC] Failed A #" + index);
        imgB.onerror = () => console.warn("[IC] Failed B #" + index);
        imgA.src = imageDataToUrl(this.urlsA[index]);
        imgB.src = imageDataToUrl(this.urlsB[index]);
    }

    _preloadAndClean(centerIdx) {
        // 预加载 ±1
        for (const idx of [centerIdx - 1, centerIdx + 1]) {
            if (idx < 0 || idx >= this.totalPairs) continue;
            const key = `pair_${idx}`;
            if (this.imageCache[key]) continue;
            const a = new Image(), b = new Image();
            let cnt = 0;
            const self = this;
            const done = () => { cnt++; if (cnt === 2) self.imageCache[key] = { a, b }; };
            a.onload = done; b.onload = done;
            a.src = imageDataToUrl(this.urlsA[idx]);
            b.src = imageDataToUrl(this.urlsB[idx]);
        }
        // 清理 ±3 以外
        for (const key of Object.keys(this.imageCache)) {
            const idx = parseInt(key.split("_")[1]);
            if (Math.abs(idx - centerIdx) > 3) delete this.imageCache[key];
        }
    }

    _goTo(index) {
        index = Math.max(0, Math.min(this.totalPairs - 1, index));
        if (index === this.currentIndex && this.imgObjA && this.imgObjB) return;
        this.currentIndex = index;
        this.cachedDrawData = null;
        this._loadPair(index);
    }

    // ============================
    // 鼠标事件
    // ============================
    onMouseEnter(event) {
        this.isPointerOver = true;
        this.node.setDirtyCanvas(true, false);
    }

    onMouseLeave(event) {
        this.isPointerOver = false;
        this.node.setDirtyCanvas(true, false);
    }

    handleMouseMove(pos) {
        if (!this.isPointerOver) return;

        // 导航条拖动
        if (this.draggingNav && this.totalPairs > 1 && this.navBounds) {
            const { trackX, trackW } = this.navBounds;
            const ratio = Math.max(0, Math.min(1, (pos[0] - trackX) / trackW));
            this._goTo(Math.round(ratio * (this.totalPairs - 1)));
            return;
        }

        const oldX = this.pointerOverPos[0];
        this.pointerOverPos = [...pos];
        if (Math.abs(oldX - pos[0]) > 1) {
            this.node.setDirtyCanvas(true, false);
        }
    }

    onMouseMove(event, pos, canvas) {
        // 检测鼠标抬起结束拖动
        if (this.draggingNav && event && event.buttons === 0) {
            this.draggingNav = false;
        }
        this.throttledMouseMove(pos);
    }

    onMouseUp(event) {
        this.draggingNav = false;
    }

    // 点击
    mouse(event, pos, node) {
        if (event.type === "pointerdown") {
            for (const part of Object.values(this.hitAreas)) {
                if (this._clickInBounds(pos, part.bounds)) {
                    if (part.onDown) { part.onDown.call(this, pos); return true; }
                }
            }
        }
        return false;
    }

    _clickInBounds(pos, b) {
        return pos[0] >= b[0] && pos[0] <= b[0] + b[2] && pos[1] >= b[1] && pos[1] <= b[1] + b[3];
    }

    // ============================
    // 绘制
    // ============================
    draw(ctx, node, width, y) {
        this.hitAreas = {};
        const [nodeW, nodeH] = node.size;

        // 底部预留：页码(14) + 间距(4) + 滑条(18) + 底部边距(8) = 44
        const navTotal = this.totalPairs > 1 ? 44 : 0;

        // 图片可用高度（不含导航）
        this.imgAreaHeight = nodeH - navTotal;
        this.lastDrawY = y;

        // 先画 A（完整）
        this._drawImg(ctx, this.imgObjA, y);

        // 鼠标悬停时画 B（裁剪到鼠标位置）
        if (this.isPointerOver && this.imgObjB) {
            this._drawImg(ctx, this.imgObjB, y, this.pointerOverPos[0]);
        }

        // 底部导航
        if (this.totalPairs > 1) {
            this._drawNav(ctx, nodeW, this.imgAreaHeight);
        }
    }

    _drawNav(ctx, nodeW, startY) {
        ctx.save();

        // === 第一行：页码 ===
        ctx.fillStyle = "#888";
        ctx.font = "11px system-ui, sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        ctx.fillText(`${this.currentIndex + 1} / ${this.totalPairs}`, nodeW / 2, startY + 2);

        // === 第二行：◀ [滑条] ▶ ===
        const sliderY = startY + 20;
        const sliderH = 18;
        const midY = sliderY + sliderH / 2;

        ctx.textBaseline = "middle";
        const activeColor = "#aaa";
        const inactiveColor = "#555";

        // 三角形箭头（左）
        const arrowSize = 6;
        ctx.fillStyle = this.currentIndex > 0 ? activeColor : inactiveColor;
        ctx.beginPath();
        ctx.moveTo(10, midY);
        ctx.lineTo(10 + arrowSize * 1.2, midY - arrowSize);
        ctx.lineTo(10 + arrowSize * 1.2, midY + arrowSize);
        ctx.closePath();
        ctx.fill();

        // 三角形箭头（右）
        ctx.fillStyle = this.currentIndex < this.totalPairs - 1 ? activeColor : inactiveColor;
        ctx.beginPath();
        ctx.moveTo(nodeW - 10, midY);
        ctx.lineTo(nodeW - 10 - arrowSize * 1.2, midY - arrowSize);
        ctx.lineTo(nodeW - 10 - arrowSize * 1.2, midY + arrowSize);
        ctx.closePath();
        ctx.fill();

        // 滑条轨道
        const trackX = 24;
        const trackW = nodeW - 48;
        const trackH = 4;
        const trackY = midY - trackH / 2;

        // 轨道背景
        ctx.fillStyle = "rgba(255,255,255,0.1)";
        ctx.beginPath();
        ctx.roundRect(trackX, trackY, trackW, trackH, trackH / 2);
        ctx.fill();

        // 已走进度
        const progress = this.totalPairs > 1 ? this.currentIndex / (this.totalPairs - 1) : 0;
        const fillW = trackW * progress;
        if (fillW > 1) {
            const grad = ctx.createLinearGradient(trackX, 0, trackX + fillW, 0);
            grad.addColorStop(0, "rgba(0,180,255,0.3)");
            grad.addColorStop(1, "rgba(0,224,255,0.6)");
            ctx.fillStyle = grad;
            ctx.beginPath();
            ctx.roundRect(trackX, trackY, fillW, trackH, trackH / 2);
            ctx.fill();
        }

        // 手柄光晕
        const handleX = trackX + fillW;
        ctx.beginPath();
        ctx.arc(handleX, midY, 10, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(0,224,255,0.1)";
        ctx.fill();

        // 手柄外圈
        ctx.beginPath();
        ctx.arc(handleX, midY, 6, 0, Math.PI * 2);
        ctx.fillStyle = "#16213e";
        ctx.fill();
        ctx.strokeStyle = "rgba(0,224,255,0.7)";
        ctx.lineWidth = 1.5;
        ctx.stroke();

        // 手柄内圆
        ctx.beginPath();
        ctx.arc(handleX, midY, 3, 0, Math.PI * 2);
        ctx.fillStyle = "#00e0ff";
        ctx.fill();

        // 记住布局
        this.navBounds = {
            arrowY: sliderY, arrowH: sliderH,
            trackX, trackW, nodeW,
            fullY: startY, fullH: 44,
        };

        ctx.restore();
    }

    // 处理导航条点击（由节点 onMouseDown 调用）
    handleNavClick(pos) {
        if (!this.navBounds || this.totalPairs <= 1) return false;
        const { arrowY, arrowH, trackX, trackW, nodeW, fullY, fullH } = this.navBounds;

        // 整个导航区域
        if (pos[1] < fullY || pos[1] > fullY + fullH) return false;

        const inSliderRow = pos[1] >= arrowY && pos[1] <= arrowY + arrowH;

        if (inSliderRow) {
            // 左箭头
            if (pos[0] < 20) {
                this._goTo(this.currentIndex - 1);
                return true;
            }
            // 右箭头
            if (pos[0] > nodeW - 20) {
                this._goTo(this.currentIndex + 1);
                return true;
            }
            // 滑条拖动
            if (pos[0] >= trackX && pos[0] <= trackX + trackW) {
                const ratio = (pos[0] - trackX) / trackW;
                this._goTo(Math.round(ratio * (this.totalPairs - 1)));
                this.draggingNav = true;
                return true;
            }
        }
        return false;
    }

    // 完全复制原版 SimpleImageCompare.drawImage 的逻辑
    _drawImg(ctx, imgObj, y, cropX) {
        if (!imgObj?.naturalWidth || !imgObj?.naturalHeight) return;

        const [nodeWidth] = this.node.size;
        // 用图片区域高度，不侵入导航区
        const effectiveHeight = this.imgAreaHeight || this.node.size[1];

        // 节点大小变化时清除缓存
        const needsRecalc = !this.lastNodeSize ||
            this.lastNodeSize[0] !== nodeWidth ||
            this.lastNodeSize[1] !== effectiveHeight;
        if (needsRecalc) {
            this.lastNodeSize = [nodeWidth, effectiveHeight];
            this.cachedDrawData = null;
        }

        // 缓存图像布局
        if (!this.cachedDrawData) {
            const refImg = this.imgObjA || imgObj;
            const imageAspect = refImg.naturalWidth / refImg.naturalHeight;
            const height = effectiveHeight - y;
            const widgetAspect = nodeWidth / height;

            let targetWidth, targetHeight, offsetX = 0;

            if (imageAspect > widgetAspect) {
                targetWidth = nodeWidth;
                targetHeight = nodeWidth / imageAspect;
            } else {
                targetHeight = height;
                targetWidth = height * imageAspect;
                offsetX = (nodeWidth - targetWidth) / 2;
            }

            this.cachedDrawData = {
                targetWidth,
                targetHeight,
                offsetX,
                widthMultiplier: refImg.naturalWidth / targetWidth,
                destX: (nodeWidth - targetWidth) / 2,
                destY: y + (height - targetHeight) / 2,
            };
        }

        const { targetWidth, targetHeight, offsetX, widthMultiplier, destX, destY } = this.cachedDrawData;

        // 计算裁剪区域（和原版完全一致）
        const sourceX = 0;
        const sourceY = 0;
        const sourceWidth = cropX != null ? (cropX - offsetX) * widthMultiplier : imgObj.naturalWidth;
        const sourceHeight = imgObj.naturalHeight;
        const destWidth = cropX != null ? cropX - offsetX : targetWidth;
        const destHeight = targetHeight;

        ctx.save();
        ctx.beginPath();

        // 和原版一致：cropX truthy 检查（cropX=0 时不 clip）
        if (cropX) {
            ctx.rect(destX, destY, destWidth, destHeight);
            ctx.clip();
        }

        ctx.drawImage(
            imgObj,
            sourceX, sourceY, sourceWidth, sourceHeight,
            destX, destY, destWidth, destHeight
        );

        // 分界线（和原版完全一致：difference 混合模式）
        if (cropX != null && cropX >= (nodeWidth - targetWidth) / 2 && cropX <= targetWidth + offsetX) {
            ctx.beginPath();
            ctx.moveTo(cropX, destY);
            ctx.lineTo(cropX, destY + destHeight);
            ctx.globalCompositeOperation = "difference";
            ctx.strokeStyle = "rgba(255,255,255, 1)";
            ctx.stroke();
        }

        ctx.restore();
    }

    computeSize(width) {
        return [width, 20];
    }

    serializeValue() {
        return {};
    }
}

// ============================
// 注册
// ============================
app.registerExtension({
    name: "comfyui.image_compare",

    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name !== "IS_ImageCompare") return;

        // onNodeCreated
        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;

            this.serialize_widgets = true;
            const widget = new ImageCompareWidget(this);
            this.addCustomWidget(widget);
            this.setSize(this.computeSize());

            return r;
        };

        // onMouseEnter
        const origMouseEnter = nodeType.prototype.onMouseEnter;
        nodeType.prototype.onMouseEnter = function (event) {
            const r = origMouseEnter ? origMouseEnter.apply(this, arguments) : undefined;
            const w = this.widgets?.find(w => w instanceof ImageCompareWidget);
            if (w) w.onMouseEnter(event);
            return r;
        };

        // onMouseLeave
        const origMouseLeave = nodeType.prototype.onMouseLeave;
        nodeType.prototype.onMouseLeave = function (event) {
            const r = origMouseLeave ? origMouseLeave.apply(this, arguments) : undefined;
            const w = this.widgets?.find(w => w instanceof ImageCompareWidget);
            if (w) w.onMouseLeave(event);
            return r;
        };

        // onMouseDown（处理底部导航条点击）
        const origMouseDown = nodeType.prototype.onMouseDown;
        nodeType.prototype.onMouseDown = function (event, pos, canvas) {
            const w = this.widgets?.find(w => w instanceof ImageCompareWidget);
            if (w && w.handleNavClick(pos)) return true;
            return origMouseDown ? origMouseDown.apply(this, arguments) : undefined;
        };

        // onMouseMove
        const origMouseMove = nodeType.prototype.onMouseMove;
        nodeType.prototype.onMouseMove = function (event, pos, canvas) {
            const r = origMouseMove ? origMouseMove.apply(this, arguments) : undefined;
            const w = this.widgets?.find(w => w instanceof ImageCompareWidget);
            if (w) w.onMouseMove(event, pos, canvas);
            return r;
        };

        // onExecuted
        const origExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (output) {
            const r = origExecuted ? origExecuted.apply(this, arguments) : undefined;
            const w = this.widgets?.find(w => w instanceof ImageCompareWidget);
            if (w && output) w.onExecuted(output);
            return r;
        };
    },

    async nodeCreated(node) {
        if (node.comfyClass !== "IS_ImageCompare") return;
        node.color = "#1a1a2e";
        node.bgcolor = "#16213e";
    },
});
