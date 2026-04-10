from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from typing import Optional


class UpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class UpdateAsset:
    url: str
    sha256: Optional[str] = None


@dataclass(frozen=True)
class UpdateManifest:
    version: str
    asset_universal2: Optional[UpdateAsset]

    @staticmethod
    def from_json_bytes(b: bytes) -> "UpdateManifest":
        obj = json.loads(b.decode("utf-8"))
        version = str(obj.get("version", "")).strip()
        assets = obj.get("assets", {}) or {}
        a = assets.get("macos-universal2")
        asset = None
        if isinstance(a, dict) and a.get("url"):
            asset = UpdateAsset(url=str(a["url"]), sha256=(str(a.get("sha256")) if a.get("sha256") else None))
        if not version:
            raise UpdateError("manifest 缺少 version")
        return UpdateManifest(version=version, asset_universal2=asset)


def _download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "kimi-ch340"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read()


def _sha256_hex(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def is_frozen_binary() -> bool:
    return bool(getattr(sys, "frozen", False))


def check_for_update(manifest_url: str) -> tuple[str, str]:
    manifest = UpdateManifest.from_json_bytes(_download(manifest_url))
    from . import __version__ as package_version

    current = os.environ.get("KIMI_CH340_VERSION") or package_version
    return current, manifest.version


def apply_update(manifest_url: str) -> str:
    manifest = UpdateManifest.from_json_bytes(_download(manifest_url))
    asset = manifest.asset_universal2
    if asset is None:
        raise UpdateError("manifest 未提供 macos-universal2 资源")
    if not is_frozen_binary():
        raise UpdateError("当前不是独立可执行文件模式，建议使用 pip 安装/升级")

    exe_path = sys.executable
    if not os.path.isfile(exe_path):
        raise UpdateError("无法定位当前可执行文件路径")

    if not os.access(os.path.dirname(exe_path), os.W_OK):
        raise UpdateError(f"无权限写入: {os.path.dirname(exe_path)}，请使用 sudo 或把可执行文件放到可写目录")

    with tempfile.TemporaryDirectory(prefix="kimi-ch340-update-") as td:
        tmp_path = os.path.join(td, "kimi-ch340.new")
        data = _download(asset.url)
        with open(tmp_path, "wb") as f:
            f.write(data)

        if asset.sha256:
            got = _sha256_hex(tmp_path)
            if got.lower() != asset.sha256.lower():
                raise UpdateError("sha256 校验失败")

        os.chmod(tmp_path, 0o755)
        backup = exe_path + ".bak"
        try:
            if os.path.exists(backup):
                os.remove(backup)
            shutil.copy2(exe_path, backup)
            os.replace(tmp_path, exe_path)
        except Exception as e:
            raise UpdateError(f"替换失败: {e}") from e
    return manifest.version
