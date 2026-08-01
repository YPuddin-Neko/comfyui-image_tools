"""
性能监控 - 系统资源实时监控
支持 NVIDIA 多 GPU / Apple Silicon / CPU-only
"""

import os
import sys
import json
import time
import platform as platform_mod
import threading
import subprocess
import ctypes
from server import PromptServer
from aiohttp import web

# 可选依赖
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

try:
    import pynvml
    HAS_PYNVML = True
except ImportError:
    HAS_PYNVML = False

try:
    import torch
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(PLUGIN_DIR, "monitor_settings.json")


class SystemMonitor:
    def __init__(self):
        self.enabled = True
        self.interval = 1.0
        self.hdd_path = "/"
        self.gpu_index = -1  # -1 = 显示所有 GPU
        if sys.platform == "win32":
            self.hdd_path = "C:\\"

        self.load_settings()

        self.platform = "cpu"
        self.gpu_count = 0
        self.gpu_names = []
        self._init_platform()

        # Apple Silicon 功率监控初始化
        self._init_apple_power()

        self._stop_event = threading.Event()
        self._thread = None

        if HAS_PSUTIL:
            # 初始化 cpu_percent（首次调用返回 0，需预热）
            psutil.cpu_percent(interval=None)

    def load_settings(self):
        """加载配置"""
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    settings = json.load(f)
                    self.enabled = settings.get("enabled", self.enabled)
                    self.interval = settings.get("interval", self.interval)
                    self.hdd_path = settings.get("hdd_path", self.hdd_path)
                    self.gpu_index = settings.get("gpu_index", self.gpu_index)
            except Exception as e:
                print(f"[ImageTools Monitor] 无法读取设置: {e}")

    def save_settings(self):
        """保存配置"""
        try:
            settings = {
                "enabled": self.enabled,
                "interval": self.interval,
                "hdd_path": self.hdd_path,
                "gpu_index": self.gpu_index,
            }
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=4)
        except Exception as e:
            print(f"[ImageTools Monitor] 无法保存设置: {e}")

    def _init_platform(self):
        """初始化平台信息 (NVIDIA, Apple Silicon, 或 CPU)"""
        if HAS_PYNVML:
            try:
                pynvml.nvmlInit()
                self.gpu_count = pynvml.nvmlDeviceGetCount()
                if self.gpu_count > 0:
                    self.platform = "nvidia"
                    # 缓存 GPU 名称列表
                    for i in range(self.gpu_count):
                        handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                        name = pynvml.nvmlDeviceGetName(handle)
                        if isinstance(name, bytes):
                            name = name.decode("utf-8")
                        self.gpu_names.append(name)
                    return
            except Exception as e:
                print(f"[ImageTools Monitor] pynvml 初始化失败: {e}")

        # Apple Silicon (macOS ARM64 + MPS)
        if (sys.platform == "darwin" and platform_mod.machine() == "arm64" and
                HAS_TORCH and hasattr(torch.backends, "mps") and torch.backends.mps.is_available()):
            self.platform = "apple_silicon"
            self.gpu_count = 1
            # 获取芯片名
            try:
                res = subprocess.run(
                    ["sysctl", "-n", "machdep.cpu.brand_string"],
                    capture_output=True, text=True, timeout=3
                )
                chip_name = res.stdout.strip() if res.returncode == 0 else "Apple Silicon"
            except Exception:
                chip_name = "Apple Silicon"
            self.gpu_names = [f"{chip_name} GPU"]
            return

        self.platform = "cpu"

    # ==================== 数据采集 ====================

    def _get_nvidia_gpus(self):
        """获取所有 NVIDIA GPU 状态（含功率、PyTorch 显存详情）"""
        gpus = []
        if not HAS_PYNVML:
            return gpus

        try:
            for i in range(self.gpu_count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)

                mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
                vram_total = mem_info.total
                vram_used = mem_info.used
                vram_percent = round((vram_used / vram_total) * 100, 1) if vram_total > 0 else 0.0

                try:
                    util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                    gpu_percent = util.gpu
                except Exception:
                    gpu_percent = 0

                try:
                    temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
                except Exception:
                    temp = -1

                # 功率 (毫瓦 -> 瓦)
                power_draw = -1
                power_limit = -1
                try:
                    power_draw = round(pynvml.nvmlDeviceGetPowerUsage(handle) / 1000, 1)
                except Exception:
                    pass
                try:
                    power_limit = round(pynvml.nvmlDeviceGetEnforcedPowerLimit(handle) / 1000, 1)
                except Exception:
                    pass

                # PyTorch CUDA 显存详情
                torch_allocated = -1
                torch_reserved = -1
                if HAS_TORCH and torch.cuda.is_available():
                    try:
                        torch_allocated = torch.cuda.memory_allocated(i)
                        torch_reserved = torch.cuda.memory_reserved(i)
                    except Exception:
                        pass

                gpus.append({
                    "index": i,
                    "name": self.gpu_names[i] if i < len(self.gpu_names) else f"GPU {i}",
                    "gpu_percent": gpu_percent,
                    "vram_total": vram_total,
                    "vram_used": vram_used,
                    "vram_percent": vram_percent,
                    "temperature": temp,
                    "power_draw": power_draw,
                    "power_limit": power_limit,
                    "torch_allocated": torch_allocated,
                    "torch_reserved": torch_reserved,
                })
        except Exception:
            pass

        return gpus

    # ==================== Apple Silicon 功率读取 ====================

    def _init_apple_power(self):
        """初始化 IOReport 功率监控 (macOS arm64, 免 sudo)"""
        self._apple_power_ok = False
        self._apple_power = {"gpu": -1, "cpu": -1, "package": -1}

        if sys.platform != "darwin" or platform_mod.machine() != "arm64":
            return

        try:
            import ctypes
            import ctypes.util

            cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
            ior = ctypes.CDLL("/usr/lib/libIOReport.dylib")

            # CoreFoundation 函数签名
            cf.CFStringCreateWithCString.restype = ctypes.c_void_p
            cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
            cf.CFRelease.restype = None
            cf.CFRelease.argtypes = [ctypes.c_void_p]

            # IOReport 函数签名
            ior.IOReportCopyChannelsInGroup.restype = ctypes.c_void_p
            ior.IOReportCopyChannelsInGroup.argtypes = [
                ctypes.c_void_p, ctypes.c_void_p,
                ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64,
            ]
            ior.IOReportCreateSubscription.restype = ctypes.c_void_p
            ior.IOReportCreateSubscription.argtypes = [
                ctypes.c_void_p, ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint64,
                ctypes.POINTER(ctypes.c_void_p),
            ]
            ior.IOReportCreateSamples.restype = ctypes.c_void_p
            ior.IOReportCreateSamples.argtypes = [
                ctypes.c_void_p, ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_void_p),
            ]
            ior.IOReportCreateSamplesDelta.restype = ctypes.c_void_p
            ior.IOReportCreateSamplesDelta.argtypes = [
                ctypes.c_void_p, ctypes.c_void_p,
                ctypes.POINTER(ctypes.c_void_p),
            ]
            ior.IOReportSimpleGetIntegerValue.restype = ctypes.c_int64
            ior.IOReportSimpleGetIntegerValue.argtypes = [ctypes.c_void_p, ctypes.c_int32]
            ior.IOReportChannelGetChannelName.restype = ctypes.c_void_p
            ior.IOReportChannelGetChannelName.argtypes = [ctypes.c_void_p]
            ior.IOReportChannelGetSubGroup.restype = ctypes.c_void_p
            ior.IOReportChannelGetSubGroup.argtypes = [ctypes.c_void_p]

            # CFString → Python str
            cf.CFStringGetLength.restype = ctypes.c_long
            cf.CFStringGetLength.argtypes = [ctypes.c_void_p]
            cf.CFStringGetCString.restype = ctypes.c_bool
            cf.CFStringGetCString.argtypes = [
                ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32,
            ]

            # CFArray 遍历
            cf.CFArrayGetCount.restype = ctypes.c_long
            cf.CFArrayGetCount.argtypes = [ctypes.c_void_p]
            cf.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
            cf.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]

            # CFDictionary 取值
            cf.CFDictionaryGetValue.restype = ctypes.c_void_p
            cf.CFDictionaryGetValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

            def cfstr(s):
                return cf.CFStringCreateWithCString(None, s.encode("utf-8"), 0)

            def cfstr_to_py(ref):
                if not ref:
                    return ""
                length = cf.CFStringGetLength(ref)
                buf = ctypes.create_string_buffer(length * 4 + 1)
                if cf.CFStringGetCString(ref, buf, len(buf), 0x08000100):
                    return buf.value.decode("utf-8")
                return ""

            # 创建 Energy Model 订阅
            group_str = cfstr("Energy Model")
            channels = ior.IOReportCopyChannelsInGroup(group_str, None, 0, 0, 0)
            if not channels:
                return

            sub_ch = ctypes.c_void_p()
            err = ctypes.c_void_p()
            sub = ior.IOReportCreateSubscription(
                None, channels, ctypes.byref(sub_ch), 0, ctypes.byref(err)
            )
            if not sub:
                return

            # 首次采样
            first = ior.IOReportCreateSamples(sub, sub_ch, ctypes.byref(err))
            if not first:
                return

            # 保存状态
            self._ap_cf = cf
            self._ap_ior = ior
            self._ap_sub = sub
            self._ap_sub_ch = sub_ch
            self._ap_prev = first
            self._ap_prev_t = time.monotonic()
            self._ap_cfstr_to_py = cfstr_to_py
            self._ap_cfstr = cfstr
            self._apple_power_ok = True

            print("[ImageTools Monitor] Apple Silicon 功率监控已启用 (IOReport)")

        except Exception as e:
            print(f"[ImageTools Monitor] Apple 功率监控不可用: {e}")

    def _read_apple_power(self):
        """读取 Apple Silicon 实时功率 (W)"""
        if not self._apple_power_ok:
            return self._apple_power

        try:
            cf = self._ap_cf
            ior = self._ap_ior
            cfstr_to_py = self._ap_cfstr_to_py

            now = time.monotonic()
            dt = now - self._ap_prev_t
            if dt < 0.3:
                return self._apple_power

            err = ctypes.c_void_p()
            cur = ior.IOReportCreateSamples(
                self._ap_sub, self._ap_sub_ch, ctypes.byref(err)
            )
            if not cur:
                return self._apple_power

            delta = ior.IOReportCreateSamplesDelta(
                self._ap_prev, cur, ctypes.byref(err)
            )
            if not delta:
                cf.CFRelease(cur)
                return self._apple_power

            # 解析 delta - 遍历 IOReportChannels 数组
            # 注意: "GPU Energy" / "CPU Energy" 是累计型大值 channel，需排除
            # 正确的 channel:
            #   GPU 功率: "GPU", "GPU SRAM"
            #   CPU 功率: "ECPU*", "PCPU*" 或 "CPU Energy"
            #   其他: "DRAM", "ANE", "SOC_AON" 等
            gpu_mj = 0.0
            cpu_mj = 0.0
            other_mj = 0.0

            # 排除的累计型 channel (值量级远大于其他)
            EXCLUDE = {"GPU Energy", "CPU Energy"}

            # delta 是 CFDictionary，内含 IOReportChannels CFArray
            key_str = self._ap_cfstr("IOReportChannels")
            ch_array = cf.CFDictionaryGetValue(delta, key_str)

            if ch_array:
                count = cf.CFArrayGetCount(ch_array)
                for i in range(count):
                    item = cf.CFArrayGetValueAtIndex(ch_array, i)
                    if not item:
                        continue
                    try:
                        ch_name = cfstr_to_py(ior.IOReportChannelGetChannelName(item))
                        if ch_name in EXCLUDE:
                            continue
                        val = ior.IOReportSimpleGetIntegerValue(item, 0)
                        if val <= 0:
                            continue

                        # GPU 相关
                        if ch_name in ("GPU", "GPU SRAM"):
                            gpu_mj += val
                        # CPU 相关 (ECPU=能效核, PCPU=性能核)
                        elif ch_name.startswith(("ECPU", "PCPU")):
                            cpu_mj += val
                        # 其他 SoC 组件 (DRAM, ANE, ISP, etc.)
                        else:
                            other_mj += val
                    except Exception:
                        continue

            cf.CFRelease(key_str)
            cf.CFRelease(delta)
            cf.CFRelease(self._ap_prev)
            self._ap_prev = cur
            self._ap_prev_t = now

            # mJ → W: P = E(mJ) / t(s) / 1000
            gpu_w = round(gpu_mj / dt / 1000, 2) if dt > 0 else 0
            cpu_w = round(cpu_mj / dt / 1000, 2) if dt > 0 else 0
            pkg_w = round((gpu_mj + cpu_mj + other_mj) / dt / 1000, 2)

            self._apple_power = {"gpu": gpu_w, "cpu": cpu_w, "package": pkg_w}
            return self._apple_power

        except Exception:
            return self._apple_power

    def _get_apple_silicon_gpu(self, ram_total, ram_used, ram_percent):
        """获取 Apple Silicon GPU 状态（统一内存 + MPS + 功率）"""
        # 读取功率
        power = self._read_apple_power()

        gpu = {
            "index": 0,
            "name": self.gpu_names[0] if self.gpu_names else "Apple Silicon GPU",
            "gpu_percent": -1,
            "vram_total": ram_total,
            "vram_used": ram_used,
            "vram_percent": ram_percent,
            "temperature": -1,
            "power_draw": power["gpu"],
            "power_limit": -1,
            "torch_allocated": -1,
            "torch_reserved": -1,
            "mps_allocated": 0,
            "mps_driver": 0,
            "cpu_power": power["cpu"],
            "package_power": power["package"],
        }

        if HAS_TORCH:
            try:
                gpu["mps_allocated"] = torch.mps.current_allocated_memory()
                gpu["mps_driver"] = torch.mps.driver_allocated_memory()
            except Exception:
                pass

        return [gpu]

    def collect_and_send(self):
        """收集系统数据并通过 WebSocket 发送"""
        if not self.enabled or not HAS_PSUTIL:
            return

        try:
            # CPU
            cpu_percent = psutil.cpu_percent(interval=None)

            # 物理内存
            vm = psutil.virtual_memory()
            ram_total = vm.total
            ram_used = vm.used
            ram_percent = vm.percent

            # 虚拟内存 / Swap
            swap = psutil.swap_memory()
            swap_total = swap.total
            swap_used = swap.used
            swap_percent = swap.percent

            # 硬盘
            try:
                disk = psutil.disk_usage(self.hdd_path)
                hdd_total = disk.total
                hdd_used = disk.used
                hdd_percent = disk.percent
            except Exception:
                hdd_total = 0
                hdd_used = 0
                hdd_percent = 0.0

            # GPU
            all_gpus = []
            if self.platform == "nvidia":
                all_gpus = self._get_nvidia_gpus()
            elif self.platform == "apple_silicon":
                all_gpus = self._get_apple_silicon_gpu(ram_total, ram_used, ram_percent)

            data = {
                "platform": self.platform,
                "cpu_percent": cpu_percent,
                "ram_total": ram_total,
                "ram_used": ram_used,
                "ram_percent": ram_percent,
                "swap_total": swap_total,
                "swap_used": swap_used,
                "swap_percent": swap_percent,
                "hdd_total": hdd_total,
                "hdd_used": hdd_used,
                "hdd_percent": hdd_percent,
                "gpus": all_gpus,
                "gpu_count": self.gpu_count,
                "gpu_index": self.gpu_index,
            }

            PromptServer.instance.send_sync("image_tools.monitor", data)
        except Exception as e:
            print(f"[ImageTools Monitor] 收集数据出错: {e}")

    def loop(self):
        """监控循环"""
        while not self._stop_event.is_set():
            if self.enabled:
                self.collect_and_send()
            self._stop_event.wait(self.interval)

    def start(self):
        """启动监控线程"""
        if not HAS_PSUTIL:
            print("[ImageTools Monitor] 未安装 psutil，系统监控无法启动。")
            return

        if self._thread is None or not self._thread.is_alive():
            self._stop_event.clear()
            self._thread = threading.Thread(target=self.loop, daemon=True)
            self._thread.start()
            print(f"[ImageTools Monitor] 监控线程已启动 (平台: {self.platform}, GPU: {self.gpu_count})")

    def stop(self):
        """停止监控线程"""
        if self._thread and self._thread.is_alive():
            self._stop_event.set()
            self._thread.join(timeout=2.0)
            print("[ImageTools Monitor] 监控线程已停止")


# 实例化监控器 (单例)
monitor_instance = SystemMonitor()


# ==================== API 路由注册 ====================

@PromptServer.instance.routes.get("/image_tools/monitor/settings")
async def get_settings(request):
    """获取当前监控设置"""
    return web.json_response({
        "enabled": monitor_instance.enabled,
        "interval": monitor_instance.interval,
        "hdd_path": monitor_instance.hdd_path,
        "gpu_index": monitor_instance.gpu_index,
        "platform": monitor_instance.platform,
        "gpu_count": monitor_instance.gpu_count,
    })


@PromptServer.instance.routes.post("/image_tools/monitor/settings")
async def set_settings(request):
    """更新监控设置"""
    try:
        data = await request.json()
        if "enabled" in data:
            monitor_instance.enabled = bool(data["enabled"])
        if "interval" in data:
            monitor_instance.interval = float(data["interval"])
        if "hdd_path" in data:
            monitor_instance.hdd_path = str(data["hdd_path"])
        if "gpu_index" in data:
            monitor_instance.gpu_index = int(data["gpu_index"])

        monitor_instance.save_settings()
        return web.json_response({"status": "success"})
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=400)


@PromptServer.instance.routes.get("/image_tools/monitor/partitions")
async def get_partitions(request):
    """获取所有磁盘分区"""
    if not HAS_PSUTIL:
        return web.json_response({"status": "error", "message": "psutil not installed"}, status=500)

    try:
        partitions = []
        for p in psutil.disk_partitions(all=False):
            if p.fstype == "":
                continue
            try:
                usage = psutil.disk_usage(p.mountpoint)
                partitions.append({
                    "device": p.device,
                    "mountpoint": p.mountpoint,
                    "fstype": p.fstype,
                    "total": usage.total,
                })
            except PermissionError:
                continue
        return web.json_response(partitions)
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500)


@PromptServer.instance.routes.get("/image_tools/monitor/gpus")
async def get_gpus(request):
    """获取 GPU 列表（供前端选择）"""
    gpus = []
    for i, name in enumerate(monitor_instance.gpu_names):
        gpus.append({"index": i, "name": name})
    return web.json_response({
        "gpus": gpus,
        "gpu_index": monitor_instance.gpu_index,
        "platform": monitor_instance.platform,
    })


def setup_monitor():
    """启动监控"""
    if not HAS_PSUTIL:
        print("[ImageTools Monitor] 警告: 未检测到 psutil，系统监控功能被禁用。请安装 psutil。")
        return

    monitor_instance.start()
