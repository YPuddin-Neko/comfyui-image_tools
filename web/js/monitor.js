import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { ComfyButtonGroup } from "../../scripts/ui/components/buttonGroup.js";

/**
 * 性能监控 - 嵌入 ComfyUI 顶部菜单栏
 * 彩色方块指示器 + 原生设置面板
 */

const GB = 1073741824;
const fmtGB = (b) => (b ? (b / GB).toFixed(1) : "0.0");

// ==================== 全局状态 ====================
let monitorEl = null;
let elements = {};
let lastLayoutKey = null;
let currentData = null;

// 设置缓存（从 ComfyUI settings 读取）
const cfg = {
    enabled: true,
    showCpu: true,
    showRam: true,
    showSwap: true,
    showGpu: true,
    showVram: true,
    showTemp: true,
    showPwr: true,
    showHdd: true,
    gpuIndex: -1,
    numbersOnly: false,
    dualRow: false,
    displayOrder: "cpu,ram,swap,gpu,vram,mps,temp,pwr,hdd",
};

// ==================== 样式 ====================
function injectStyles() {
    const style = document.createElement("style");
    style.textContent = `
.it-mon {
    display: flex; align-items: center; gap: 10px;
    font: 500 11px/1 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    color: rgba(255,255,255,0.88);
    padding: 0 8px;
    height: 100%;
    white-space: nowrap;
    flex-shrink: 0;
}
.it-mon.it-dual-row {
    display: grid;
    grid-template-rows: 1fr 1fr;
    grid-auto-flow: column;
    gap: 4px 10px;
    height: auto; padding: 2px 8px;
    max-width: 600px;
}
.it-mon.it-dual-row .it-mon-item {
    min-width: 95px;
}
.it-mon.it-dual-row .it-mon-sep {
    display: none;
}
.it-mon-col-sep {
    width: 1px;
    background: rgba(255,255,255,0.15);
    grid-row: 1 / -1;
}
.it-mon-item {
    display: flex; align-items: center; gap: 4px;
    position: relative; cursor: default;
}
.it-mon-dot {
    width: 8px; height: 8px; border-radius: 2px;
    flex-shrink: 0;
}
.it-mon-bar-bg {
    width: 48px; height: 6px;
    background: rgba(255,255,255,0.1);
    border-radius: 3px; overflow: hidden;
}
.it-mon-bar-fill {
    height: 100%; width: 0%; border-radius: 3px;
    transition: width 0.6s ease;
}
.it-mon-val {
    min-width: 32px; font-size: 11px;
    font-variant-numeric: tabular-nums;
}
.it-mon-sep {
    width: 1px; height: 12px;
    background: rgba(255,255,255,0.12);
    flex-shrink: 0;
}
/* 颜色 */
.it-c-cpu  { background: #4facfe; }
.it-c-ram  { background: #43e97b; }
.it-c-swap { background: #fda085; }
.it-c-gpu  { background: #fa709a; }
.it-c-vram { background: #a18cd1; }
.it-c-temp { background: #ff6b6b; }
.it-c-pwr  { background: #f7971e; }
.it-c-hdd  { background: #8e8e8e; }
.it-c-mps  { background: #ff6b6b; }
/* 进度条填充 */
.it-f-cpu  { background: linear-gradient(90deg, #4facfe, #00f2fe); }
.it-f-ram  { background: linear-gradient(90deg, #43e97b, #38f9d7); }
.it-f-swap { background: linear-gradient(90deg, #f6d365, #fda085); }
.it-f-gpu  { background: linear-gradient(90deg, #fa709a, #fee140); }
.it-f-vram { background: linear-gradient(90deg, #a18cd1, #fbc2eb); }
.it-f-temp { background: linear-gradient(90deg, #ff9a9e, #fad0c4); }
.it-f-pwr  { background: linear-gradient(90deg, #f7971e, #ffd200); }
.it-f-hdd  { background: linear-gradient(90deg, #bbb, #888); }
.it-f-mps  { background: linear-gradient(90deg, #ff6b6b, #ee5a24); }
.it-f-warn { background: linear-gradient(90deg, #f5576c, #ff6b6b) !important; }
/* Tooltip - 向下显示 */
.it-mon-tip {
    position: fixed;
    background: rgba(20,20,30,0.95);
    border: 1px solid rgba(255,255,255,0.12);
    padding: 4px 8px; border-radius: 5px;
    font-size: 11px; color: rgba(255,255,255,0.92);
    pointer-events: none; opacity: 0;
    transition: opacity 0.15s; white-space: pre;
    box-shadow: 0 4px 12px rgba(0,0,0,0.3); z-index: 100000;
}
`;
    document.head.appendChild(style);
}

// ==================== DOM 构建 ====================
function createItem(id, color, label, fillCls) {
    if (elements[id]) return elements[id].container;

    const c = document.createElement("div");
    c.className = "it-mon-item";

    const dot = document.createElement("span");
    dot.className = `it-mon-dot ${color}`;

    const lbl = document.createElement("span");
    lbl.textContent = label;
    lbl.style.opacity = "0.65";
    lbl.style.fontSize = "10px";

    const bg = document.createElement("div");
    bg.className = "it-mon-bar-bg";
    const fill = document.createElement("div");
    fill.className = `it-mon-bar-fill ${fillCls}`;
    bg.appendChild(fill);

    const val = document.createElement("span");
    val.className = "it-mon-val";
    val.textContent = "—";

    const tip = document.createElement("div");
    tip.className = "it-mon-tip";

    c.addEventListener("mouseenter", () => {
        const rect = c.getBoundingClientRect();
        tip.style.left = `${rect.left + rect.width / 2}px`;
        tip.style.top = `${rect.bottom + 6}px`;
        tip.style.transform = "translateX(-50%)";
        tip.style.opacity = "1";
    });
    c.addEventListener("mouseleave", () => {
        tip.style.opacity = "0";
    });

    c.append(dot, lbl, bg, val, tip);
    elements[id] = { container: c, fill, val, tip, bg };
    return c;
}

function sep() {
    const d = document.createElement("div");
    d.className = "it-mon-sep";
    return d;
}

function updateItem(id, pct, display, tooltip) {
    const el = elements[id];
    if (!el) return;
    pct = Math.max(0, Math.min(100, pct || 0));
    el.fill.style.width = `${pct}%`;
    el.val.textContent = display || "—";
    el.fill.classList.toggle("it-f-warn", pct > 80);
    el.bg.style.display = cfg.numbersOnly ? "none" : "";
    if (tooltip) {
        el.tip.textContent = tooltip;
        el.tip.style.display = "";
    } else {
        el.tip.style.display = "none";
    }
}

// ==================== 菜单栏注入 ====================
let buttonGroup = null;

function injectMonitor() {
    if (monitorEl) return;

    monitorEl = document.createElement("div");
    monitorEl.className = "it-mon";
    monitorEl.id = "it-monitor-root";

    // 使用 ComfyUI 官方 API 注入（和 Crystools 相同方式）
    const tryInject = () => {
        // 方法1: app.menu API（新版 Top/Bottom 菜单）
        if (app.menu?.settingsGroup?.element) {
            try {
                buttonGroup = new ComfyButtonGroup();
                buttonGroup.element.appendChild(monitorEl);
                app.menu.settingsGroup.element.before(buttonGroup.element);
                console.log("[ImageTools Monitor] 注入成功: app.menu.settingsGroup");
                return true;
            } catch (e) {
                console.warn("[ImageTools Monitor] ComfyButtonGroup 注入失败:", e);
            }
        }

        // 方法2: 旧版菜单 queue-button 后面
        const queueBtn = document.getElementById("queue-button");
        if (queueBtn) {
            queueBtn.insertAdjacentElement("afterend", monitorEl);
            console.log("[ImageTools Monitor] 注入成功: queue-button");
            return true;
        }

        return false;
    };

    if (!tryInject()) {
        let attempts = 0;
        const interval = setInterval(() => {
            if (tryInject() || ++attempts > 60) {
                clearInterval(interval);
                if (attempts > 60) {
                    console.warn("[ImageTools Monitor] 30秒内未找到菜单栏");
                }
            }
        }, 500);
    }
}

// ==================== 主更新 ====================
function updateMonitor(data) {
    if (!cfg.enabled || !data || !monitorEl) return;
    currentData = data;

    const p = data.platform || "cpu";
    const gi = data.gpu_index ?? -1;
    let gpus = data.gpus || [];
    if (gi >= 0) gpus = gpus.filter(g => g.index === gi);

    // 构建布局 key
    const key = `${p}_${gi}_${gpus.length}_${cfg.showCpu}_${cfg.showRam}_${cfg.showSwap}_${cfg.showGpu}_${cfg.showVram}_${cfg.showTemp}_${cfg.showPwr}_${cfg.showHdd}_${cfg.numbersOnly}_${cfg.dualRow}_${cfg.displayOrder}`;

    if (lastLayoutKey !== key) {
        lastLayoutKey = key;
        elements = {};
        monitorEl.innerHTML = "";
        monitorEl.classList.toggle("it-dual-row", cfg.dualRow);

        const allItems = [];
        // System items
        if (cfg.showCpu) allItems.push({key: "cpu", color: "it-c-cpu", label: "CPU", fill: "it-f-cpu"});
        if (cfg.showRam) allItems.push({key: "ram", color: "it-c-ram", label: "RAM", fill: "it-f-ram"});
        if (cfg.showSwap && data.swap_total > 0) allItems.push({key: "swap", color: "it-c-swap", label: "Swap", fill: "it-f-swap"});
        // GPU items (nvidia)
        if (p === "nvidia") {
            for (const gpu of gpus) {
                const s = gpus.length > 1 ? ` ${gpu.index}` : "";
                if (cfg.showGpu) allItems.push({key: `gpu${gpu.index}`, color: "it-c-gpu", label: `GPU${s}`, fill: "it-f-gpu", sortKey: "gpu"});
                if (cfg.showVram) allItems.push({key: `vram${gpu.index}`, color: "it-c-vram", label: `VRAM${s}`, fill: "it-f-vram", sortKey: "vram"});
                if (cfg.showTemp && gpu.temperature >= 0) allItems.push({key: `temp${gpu.index}`, color: "it-c-temp", label: `Temp${s}`, fill: "it-f-temp", sortKey: "temp"});
                if (cfg.showPwr && gpu.power_draw >= 0) allItems.push({key: `pwr${gpu.index}`, color: "it-c-pwr", label: `PWR${s}`, fill: "it-f-pwr", sortKey: "pwr"});
            }
        }
        // Apple Silicon
        if (p === "apple_silicon" && gpus.length > 0) {
            allItems.push({key: "mps", color: "it-c-mps", label: "MPS", fill: "it-f-mps"});
            if (cfg.showPwr && gpus[0].power_draw >= 0) allItems.push({key: "pwr_apple", color: "it-c-pwr", label: "PWR", fill: "it-f-pwr", sortKey: "pwr"});
        }
        if (cfg.showHdd) allItems.push({key: "hdd", color: "it-c-hdd", label: "HDD", fill: "it-f-hdd"});

        // Sort by displayOrder
        const order = cfg.displayOrder.split(",").map(s => s.trim());
        allItems.sort((a, b) => {
            const aKey = a.sortKey || a.key;
            const bKey = b.sortKey || b.key;
            const ai = order.indexOf(aKey);
            const bi = order.indexOf(bKey);
            return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
        });

        for (let i = 0; i < allItems.length; i++) {
            const item = allItems[i];
            monitorEl.appendChild(createItem(item.key, item.color, item.label, item.fill));
            // In dual-row mode, add column separator after every 2 items (if not last)
            if (cfg.dualRow && i % 2 === 1 && i < allItems.length - 1) {
                const colSep = document.createElement("div");
                colSep.className = "it-mon-col-sep";
                monitorEl.appendChild(colSep);
            }
            // In single-row mode, NO separators (remove old sep logic)
        }
    }

    // 数值更新
    if (cfg.showCpu)
        updateItem("cpu", data.cpu_percent, `${(data.cpu_percent || 0).toFixed(0)}%`);

    if (cfg.showRam)
        updateItem("ram", data.ram_percent,
            `${(data.ram_percent || 0).toFixed(0)}%`,
            `已用 ${fmtGB(data.ram_used)} / ${fmtGB(data.ram_total)} GB`);

    if (cfg.showSwap && data.swap_total > 0)
        updateItem("swap", data.swap_percent,
            `${(data.swap_percent || 0).toFixed(0)}%`,
            `已用 ${fmtGB(data.swap_used)} / ${fmtGB(data.swap_total)} GB`);

    if (p === "nvidia") {
        for (const gpu of gpus) {
            const i = gpu.index;
            if (cfg.showGpu)
                updateItem(`gpu${i}`, gpu.gpu_percent, `${gpu.gpu_percent || 0}%`, gpu.name);
            if (cfg.showVram) {
                // 详细 VRAM tooltip: 驱动层 + PyTorch allocated + reserved
                let vramTip = `驱动: ${fmtGB(gpu.vram_used)} / ${fmtGB(gpu.vram_total)} GB`;
                if (gpu.torch_allocated >= 0)
                    vramTip += `\nPyTorch 已分配: ${fmtGB(gpu.torch_allocated)} GB`;
                if (gpu.torch_reserved >= 0)
                    vramTip += `\nPyTorch 缓存池: ${fmtGB(gpu.torch_reserved)} GB`;
                updateItem(`vram${i}`, gpu.vram_percent,
                    `${fmtGB(gpu.vram_used)}G`,
                    vramTip);
            }
            if (cfg.showTemp && gpu.temperature >= 0)
                updateItem(`temp${i}`, gpu.temperature, `${gpu.temperature}°C`);
            if (cfg.showPwr && gpu.power_draw >= 0) {
                const pwrPct = gpu.power_limit > 0 ? (gpu.power_draw / gpu.power_limit) * 100 : 0;
                const pwrTip = gpu.power_limit > 0
                    ? `${gpu.power_draw}W / ${gpu.power_limit}W (${pwrPct.toFixed(0)}%)`
                    : `${gpu.power_draw}W`;
                updateItem(`pwr${i}`, pwrPct, `${gpu.power_draw}W`, pwrTip);
            }
        }
    } else if (p === "apple_silicon" && gpus.length > 0) {
        const gpu = gpus[0];
        const mps = gpu.mps_allocated || 0;
        const pct = data.ram_total ? (mps / data.ram_total) * 100 : 0;
        updateItem("mps", pct, `${fmtGB(mps)} GB`,
            `已分配: ${fmtGB(gpu.mps_allocated)} GB / 驱动: ${fmtGB(gpu.mps_driver)} GB`);
        if (cfg.showPwr && gpu.power_draw >= 0) {
            let pwrTip = `GPU: ${gpu.power_draw}W`;
            if (gpu.cpu_power >= 0) pwrTip += `\nCPU: ${gpu.cpu_power}W`;
            if (gpu.package_power >= 0) pwrTip += `\nSoC 总功耗: ${gpu.package_power}W`;
            updateItem("pwr_apple", 0, `${gpu.power_draw}W`, pwrTip);
        }
    }

    if (cfg.showHdd)
        updateItem("hdd", data.hdd_percent,
            `${(data.hdd_percent || 0).toFixed(0)}%`,
            `已用 ${fmtGB(data.hdd_used)} / ${fmtGB(data.hdd_total)} GB`);
}

// ==================== 设置变更回调 ====================
function onSettingChange() {
    lastLayoutKey = null; // 强制重建布局
    if (currentData) updateMonitor(currentData);
}

function onToggleChange(value) {
    cfg.enabled = value;
    if (monitorEl) monitorEl.style.display = value ? "" : "none";
    // 同步到后端
    api.fetchApi("/image_tools/monitor/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: value }),
    }).catch(() => {});
}

// ==================== 注册扩展 ====================
app.registerExtension({
    name: "comfyui.image_tools.monitor",

    settings: [
        // === 配置 ===
        {
            id: "ImageTools.Monitor.Enabled",
            name: "启用监控",
            type: "boolean",
            defaultValue: true,
            onChange: (v) => { onToggleChange(v); },
        },
        {
            id: "ImageTools.Monitor.NumbersOnly",
            name: "仅显示数字",
            tooltip: "隐藏进度条，只显示数值",
            type: "boolean",
            defaultValue: false,
            onChange: (v) => { cfg.numbersOnly = v; onSettingChange(); },
        },
        {
            id: "ImageTools.Monitor.DualRow",
            name: "双行显示",
            tooltip: "监控项分两行显示，避免过长",
            type: "boolean",
            defaultValue: false,
            onChange: (v) => { cfg.dualRow = v; onSettingChange(); },
        },
        {
            id: "ImageTools.Monitor.DisplayOrder",
            name: "显示顺序",
            tooltip: "用英文逗号分隔，可用项: cpu, ram, swap, gpu, vram, mps, temp, pwr, hdd。前后顺序决定显示位置，双行模式下相邻两项在同一竖列",
            type: "text",
            defaultValue: "cpu,ram,swap,gpu,vram,mps,temp,pwr,hdd",
            onChange: (v) => { cfg.displayOrder = v; onSettingChange(); },
        },
        {
            id: "ImageTools.Monitor.RefreshRate",
            name: "刷新频率（秒）",
            type: "slider",
            attrs: { min: 1, max: 5, step: 1 },
            defaultValue: 1,
            onChange: (v) => {
                api.fetchApi("/image_tools/monitor/settings", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ interval: v }),
                }).catch(() => {});
            },
        },
        // === 硬件 ===
        {
            id: "ImageTools.Hardware.CPU",
            name: "CPU 使用率",
            type: "boolean",
            defaultValue: true,
            onChange: (v) => { cfg.showCpu = v; onSettingChange(); },
        },
        {
            id: "ImageTools.Hardware.RAM",
            name: "RAM 使用率",
            type: "boolean",
            defaultValue: true,
            onChange: (v) => { cfg.showRam = v; onSettingChange(); },
        },
        {
            id: "ImageTools.Hardware.Swap",
            name: "Swap 虚拟内存",
            type: "boolean",
            defaultValue: true,
            onChange: (v) => { cfg.showSwap = v; onSettingChange(); },
        },
        {
            id: "ImageTools.Hardware.GPU",
            name: "GPU 使用率",
            type: "boolean",
            defaultValue: true,
            onChange: (v) => { cfg.showGpu = v; onSettingChange(); },
        },
        {
            id: "ImageTools.Hardware.VRAM",
            name: "VRAM 显存",
            type: "boolean",
            defaultValue: true,
            onChange: (v) => { cfg.showVram = v; onSettingChange(); },
        },
        {
            id: "ImageTools.Hardware.Temperature",
            name: "GPU 温度",
            type: "boolean",
            defaultValue: true,
            onChange: (v) => { cfg.showTemp = v; onSettingChange(); },
        },
        {
            id: "ImageTools.Hardware.Power",
            name: "GPU 功率",
            type: "boolean",
            defaultValue: true,
            onChange: (v) => { cfg.showPwr = v; onSettingChange(); },
        },
        {
            id: "ImageTools.Hardware.HDD",
            name: "硬盘使用率",
            type: "boolean",
            defaultValue: true,
            onChange: (v) => { cfg.showHdd = v; onSettingChange(); },
        },
    ],

    async setup() {
        injectStyles();
        injectMonitor();

        // 从 ComfyUI 设置读取初始值
        const get = (id, fallback) => {
            try {
                const v = app.extensionManager.setting.get(id);
                return v !== undefined && v !== null ? v : fallback;
            } catch { return fallback; }
        };

        cfg.enabled = get("ImageTools.Monitor.Enabled", true);
        cfg.numbersOnly = get("ImageTools.Monitor.NumbersOnly", false);
        cfg.dualRow = get("ImageTools.Monitor.DualRow", false);
        cfg.displayOrder = get("ImageTools.Monitor.DisplayOrder", "cpu,ram,swap,gpu,vram,mps,temp,pwr,hdd");
        cfg.showCpu = get("ImageTools.Hardware.CPU", true);
        cfg.showRam = get("ImageTools.Hardware.RAM", true);
        cfg.showSwap = get("ImageTools.Hardware.Swap", true);
        cfg.showGpu = get("ImageTools.Hardware.GPU", true);
        cfg.showVram = get("ImageTools.Hardware.VRAM", true);
        cfg.showTemp = get("ImageTools.Hardware.Temperature", true);
        cfg.showPwr = get("ImageTools.Hardware.Power", true);
        cfg.showHdd = get("ImageTools.Hardware.HDD", true);

        if (!cfg.enabled && monitorEl) {
            monitorEl.style.display = "none";
        }

        // 从后端加载动态选项并注册到设置面板
        try {
            const [settResp, partResp, gpuResp] = await Promise.all([
                api.fetchApi("/image_tools/monitor/settings"),
                api.fetchApi("/image_tools/monitor/partitions"),
                api.fetchApi("/image_tools/monitor/gpus"),
            ]);
            const settings = await settResp.json();
            const partitions = await partResp.json();
            const gpuData = await gpuResp.json();

            cfg.gpuIndex = settings.gpu_index ?? -1;

            // 硬盘分区 combo (字符串数组格式)
            if (Array.isArray(partitions) && partitions.length > 0) {
                const partLabels = partitions.map(p => p.mountpoint);
                app.registerExtension({
                    name: "comfyui.image_tools.monitor.disk",
                    settings: [{
                        id: "ImageTools.Disk.Partition",
                        name: "监控分区",
                        type: "combo",
                        options: partLabels,
                        defaultValue: settings.hdd_path || partLabels[0],
                        onChange: (v) => {
                            api.fetchApi("/image_tools/monitor/settings", {
                                method: "POST",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({ hdd_path: v }),
                            }).catch(() => {});
                        },
                    }],
                });
            }

            // GPU 选择 combo（多 GPU 时）
            if (gpuData.gpus && gpuData.gpus.length > 1) {
                const gpuLabels = [
                    "全部显示",
                    ...gpuData.gpus.map(g => `GPU ${g.index}: ${g.name}`),
                ];
                app.registerExtension({
                    name: "comfyui.image_tools.monitor.gpu",
                    settings: [{
                        id: "ImageTools.GPU.Selection",
                        name: "监控 GPU",
                        type: "combo",
                        options: gpuLabels,
                        defaultValue: "全部显示",
                        onChange: (v) => {
                            let idx = -1;
                            if (v !== "全部显示") {
                                const match = v.match(/GPU (\d+)/);
                                if (match) idx = parseInt(match[1]);
                            }
                            cfg.gpuIndex = idx;
                            onSettingChange();
                            api.fetchApi("/image_tools/monitor/settings", {
                                method: "POST",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({ gpu_index: idx }),
                            }).catch(() => {});
                        },
                    }],
                });
            }
        } catch (e) {
            console.warn("[ImageTools Monitor] 加载设置失败:", e);
        }

        // 监听 WebSocket
        api.addEventListener("image_tools.monitor", (event) => {
            updateMonitor(event.detail);
        });
    },
});
