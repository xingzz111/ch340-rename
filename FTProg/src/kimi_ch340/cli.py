from __future__ import annotations

import argparse
import os
import sys
from typing import Optional

from kimi_ch340 import __version__
from kimi_ch340.ch34x import Ch34xError, open_eeprom_usb, usb_list_devices


LOGO = r"""
   ____ _   _ _____  _  _    ___
  / ___| | | |___ / | || |  / _ \
 | |   | |_| | |_ \ | || |_| | | |
 | |___|  _  |___) ||__   _| |_| |
  \____|_| |_|____/    |_|  \___/
"""


def _p(s: str) -> None:
    sys.stdout.write(s + "\n")


def _use_color(stream) -> bool:
    if not hasattr(stream, "isatty") or not stream.isatty():
        return False
    if os.environ.get("NO_COLOR") is not None:
        return False
    term = os.environ.get("TERM", "")
    return term.lower() not in {"", "dumb"}


def _c(s: str, code: str) -> str:
    if not _use_color(sys.stdout):
        return s
    return f"\033[{code}m{s}\033[0m"


def _c_err(s: str, code: str) -> str:
    if not _use_color(sys.stderr):
        return s
    return f"\033[{code}m{s}\033[0m"


def _e(s: str) -> None:
    sys.stderr.write(_c_err(s, "31") + "\n")


def _hint_for_error(msg: str) -> None:
    m = msg.lower()
    hints: list[str] = []
    if "no backend available" in m or "libusb" in m:
        hints.append("请使用打包好的 dist/kimi-ch340（已内置 libusb），或重新构建并内置 universal libusb")
    if "operation timed out" in m or "timed out" in m or "timeout" in m:
        hints.append("确认没有其它程序占用串口（例如串口助手/日志工具），并尝试重新插拔 USB")
        hints.append("若仍失败，尝试 sudo 运行（USB 访问权限问题）")
    if "access denied" in m or "permission" in m or "operation not permitted" in m:
        hints.append("可能是权限问题：尝试 sudo 运行，或把可执行文件放到可写目录")
    if not hints:
        return
    for h in hints:
        _p(_c("提示: " + h, "33"))


def _parse_int_auto(s: str) -> int:
    s = s.strip().lower()
    if s.startswith("0x"):
        return int(s, 16)
    return int(s, 10)

def cmd_set_serial(args: argparse.Namespace) -> int:
    t = None
    try:
        t, e = open_eeprom_usb(vid=args.vid, pid=args.pid, bus=args.bus, address=args.address)
        before = e.read_serial_ascii()
        e.write_serial_ascii(args.value)
        after = e.read_serial_ascii()
        _p(f"Serial String: {before!r} -> {after!r}")
        if after != args.value:
            _e("写入后校验失败")
            return 3
        _p("请重新插拔 USB，再用 ls /dev/cu.* 验证设备名是否变为 usbserial-<Serial>")
        return 0
    except Ch34xError as ex:
        msg = str(ex)
        _e(msg)
        _hint_for_error(msg)
        return 2
    finally:
        if t is not None:
            t.close()


def cmd_set_kimi(args: argparse.Namespace) -> int:
    args.value = "Kimi"
    return cmd_set_serial(args)


def _prompt(text: str, *, default: Optional[str] = None) -> str:
    if default is not None and default != "":
        q = f"{text} [{default}] "
    else:
        q = f"{text} "
    sys.stdout.write(_c(q, "36"))
    sys.stdout.flush()
    s = sys.stdin.readline()
    if not s:
        return default or ""
    s = s.strip()
    if not s and default is not None:
        return default
    return s


def _select_device() -> Optional[dict]:
    while True:
        try:
            devs = usb_list_devices(vid=0x1A86, pid=None)
        except Ch34xError as ex:
            msg = str(ex)
            _e(msg)
            if "no backend available" in msg.lower() or "backend" in msg.lower() or "libusb" in msg.lower():
                _p(_c("当前环境缺少 libusb 后端。此工具支持离线使用：请使用我们打包好的 dist/kimi-ch340（已内置 libusb）。", "33"))
                _p(_c("如果你是从源码 python 运行的，请改用 dist/kimi-ch340，或在有网络环境下安装 libusb。", "33"))
                return None
            return None

        if not devs:
            _e("未找到 CH340 设备（VID=0x1A86）。请确认拨码开关切到 CH340B 那路并重新插拔 USB。")
            return None
        if len(devs) == 1:
            d = devs[0]
            return {
                "vid": int(d.idVendor),
                "pid": int(d.idProduct),
                "bus": getattr(d, "bus", None),
                "address": getattr(d, "address", None),
            }

        _p(_c("USB 设备：", "1;34"))
        for i, d in enumerate(devs, 0):
            _p(f"  {_c(str(i).rjust(2), '33')}) {d.idVendor:04x}:{d.idProduct:04x}")
        s = _prompt("请选择设备序号（b 返回）:", default="0")
        if s.lower() in {"b", "back"}:
            return None
        try:
            idx = int(s, 10)
        except ValueError:
            _e("请输入数字序号。")
            continue
        if idx < 0 or idx >= len(devs):
            _e("序号超范围。")
            continue
        d = devs[idx]
        return {
            "vid": int(d.idVendor),
            "pid": int(d.idProduct),
            "bus": getattr(d, "bus", None),
            "address": getattr(d, "address", None),
        }


def run_menu() -> int:
    _p(_c(LOGO.rstrip("\n"), "1;35"))
    _p(_c(f"Version: {__version__}", "2"))
    _p("")

    while True:
        _p(_c("请选择功能：", "1;34"))
        _p(f"  {_c(' 1', '33')}) 写入 Serial String（自定义）")
        _p(f"  {_c(' 2', '33')}) 一键改名为 Kimi")
        _p(f"  {_c(' 3', '33')}) 退出")
        s = _prompt("输入序号:", default="2")
        try:
            choice = int(s, 10)
        except ValueError:
            _e("请输入数字序号。")
            continue
        if choice == 3:
            return 0

        if choice == 1:
            dev = _select_device()
            if dev is None:
                _p("")
                continue
            value = _prompt("请输入 Serial（ASCII，最长 8 字符）:")
            if not value:
                _e("Serial 不能为空。")
                _p("")
                continue
            rc = cmd_set_serial(argparse.Namespace(**dev, value=value))
            _p("")
            continue

        if choice == 2:
            dev = _select_device()
            if dev is None:
                _p("")
                continue
            rc = cmd_set_serial(argparse.Namespace(**dev, value="Kimi"))
            _p("")
            continue

        _e("序号超范围。")
        _p("")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kimi-ch340")
    p.add_argument("-V", "--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=False)

    p_set = sub.add_parser("set-serial", help="写入 Serial String(最长 8 字符 ASCII)")
    p_set.add_argument("value")
    p_set.add_argument("--vid", type=_parse_int_auto, default=0x1A86)
    p_set.add_argument("--pid", type=_parse_int_auto, default=0x7523)
    p_set.add_argument("--bus", type=int, default=None)
    p_set.add_argument("--address", type=int, default=None)
    p_set.set_defaults(func=cmd_set_serial)

    p_kimi = sub.add_parser("set-kimi", help="把 Serial String 写成 Kimi")
    p_kimi.add_argument("--vid", type=_parse_int_auto, default=0x1A86)
    p_kimi.add_argument("--pid", type=_parse_int_auto, default=0x7523)
    p_kimi.add_argument("--bus", type=int, default=None)
    p_kimi.add_argument("--address", type=int, default=None)
    p_kimi.set_defaults(func=cmd_set_kimi)

    p_menu = sub.add_parser("menu", help="交互式菜单（序号选择）")
    p_menu.set_defaults(func=lambda _: run_menu())

    return p


def main(argv: Optional[list[str]] = None) -> None:
    parser = build_parser()
    raw = sys.argv[1:] if argv is None else argv
    if not raw:
        if sys.stdin.isatty() and sys.stdout.isatty():
            rc = int(run_menu())
            raise SystemExit(rc)
        parser.print_help(sys.stdout)
        raise SystemExit(2)
    args = parser.parse_args(raw)
    if not hasattr(args, "func"):
        parser.print_help(sys.stdout)
        raise SystemExit(2)
    rc = int(args.func(args))
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
