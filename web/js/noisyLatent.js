import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

/**
 * 噪声潜空间合成器 - 前端扩展
 * Canvas 绘制按钮 + clip 裁剪 + 最小高度锁定
 */

const MAX_SEED = 1125899906842624;

const LABEL_MAP = {
    seed: "种子",
    width: "宽度",
    height: "高度",
    batch_size: "批量大小",
};

const BUTTONS = [
    { id: "randomize", label: "🎲 每次随机" },
    { id: "fixed_random", label: "🎲 新固定随机" },
    { id: "last_seed", label: "♻️ 使用上次种子", disabledByDefault: true },
];

const BTN_HEIGHT = 26;
const BTN_GAP = 4;
const BTN_PAD_X = 10;
const BTN_PAD_Y = 8;

app.registerExtension({
    name: "comfyui.noisy_latent",

    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name !== "IS_NoisyLatentImage") return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
            const node = this;

            // 汉化 widget 标签
            for (const w of node.widgets || []) {
                if (LABEL_MAP[w.name]) w.label = LABEL_MAP[w.name];
            }

            // 删除 control_after_generate
            setTimeout(() => {
                const idx = node.widgets?.findIndex(w => w.name === "control_after_generate");
                if (idx >= 0) node.widgets.splice(idx, 1);
                // 计算并锁定最小高度
                node._btnAreaH = BUTTONS.length * (BTN_HEIGHT + BTN_GAP) + BTN_PAD_Y * 2;
                const baseSize = node.computeSize();
                node._minH = baseSize[1] + node._btnAreaH;
                node.setSize([Math.max(node.size[0], 220), node._minH]);
                node.setDirtyCanvas(true, true);
            }, 0);

            // 状态
            node._lastQueuedSeed = null;
            node._hoverBtn = -1;
            node._btnLabels = BUTTONS.map(b => b.label);
            node._btnAreaH = BUTTONS.length * (BTN_HEIGHT + BTN_GAP) + BTN_PAD_Y * 2;

            // === 强制最小高度：阻止缩小到按钮区域外 ===
            const origResize = node.onResize;
            node.onResize = function (size) {
                if (node._minH && size[1] < node._minH) {
                    size[1] = node._minH;
                }
                if (origResize) origResize.call(this, size);
            };

            // === Canvas 绘制按钮（带 clip 裁剪） ===
            const origDraw = node.onDrawForeground;
            node.onDrawForeground = function (ctx) {
                if (origDraw) origDraw.call(this, ctx);
                if (this.flags.collapsed) return;

                const w = this.size[0];
                const h = this.size[1];

                // clip 到节点区域，防止任何溢出
                ctx.save();
                ctx.beginPath();
                ctx.rect(0, 0, w, h);
                ctx.clip();

                // 按钮从底部往上排列
                const totalBtnH = BUTTONS.length * (BTN_HEIGHT + BTN_GAP) - BTN_GAP;
                const startY = h - BTN_PAD_Y - totalBtnH;

                for (let i = 0; i < BUTTONS.length; i++) {
                    const btn = BUTTONS[i];
                    const y = startY + i * (BTN_HEIGHT + BTN_GAP);
                    const x = BTN_PAD_X;
                    const bw = w - BTN_PAD_X * 2;
                    const isDisabled = btn.disabledByDefault && this._lastQueuedSeed == null;
                    const isHover = this._hoverBtn === i && !isDisabled;

                    // 背景
                    ctx.fillStyle = isDisabled ? "#333" : isHover ? "#4e5e70" : "#3c4858";
                    ctx.beginPath();
                    ctx.roundRect(x, y, bw, BTN_HEIGHT, 4);
                    ctx.fill();

                    // 边框
                    ctx.strokeStyle = isDisabled ? "#444" : "#5a6a7a";
                    ctx.lineWidth = 1;
                    ctx.stroke();

                    // 文字
                    ctx.fillStyle = isDisabled ? "#555" : "#ddd";
                    ctx.font = "12px Arial, sans-serif";
                    ctx.textAlign = "center";
                    ctx.textBaseline = "middle";
                    ctx.fillText(this._btnLabels[i], w / 2, y + BTN_HEIGHT / 2);
                }

                ctx.restore();
            };

            // === 点击处理 ===
            const origMouseDown = node.onMouseDown;
            node.onMouseDown = function (e, pos, canvas) {
                const btnIdx = this._getBtnAtPos(pos);
                if (btnIdx >= 0) {
                    const seedWidget = this.widgets?.find(w => w.name === "seed");
                    if (!seedWidget) return true;
                    const btn = BUTTONS[btnIdx];

                    if (btn.id === "randomize") {
                        seedWidget.value = -1;
                    } else if (btn.id === "fixed_random") {
                        seedWidget.value = Math.floor(Math.random() * MAX_SEED);
                    } else if (btn.id === "last_seed" && this._lastQueuedSeed != null) {
                        seedWidget.value = this._lastQueuedSeed;
                    }
                    this.setDirtyCanvas(true, true);
                    return true;
                }
                if (origMouseDown) return origMouseDown.call(this, e, pos, canvas);
                return false;
            };

            // 悬停
            const origMouseMove = node.onMouseMove;
            node.onMouseMove = function (e, pos, canvas) {
                const btnIdx = this._getBtnAtPos(pos);
                if (this._hoverBtn !== btnIdx) {
                    this._hoverBtn = btnIdx;
                    this.setDirtyCanvas(true, false);
                }
                if (origMouseMove) return origMouseMove.call(this, e, pos, canvas);
            };

            // 鼠标离开
            const origMouseLeave = node.onMouseLeave;
            node.onMouseLeave = function (e) {
                if (this._hoverBtn !== -1) {
                    this._hoverBtn = -1;
                    this.setDirtyCanvas(true, false);
                }
                if (origMouseLeave) return origMouseLeave.call(this, e);
            };

            // 按钮碰撞检测
            node._getBtnAtPos = function (pos) {
                const w = this.size[0];
                const h = this.size[1];
                const totalBtnH = BUTTONS.length * (BTN_HEIGHT + BTN_GAP) - BTN_GAP;
                const startY = h - BTN_PAD_Y - totalBtnH;

                for (let i = 0; i < BUTTONS.length; i++) {
                    const y = startY + i * (BTN_HEIGHT + BTN_GAP);
                    if (pos[0] >= BTN_PAD_X && pos[0] <= w - BTN_PAD_X &&
                        pos[1] >= y && pos[1] <= y + BTN_HEIGHT) {
                        return i;
                    }
                }
                return -1;
            };

            // 监听执行完成
            api.addEventListener("executed", (event) => {
                const detail = event.detail;
                if (!detail || String(detail.node) !== String(node.id)) return;
                const output = detail.output;
                if (output?.SEED != null) {
                    const seed = Array.isArray(output.SEED) ? output.SEED[0] : output.SEED;
                    node._lastQueuedSeed = seed;
                    node._btnLabels[2] = `♻️ 使用上次种子 (${seed})`;
                    node.setDirtyCanvas(true, false);
                }
            });

            return r;
        };
    },

    async nodeCreated(node) {
        if (node.comfyClass !== "IS_NoisyLatentImage") return;
        node.color = "#1a1a2e";
        node.bgcolor = "#16213e";
    },
});
