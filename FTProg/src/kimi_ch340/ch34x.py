from __future__ import annotations

import ctypes
import os
import sys
import time
from typing import Optional


class Ch34xError(RuntimeError):
    pass


def _vendor_libusb_path() -> str:
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    return os.path.join(base, "vendor", "libusb", "macos", "libusb-1.0.0.dylib")


def _get_libusb_backend():
    try:
        import usb.backend.libusb1  # type: ignore
    except Exception:
        return None
    try:
        def find_library(_: str):
            candidates: list[str] = []

            vendor = _vendor_libusb_path()
            if os.path.isfile(vendor):
                candidates.append(vendor)

            meipass = getattr(sys, "_MEIPASS", None)
            if isinstance(meipass, str) and meipass:
                candidates.extend(
                    [
                        os.path.join(meipass, "libusb-1.0.0.dylib"),
                        os.path.join(meipass, "libusb-1.0.dylib"),
                    ]
                )

            exe_dir = os.path.dirname(sys.executable) if getattr(sys, "executable", None) else ""
            if exe_dir:
                candidates.extend(
                    [
                        os.path.join(exe_dir, "libusb-1.0.0.dylib"),
                        os.path.join(exe_dir, "libusb-1.0.dylib"),
                    ]
                )

            for p in candidates:
                if os.path.isfile(p):
                    return p
            return None

        return usb.backend.libusb1.get_backend(find_library=find_library)
    except Exception:
        return None


def _find_libusb_paths() -> list[str]:
    out: list[str] = []
    vendor = _vendor_libusb_path()
    if os.path.isfile(vendor):
        out.append(vendor)
    meipass = getattr(sys, "_MEIPASS", None)
    if isinstance(meipass, str) and meipass:
        out.extend(
            [
                os.path.join(meipass, "libusb-1.0.0.dylib"),
                os.path.join(meipass, "libusb-1.0.dylib"),
            ]
        )
    exe_dir = os.path.dirname(sys.executable) if getattr(sys, "executable", None) else ""
    if exe_dir:
        out.extend(
            [
                os.path.join(exe_dir, "libusb-1.0.0.dylib"),
                os.path.join(exe_dir, "libusb-1.0.dylib"),
            ]
        )
    return [p for p in out if os.path.isfile(p)]


def _diagnose_libusb_load() -> Optional[str]:
    paths = _find_libusb_paths()
    if not paths:
        return None
    try:
        for p in paths:
            try:
                ctypes.CDLL(p)
                return None
            except OSError as e:
                if "wrong architecture" in str(e).lower():
                    return "内置 libusb 架构不匹配（universal 产物可能只带了单一架构的 libusb）。请重新构建时提供两份 libusb 并生成 universal2。"
        return "检测到内置 libusb，但加载失败。请重新构建打包产物。"
    except Exception:
        return "检测到内置 libusb，但无法加载。请重新构建打包产物。"


class UsbTransport:
    def __init__(self, dev):
        self._dev = dev
        self._intf = None

    def open(self) -> None:
        try:
            if getattr(self._dev, "set_configuration", None) is not None:
                self._dev.set_configuration()
            cfg = self._dev.get_active_configuration()
            for intf in cfg:
                self._intf = int(intf.bInterfaceNumber)
                break
        except Exception as e:
            raise Ch34xError(f"USB 初始化失败: {e}") from e

    def control_read(self, request: int, w_value: int, w_index: int, length: int, timeout_ms: int = 1000) -> bytes:
        try:
            data = self._dev.ctrl_transfer(0xC0, request, w_value, w_index, length, timeout=timeout_ms)
            return bytes(data)
        except Exception as e:
            raise Ch34xError(f"USB control 读失败: {e}") from e

    def control_write(self, request: int, w_value: int, w_index: int, timeout_ms: int = 1000) -> None:
        try:
            self._dev.ctrl_transfer(0x40, request, w_value, w_index, 0, timeout=timeout_ms)
        except Exception as e:
            raise Ch34xError(f"USB control 写失败: {e}") from e

    def close(self) -> None:
        pass


class Ch34xEepromUsb:
    def __init__(self, t: UsbTransport):
        self._t = t
        self._proto = self._detect_proto()

    def _init_for_ch340b(self) -> None:
        self._t.control_write(0xA1, 0xC39C, 0xD9E8, timeout_ms=500)
        self._t.control_write(0xA4, 0x00DF, 0x0000, timeout_ms=500)
        self._t.control_write(0xA4, 0x009F, 0x0000, timeout_ms=500)

    def _try_read_byte(self, addr: int, *, request: int, addr_in_index: bool) -> int:
        if request == 0x54:
            self._init_for_ch340b()
            data = self._t.control_read(request, addr << 8, 0xA001, 1, timeout_ms=800)
        elif addr_in_index:
            data = self._t.control_read(request, 0x0000, addr & 0xFF, 1, timeout_ms=800)
        else:
            data = self._t.control_read(request, addr & 0xFF, 0x0000, 1, timeout_ms=800)
        if len(data) != 1:
            raise Ch34xError("EEPROM 读返回长度异常")
        return data[0]

    def _detect_proto(self) -> tuple[int, int, bool]:
        candidates: list[tuple[int, int, bool]] = [
            (0x54, 0x54, False),
            (0xA1, 0xA0, False),
            (0xA1, 0xA0, True),
            (0x95, 0x9A, False),
            (0x95, 0x9A, True),
        ]
        first_working: Optional[tuple[int, int, bool]] = None
        for read_req, write_req, addr_in_index in candidates:
            try:
                vid_l = self._try_read_byte(0x04, request=read_req, addr_in_index=addr_in_index)
                vid_h = self._try_read_byte(0x05, request=read_req, addr_in_index=addr_in_index)
                pid_l = self._try_read_byte(0x06, request=read_req, addr_in_index=addr_in_index)
                pid_h = self._try_read_byte(0x07, request=read_req, addr_in_index=addr_in_index)
            except Exception:
                continue
            if first_working is None:
                first_working = (read_req, write_req, addr_in_index)
            vid = (vid_h << 8) | vid_l
            pid = (pid_h << 8) | pid_l
            if vid == 0x1A86 and pid in {0x7523, 0x5523}:
                return (read_req, write_req, addr_in_index)
        if first_working is not None:
            return first_working
        raise Ch34xError("无法识别 EEPROM 配置协议（USB 模式）")

    def read_byte(self, addr: int) -> int:
        if not (0 <= addr <= 0xFF):
            raise Ch34xError("EEPROM 地址超范围")
        read_req, _, addr_in_index = self._proto
        return self._try_read_byte(addr, request=read_req, addr_in_index=addr_in_index)

    def write_byte(self, addr: int, value: int) -> None:
        if not (0 <= addr <= 0xFF):
            raise Ch34xError("EEPROM 地址超范围")
        if not (0 <= value <= 0xFF):
            raise Ch34xError("EEPROM 写入值超范围")
        _, write_req, addr_in_index = self._proto

        if write_req == 0x54:
            self._init_for_ch340b()
            w_value = ((addr & 0xFF) << 8) | (value & 0xFF)
            self._t.control_write(write_req, w_value, 0xA001, timeout_ms=1200)
            time.sleep(0.01)
            self._t.control_write(0x5E, 0x000A, 0x0000, timeout_ms=1200)
            time.sleep(0.01)
        elif addr_in_index:
            w_value = value & 0xFF
            w_index = addr & 0xFF
            self._t.control_write(write_req, w_value, w_index, timeout_ms=1200)
            time.sleep(0.008)
        else:
            w_value = ((value & 0xFF) << 8) | (addr & 0xFF)
            w_index = 0x0000
            self._t.control_write(write_req, w_value, w_index, timeout_ms=1200)
            time.sleep(0.008)

    def begin_write_session(self) -> None:
        _, write_req, addr_in_index = self._proto
        if write_req == 0x54:
            return
        if write_req != 0xA0:
            return
        if addr_in_index:
            self._t.control_write(write_req, 0x005B, 0x0000, timeout_ms=1200)
        else:
            self._t.control_write(write_req, 0x5B00, 0x0000, timeout_ms=1200)
        time.sleep(0.02)

    def read_serial_ascii(self) -> str:
        raw = bytes(self.read_byte(a) for a in range(0x10, 0x18))
        raw = raw.split(b"\x00", 1)[0]
        try:
            return raw.decode("ascii", errors="strict")
        except Exception:
            return raw.decode("ascii", errors="replace")

    def write_serial_ascii(self, s: str) -> None:
        b = s.encode("ascii", errors="strict")
        if len(b) > 8:
            raise Ch34xError("Serial String 最长 8 字符")
        buf = b.ljust(8, b"\x00")
        self.begin_write_session()
        for i, addr in enumerate(range(0x10, 0x18)):
            self.write_byte(addr, buf[i])

    def read_product_string(self) -> str:
        length = self.read_byte(0x1A)
        if length < 2:
            return ""
        body_len = max(0, min(length - 2, 36))
        raw = bytes(self.read_byte(a) for a in range(0x1C, 0x1C + body_len))
        try:
            return raw.decode("utf-16le", errors="replace")
        except Exception:
            return ""


def usb_list_devices(vid: Optional[int] = 0x1A86, pid: Optional[int] = None):
    try:
        import usb.core  # type: ignore
    except Exception as e:
        raise Ch34xError(f"缺少依赖 pyusb: {e}") from e
    backend = _get_libusb_backend()
    if backend is None:
        hint = _diagnose_libusb_load()
        if hint:
            raise Ch34xError(hint)
        raise Ch34xError("No backend available")
    kwargs = {"find_all": True}
    if vid is not None:
        kwargs["idVendor"] = vid
    if pid is not None:
        kwargs["idProduct"] = pid
    if backend is not None:
        kwargs["backend"] = backend
    try:
        return list(usb.core.find(**kwargs) or [])
    except Exception as e:
        raise Ch34xError(str(e)) from e


def open_eeprom_usb(vid: int = 0x1A86, pid: int = 0x7523, bus: Optional[int] = None, address: Optional[int] = None):
    devs = usb_list_devices(vid=vid, pid=pid)
    if not devs:
        raise Ch34xError("未找到目标 USB 设备")
    chosen = None
    for d in devs:
        if bus is not None and getattr(d, "bus", None) != bus:
            continue
        if address is not None and getattr(d, "address", None) != address:
            continue
        chosen = d
        break
    if chosen is None:
        chosen = devs[0]
    t = UsbTransport(chosen)
    t.open()
    return t, Ch34xEepromUsb(t)
