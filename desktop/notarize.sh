#!/usr/bin/env bash
# =============================================================================
# PicHome —— 对 .app / .dmg 执行 Apple 公证（notarytool）+ 装订（stapler）
#
# 【为什么要自己接管公证】
#   Tauri 的内置公证（tauri-macos-sign / tauri-action）跑在 `tauri build` 的
#   最后一步：等它报错时，已经来不及补签嵌套的 framework 了 —— 这正是
#   v0.1.1~v0.1.6 反复失败的机制。所以我们让 `tauri build` 只做签名
#   （不传 APPLE_ID/PASSWORD/TEAM_ID，它会自动跳过公证），再由本脚本公证。
#
# 【用法】
#   APPLE_ID=... APPLE_PASSWORD=... APPLE_TEAM_ID=... desktop/notarize.sh <路径>
#
#   - 传 .app  → 自动 ditto 打成 zip 再提交（公证要求容器）
#   - 传 .dmg  → 直接提交
#   公证通过后自动 `stapler staple` 装订到原路径。
#
# 【未配置凭据时】直接跳过并返回 0（本地开发不阻塞构建）。
# =============================================================================
set -euo pipefail

TARGET="${1:-}"
if [ -z "$TARGET" ]; then
  echo "用法: $(basename "$0") <xxx.app|xxx.dmg>" >&2
  exit 2
fi

if [ -z "${APPLE_ID:-}" ] || [ -z "${APPLE_PASSWORD:-}" ] || [ -z "${APPLE_TEAM_ID:-}" ]; then
  echo "[notarize] 未配置 Apple 公证凭据（APPLE_ID / APPLE_PASSWORD / APPLE_TEAM_ID）→ 跳过公证"
  exit 0
fi

[ -e "$TARGET" ] || { echo "[notarize] 找不到目标：$TARGET" >&2; exit 1; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/pichome-notarize.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

# ---------------------------------------------------------------------------
# 准备提交物：.app 需要先打成 zip（保留 bundle 结构）
# ---------------------------------------------------------------------------
SUBMIT_PATH="$TARGET"
case "$TARGET" in
  *.app)
    SUBMIT_PATH="$WORK/$(basename "$TARGET" .app).zip"
    echo "[notarize] 打包 .app 为 zip（--keepParent 保留 bundle 结构）..."
    ditto -c -k --keepParent "$TARGET" "$SUBMIT_PATH"
    ;;
  *.dmg)
    # dmg 必须先签名再公证：
    #   - 未签名的 dmg 提交公证容易被拒；
    #   - 且 `stapler staple` 要求目标已签名，否则装订会失败。
    if [ -n "${APPLE_SIGNING_IDENTITY:-}" ]; then
      echo "[notarize] 对 dmg 签名：$APPLE_SIGNING_IDENTITY"
      codesign --force --timestamp --sign "$APPLE_SIGNING_IDENTITY" "$TARGET"
      codesign --verify --strict --verbose=2 "$TARGET"
    else
      echo "[notarize] ⚠️ 未提供 APPLE_SIGNING_IDENTITY，跳过 dmg 签名（公证/装订可能失败）"
    fi
    echo "[notarize] 直接提交 dmg（无需打包）"
    ;;
  *)
    echo "[notarize] 不支持的目标类型：${TARGET}（只支持 .app / .dmg）" >&2
    exit 1
    ;;
esac
ls -lh "$SUBMIT_PATH"

# ---------------------------------------------------------------------------
# 提交公证（--wait 同步等待结果）
# ---------------------------------------------------------------------------
echo "[notarize] 提交公证：$(basename "$TARGET")"
RC=0
xcrun notarytool submit "$SUBMIT_PATH" \
  --apple-id "$APPLE_ID" \
  --password "$APPLE_PASSWORD" \
  --team-id "$APPLE_TEAM_ID" \
  --wait --output-format json \
  > "$WORK/out.json" 2> "$WORK/err.txt" || RC=$?

echo "[notarize] ---- notarytool 输出 ----"
cat "$WORK/out.json" 2>/dev/null || true
if [ -s "$WORK/err.txt" ]; then
  cat "$WORK/err.txt" || true
fi

json_get() {  # $1 = 顶层字段名
  python3 -c 'import json,sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    d = {}
print(d.get(sys.argv[2], ""))' "$WORK/out.json" "$1" 2>/dev/null || true
}

STATUS="$(json_get status)"
SUBMIT_ID="$(json_get id)"

# ---------------------------------------------------------------------------
# 失败时自动拉取详细问题日志（含每个出问题的文件路径与原因）
# ---------------------------------------------------------------------------
if [ "$RC" -ne 0 ] || [ "$STATUS" != "Accepted" ]; then
  echo "[notarize] ❌ 公证未通过（rc=$RC, status=${STATUS:-<空>}）"
  if [ -n "$SUBMIT_ID" ]; then
    echo "[notarize] 拉取详细问题日志（notarytool log ${SUBMIT_ID}）..."
    xcrun notarytool log "$SUBMIT_ID" \
      --apple-id "$APPLE_ID" \
      --password "$APPLE_PASSWORD" \
      --team-id "$APPLE_TEAM_ID" || true
  else
    echo "[notarize] 未拿到 submission id，无法拉取详细日志"
  fi
  exit 1
fi

echo "[notarize] ✅ 公证通过（Accepted, id=${SUBMIT_ID}）"

# ---------------------------------------------------------------------------
# 装订（让离线/首次启动也能通过 Gatekeeper）
# ---------------------------------------------------------------------------
xcrun stapler staple "$TARGET"
xcrun stapler validate "$TARGET"
echo "[notarize] ✅ 装订完成：$TARGET"
