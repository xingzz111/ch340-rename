#!/bin/zsh
if [ -z "${ZSH_VERSION:-}" ]; then
  exec zsh "$0" "$@"
fi
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"
BUILD_DIR="$ROOT_DIR/build"

rm -rf "$DIST_DIR" "$BUILD_DIR"
mkdir -p "$DIST_DIR"
mkdir -p "$BUILD_DIR/pyinstaller-config" "$BUILD_DIR/spec"

PYTHON_BIN="${PYTHON_BIN:-python3.11}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "找不到 $PYTHON_BIN。请先安装 Python3.11，或设置 PYTHON_BIN=/path/to/python3.11"
  exit 2
fi

PYTHON_X86_64_BIN="${PYTHON_X86_64_BIN:-}"
BUILD_X86_64="${BUILD_X86_64:-auto}"
LIBUSB_DYLIB_PATH="${LIBUSB_DYLIB_PATH:-}"
LIBUSB_DYLIB_PATH_ARM64="${LIBUSB_DYLIB_PATH_ARM64:-}"
LIBUSB_DYLIB_PATH_X86_64="${LIBUSB_DYLIB_PATH_X86_64:-}"

UNIVERSAL_LIBUSB_DIR="$BUILD_DIR/libusb"
UNIVERSAL_LIBUSB_PATH="$UNIVERSAL_LIBUSB_DIR/libusb-1.0.0.dylib"

find_libusb_dylib() {
  local lib=""
  if [[ -n "$LIBUSB_DYLIB_PATH" && -f "$LIBUSB_DYLIB_PATH" ]]; then
    echo "$LIBUSB_DYLIB_PATH"
    return
  fi
  if [[ -f "$ROOT_DIR/vendor/libusb/macos/libusb-1.0.0.dylib" ]]; then
    echo "$ROOT_DIR/vendor/libusb/macos/libusb-1.0.0.dylib"
    return
  fi
  if command -v brew >/dev/null 2>&1; then
    local prefix=""
    prefix="$(brew --prefix libusb 2>/dev/null || true)"
    if [[ -n "$prefix" && -f "$prefix/lib/libusb-1.0.0.dylib" ]]; then
      lib="$prefix/lib/libusb-1.0.0.dylib"
    fi
    if [[ -z "$lib" && -n "$prefix" && -f "$prefix/opt/libusb/lib/libusb-1.0.0.dylib" ]]; then
      lib="$prefix/opt/libusb/lib/libusb-1.0.0.dylib"
    fi
    if [[ -z "$lib" && -n "$prefix" && -f "$prefix/lib/libusb-1.0.dylib" ]]; then
      lib="$prefix/lib/libusb-1.0.dylib"
    fi
  fi
  if [[ -z "$lib" && -f "/opt/homebrew/opt/libusb/lib/libusb-1.0.0.dylib" ]]; then
    lib="/opt/homebrew/opt/libusb/lib/libusb-1.0.0.dylib"
  fi
  if [[ -z "$lib" && -f "/opt/homebrew/lib/libusb-1.0.0.dylib" ]]; then
    lib="/opt/homebrew/lib/libusb-1.0.0.dylib"
  fi
  if [[ -z "$lib" && -f "/usr/local/opt/libusb/lib/libusb-1.0.0.dylib" ]]; then
    lib="/usr/local/opt/libusb/lib/libusb-1.0.0.dylib"
  fi
  if [[ -z "$lib" && -f "/usr/local/lib/libusb-1.0.0.dylib" ]]; then
    lib="/usr/local/lib/libusb-1.0.0.dylib"
  fi
  echo "$lib"
}

find_libusb_dylib_arm64() {
  if [[ -n "$LIBUSB_DYLIB_PATH_ARM64" && -f "$LIBUSB_DYLIB_PATH_ARM64" ]]; then
    echo "$LIBUSB_DYLIB_PATH_ARM64"
    return
  fi
  if [[ -f "/opt/homebrew/opt/libusb/lib/libusb-1.0.0.dylib" ]]; then
    echo "/opt/homebrew/opt/libusb/lib/libusb-1.0.0.dylib"
    return
  fi
  if [[ -f "/opt/homebrew/lib/libusb-1.0.0.dylib" ]]; then
    echo "/opt/homebrew/lib/libusb-1.0.0.dylib"
    return
  fi
  echo ""
}

find_libusb_dylib_x86_64() {
  if [[ -n "$LIBUSB_DYLIB_PATH_X86_64" && -f "$LIBUSB_DYLIB_PATH_X86_64" ]]; then
    echo "$LIBUSB_DYLIB_PATH_X86_64"
    return
  fi
  if [[ -f "/usr/local/opt/libusb/lib/libusb-1.0.0.dylib" ]]; then
    echo "/usr/local/opt/libusb/lib/libusb-1.0.0.dylib"
    return
  fi
  if [[ -f "/usr/local/lib/libusb-1.0.0.dylib" ]]; then
    echo "/usr/local/lib/libusb-1.0.0.dylib"
    return
  fi
  echo ""
}

prepare_universal_libusb() {
  if [[ -n "$LIBUSB_DYLIB_PATH" && -f "$LIBUSB_DYLIB_PATH" ]]; then
    return 0
  fi

  local a=""
  local x=""
  a="$(find_libusb_dylib_arm64)"
  x="$(find_libusb_dylib_x86_64)"
  if [[ -z "$a" || -z "$x" ]]; then
    return 0
  fi

  mkdir -p "$UNIVERSAL_LIBUSB_DIR"
  lipo -create -output "$UNIVERSAL_LIBUSB_PATH" "$a" "$x"
  LIBUSB_DYLIB_PATH="$UNIVERSAL_LIBUSB_PATH"
  export LIBUSB_DYLIB_PATH
  echo "prepared universal libusb: $UNIVERSAL_LIBUSB_PATH"
}

build_one() {
  local target_arch="$1"
  local runner="$2"
  local pybin="$3"
  local dist_subdir="$4"
  local work_subdir="$5"
  local config_dir="$6"

  if ! command -v "$pybin" >/dev/null 2>&1; then
    echo "找不到 Python: $pybin"
    return 2
  fi

  local -a prefix=()
  if [[ -n "$runner" ]]; then
    prefix=(${=runner})
  fi

  "${prefix[@]}" "$pybin" -m pip install -U pip setuptools wheel pyinstaller pyusb

  export PYINSTALLER_CONFIG_DIR="$config_dir"

  local libusb=""
  libusb="$(find_libusb_dylib)"
  if [[ -z "$libusb" ]]; then
    echo "仍未找到 libusb-1.0.0.dylib，无法把 libusb 打包进产物。"
    echo "离线构建请先准备好 libusb-1.0.0.dylib，然后指定环境变量："
    echo "  LIBUSB_DYLIB_PATH=/path/to/libusb-1.0.0.dylib bash scripts/build_universal2.sh"
    echo "构建 universal2 时建议提供两份："
    echo "  LIBUSB_DYLIB_PATH_ARM64=/path/to/arm64/libusb-1.0.0.dylib"
    echo "  LIBUSB_DYLIB_PATH_X86_64=/path/to/x86_64/libusb-1.0.0.dylib"
    return 2
  fi
  local add_bin_args=()
  add_bin_args=(--add-binary "$libusb:.")

  "${prefix[@]}" "$pybin" -m PyInstaller \
    --clean \
    --specpath "$BUILD_DIR/spec" \
    --onefile \
    --name kimi-ch340 \
    --distpath "$DIST_DIR/$dist_subdir" \
    --workpath "$BUILD_DIR/$work_subdir" \
    "${add_bin_args[@]}" \
    --paths "$ROOT_DIR/src" \
    "$ROOT_DIR/src/kimi_ch340/cli.py"

  file "$DIST_DIR/$dist_subdir/kimi-ch340" >/dev/null 2>&1 || true
  "${prefix[@]}" "$DIST_DIR/$dist_subdir/kimi-ch340" -V >/dev/null 2>&1 || true

  echo "build ok: $target_arch -> dist/$dist_subdir/kimi-ch340"
}

build_one_universal2() {
  local pybin="$1"
  local config_dir="$2"

  if ! command -v "$pybin" >/dev/null 2>&1; then
    echo "找不到 Python: $pybin"
    return 2
  fi

  "$pybin" -m pip install -U pip setuptools wheel pyinstaller pyusb
  export PYINSTALLER_CONFIG_DIR="$config_dir"

  local libusb=""
  libusb="$(find_libusb_dylib)"
  if [[ -z "$libusb" ]]; then
    echo "仍未找到 libusb-1.0.0.dylib，无法把 libusb 打包进产物。"
    return 2
  fi

  "$pybin" -m PyInstaller \
    --clean \
    --specpath "$BUILD_DIR/spec" \
    --onefile \
    --target-architecture universal2 \
    --name kimi-ch340 \
    --distpath "$DIST_DIR/universal2" \
    --workpath "$BUILD_DIR/universal2" \
    --add-binary "$libusb:." \
    --paths "$ROOT_DIR/src" \
    "$ROOT_DIR/src/kimi_ch340/cli.py"

  if [[ -f "$DIST_DIR/universal2/kimi-ch340" ]]; then
    cp -f "$DIST_DIR/universal2/kimi-ch340" "$DIST_DIR/kimi-ch340"
    chmod +x "$DIST_DIR/kimi-ch340" || true
    echo "universal2 ok: dist/kimi-ch340 (native universal2)"
    INFO="$(lipo -info "$DIST_DIR/kimi-ch340" 2>/dev/null || true)"
    echo "$INFO"
    if echo "$INFO" | grep -q "x86_64" && echo "$INFO" | grep -q "arm64"; then
      return 0
    fi
    echo "native universal2 构建未包含 x86_64+arm64 两个架构。"
    return 2
  fi
  return 2
}

rosetta_available() {
  arch -x86_64 /usr/bin/true >/dev/null 2>&1
}

detect_x86_64_python() {
  local candidates=()
  if [[ -n "$PYTHON_X86_64_BIN" ]]; then
    candidates+=("$PYTHON_X86_64_BIN")
  fi
  candidates+=("/usr/local/bin/python3.11" "/usr/local/bin/python3" "/usr/bin/python3")

  local c=""
  for c in "${candidates[@]}"; do
    if ! command -v "$c" >/dev/null 2>&1; then
      continue
    fi
    if arch -x86_64 "$c" -c 'import platform; import sys; print(platform.machine());' 2>/dev/null | grep -q '^x86_64$'; then
      echo "$c"
      return 0
    fi
  done
  return 1
}

ARCH="$(uname -m)"
if [[ "$ARCH" == "arm64" ]]; then
  prepare_universal_libusb || true
  build_one "arm64" "" "$PYTHON_BIN" "arm64" "arm64" "$BUILD_DIR/pyinstaller-config/arm64"

  make_universal_launcher_if_ready() {
    if [[ -f "$DIST_DIR/arm64/kimi-ch340" && -f "$DIST_DIR/x86_64/kimi-ch340" ]]; then
      echo "生成单文件 universal 启动器（自解压选择架构）..."
      OUT="$DIST_DIR/kimi-ch340"
      ARM_BIN="$DIST_DIR/arm64/kimi-ch340"
      X86_BIN="$DIST_DIR/x86_64/kimi-ch340"

      file "$ARM_BIN" | grep -q 'arm64' || { echo "arm64 产物架构异常"; exit 2; }
      file "$X86_BIN" | grep -q 'x86_64' || { echo "x86_64 产物架构异常"; exit 2; }

      ARM_SHA="$(shasum -a 256 "$ARM_BIN" | awk '{print $1}')"
      X86_SHA="$(shasum -a 256 "$X86_BIN" | awk '{print $1}')"

      OUT="$OUT" ARM_BIN="$ARM_BIN" X86_BIN="$X86_BIN" ARM_SHA="$ARM_SHA" X86_SHA="$X86_SHA" VERSION="0.1.0" python3 - <<'PY'
import base64
import os
from pathlib import Path

out = Path(os.environ["OUT"])
arm_path = Path(os.environ["ARM_BIN"])
x86_path = Path(os.environ["X86_BIN"])
version = os.environ["VERSION"]
arm_sha = os.environ["ARM_SHA"]
x86_sha = os.environ["X86_SHA"]

arm_b64 = base64.b64encode(arm_path.read_bytes()).decode("ascii")
x86_b64 = base64.b64encode(x86_path.read_bytes()).decode("ascii")

script = f"""#!/bin/zsh
if [ -z "${{ZSH_VERSION:-}}" ]; then
  exec zsh "$0" "$@"
fi
set -euo pipefail

ARCH="$(uname -m)"
case "$ARCH" in
  arm64) WANT="arm64" ;;
  x86_64) WANT="x86_64" ;;
  *) echo "unsupported arch: $ARCH" >&2; exit 2 ;;
esac

VERSION="{version}"
ARM_SHA="{arm_sha}"
X86_SHA="{x86_sha}"

TMP_BASE="${{TMPDIR:-/tmp}}"
WORK="$TMP_BASE/kimi-ch340-$VERSION-$WANT"
BIN="$WORK/kimi-ch340"
SHA_FILE="$WORK/sha256"
mkdir -p "$WORK"

EXPECTED="$ARM_SHA"
if [[ "$WANT" == "x86_64" ]]; then
  EXPECTED="$X86_SHA"
fi

if [[ -f "$SHA_FILE" && -x "$BIN" ]]; then
  HAVE="$(cat "$SHA_FILE" 2>/dev/null || true)"
  if [[ "$HAVE" == "$EXPECTED" ]]; then
    exec "$BIN" "$@"
  fi
fi

if [[ "$WANT" == "arm64" ]]; then
  base64 -D > "$BIN" <<'B64'
{arm_b64}
B64
else
  base64 -D > "$BIN" <<'B64'
{x86_b64}
B64
fi

chmod +x "$BIN"
echo -n "$EXPECTED" > "$SHA_FILE"
exec "$BIN" "$@"
"""

out.write_text(script, encoding="utf-8")
PY

      chmod +x "$OUT"
      echo "universal ok: dist/kimi-ch340 (self-extracting launcher)"
    fi
  }

  if [[ "$BUILD_X86_64" == "0" || "$BUILD_X86_64" == "false" || "$BUILD_X86_64" == "no" ]]; then
    echo "跳过 x86_64 构建（BUILD_X86_64=$BUILD_X86_64）"
    make_universal_launcher_if_ready || true
    exit 0
  fi

  if ! rosetta_available; then
    echo "未检测到 Rosetta，无法在 arm64 上执行 arch -x86_64。"
    echo "安装 Rosetta: softwareupdate --install-rosetta --agree-to-license"
    echo "将尝试直接构建 native universal2（不依赖 x86_64 Python）。"
    if ! build_one_universal2 "$PYTHON_BIN" "$BUILD_DIR/pyinstaller-config/universal2"; then
      echo "native universal2 构建失败。建议安装 python.org 的 universal2 Python3.11（/Library/Frameworks/Python.framework），再重试。"
      exit 2
    fi
    exit 0
  fi

  X86PY=""
  if X86PY="$(detect_x86_64_python)"; then
    prepare_universal_libusb || true
    build_one "x86_64" "arch -x86_64" "$X86PY" "x86_64" "x86_64" "$BUILD_DIR/pyinstaller-config/x86_64"
  else
    echo "未找到可用的 x86_64 Python。"
    echo "将尝试直接构建 native universal2（不依赖 x86_64 Python）。"
    if ! build_one_universal2 "$PYTHON_BIN" "$BUILD_DIR/pyinstaller-config/universal2"; then
      echo "native universal2 构建失败。"
      echo "方案 A: 安装 python.org 的 universal2 Python3.11（/Library/Frameworks/Python.framework），再重试。"
      echo "方案 B: 安装 x86_64 Python（Intel Homebrew /usr/local），再重试。"
      exit 2
    fi
    exit 0
  fi

  make_universal_launcher_if_ready || true
elif [[ "$ARCH" == "x86_64" ]]; then
  build_one "x86_64" "" "$PYTHON_BIN" "x86_64" "x86_64" "$BUILD_DIR/pyinstaller-config/x86_64"
  echo "请在 arm64 机器/环境重复执行本脚本，生成 dist/arm64/kimi-ch340，并自动生成 dist/kimi-ch340（单文件 universal 启动器）"
else
  echo "未知架构: $ARCH"
  exit 2
fi
