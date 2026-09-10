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

# ---- 递归补签兜底（仅 CI 配置了 Apple 证书时）----
# PyInstaller 的 codesign_identity 已递归签 _internal + 主 EXE（带 entitlements），
# 这里再兜底一遍：防止个别未被 PyInstaller 收集的 Mach-O 漏签，确保 notarize 万无一失。
IDENTITY="${APPLE_SIGNING_IDENTITY:-}"
if [ -n "$IDENTITY" ]; then
  echo "[build] 递归补签 sidecar 内所有 Mach-O（identity=$IDENTITY）"
  ENT="$ROOT/desktop/entitlements.plist"
  find "$TMPD/pichome-server" -type f -print0 | \
  while IFS= read -r -d '' f; do
    # 主 EXE 由 PyInstaller 已带 entitlements 签好，这里不要清掉它的 entitlements，跳过
    [ "$f" = "$TMPD/pichome-server/pichome-server" ] && continue
    if file "$f" | grep -q "Mach-O"; then
      codesign --force --timestamp --options runtime -s "$IDENTITY" "$f"
    fi
  done
  # 主 EXE 最后再确认带 entitlements 签一次（幂等，确保保留 Python 运行时放行项）
  codesign --force --timestamp --options runtime \
    --entitlements "$ENT" -s "$IDENTITY" "$TMPD/pichome-server/pichome-server"
  echo "[build] sidecar codesign 完成"
fi

mkdir -p desktop/src-tauri/bin
cp -R "$TMPD/pichome-server/." desktop/src-tauri/bin/pichome-server/

echo "[build] sidecar 已生成：desktop/src-tauri/bin/pichome-server"
