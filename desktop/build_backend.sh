#!/usr/bin/env bash
# 把 Django 后端冻结成 Tauri sidecar：desktop/src-tauri/bin/pichome-server
#
# 用法（在项目根目录，且 .venv 已装好依赖）：
#   bash desktop/build_backend.sh
#
# 产物：desktop/src-tauri/bin/pichome-server/（onedir，含 _internal/）
# 该路径正好对齐 tauri.conf.json 的 resources 映射 bin/pichome-server -> pichome-server
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ ! -x ".venv/bin/pyinstaller" ]; then
  echo "[build] 未找到 .venv/bin/pyinstaller，请先创建虚拟环境并安装："
  echo "        python -m venv .venv && . .venv/bin/activate"
  echo "        pip install -r requirements.txt pyinstaller waitress"
  exit 1
fi

# 先冻到全新临时目录，避免 PyInstaller 在 COLLECT 阶段递归删除已存在的
# bin/pichome-server（沙箱会拦截这种批量删除），再用 cp 逐文件合并进去。
TMPD="$(mktemp -d /tmp/pichome_dist.XXXXXX)"
.venv/bin/pyinstaller desktop/build.spec --noconfirm \
  --workpath /tmp/pichome_pi_build --distpath "$TMPD"

# 签名职责完全交给 PyInstaller 冻结阶段（见 desktop/build.spec 的 codesign_identity +
# entitlements_file）：它在 COLLECT 阶段递归签名整个 sidecar —— 主 EXE 附带 Python 运行时
# 所需的 entitlements（allow-jit / allow-unsigned-executable-memory / disable-library-validation），
# _internal 下所有 .so/.dylib/Python 解释器用 hardened runtime 签名。这样 tauri build 内部的
# notarize 才能通过。本脚本不再重复 codesign，避免变量未定义等副作用。
# 本地未配置 APPLE_SIGNING_IDENTITY 时 PyInstaller 自动跳过签名，仅出未签名产物。

mkdir -p desktop/src-tauri/bin
cp -R "$TMPD/pichome-server/." desktop/src-tauri/bin/pichome-server/

echo "[build] sidecar 已生成：desktop/src-tauri/bin/pichome-server"
