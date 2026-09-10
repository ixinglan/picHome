#!/usr/bin/env bash
# =============================================================================
# PicHome —— 对最终 .app 执行「由内到外」深度签名 + 全量签名校验收口
#
# 【为什么需要这个脚本】
#   Tauri 打包 macOS 时只会签「主程序 + 最外层 .app」，它内部的嵌套签名收集
#   （tauri-bundler 的 add_nested_code_sign_path）只扫描一层目录，够不到我们
#   sidecar 里深层嵌套的 `_internal/Python.framework`。
#
#   PyInstaller 虽然会签它，但签的是 bincache 缓存目录里的副本 —— 那个目录里
#   没有 Resources/Info.plist，因此 codesign 只能产出「扁平 Mach-O 签名」，
#   拿不到「框架包签名（bundle 签名）」。等 PyInstaller 再把 Info.plist 收进
#   产物后，框架外壳齐全、但签名没封住它 → Apple 公证判定：
#       "The signature of the binary is invalid."
#
#   本脚本在「最终产物」上、按正确形态重签（framework 当 bundle 签），根治该问题。
#
# 【签名顺序：必须由内到外】
#   1) 所有 Mach-O 文件（framework 内的二进制 / dylib / 可执行）
#      —— 已用「目标身份」正确签好的直接跳过（CI 上 PyInstaller 已签过绝大多数，
#         逐个重签会触发数百次 Apple 时间戳请求，任一次网络抖动都会让流水线失败）
#   2) 所有嵌套 bundle（.framework / .xpc / 内嵌 .app），最深优先，**无条件 --force 重签**
#      —— 这是核心修复点：`codesign --force <framework>` 会连带把框架内的主二进制
#         重签成 bundle 形态（绑住 Info.plist），这正是 flat 签名缺的那一步。
#      顺序不能反：若先签 bundle 再改内部文件，bundle 的 _CodeSignature 记录会失效
#      （"code has no resources but signature indicates they must be present"）。
#   3) 最外层 .app（带 entitlements）
#   4) 全量 codesign --verify --strict 收口，任一失败立即打印文件路径并退出
#
# 【用法】
#   desktop/sign_app_bundle.sh <PicHome.app 路径> [entitlements.plist]
#
# 【签名身份解析顺序】
#   1) 环境变量 APPLE_SIGNING_IDENTITY（CI 通过 secrets 注入）
#   2) 本机 keychain 的 "Developer ID Application"（本地开发便利）
#   3) 都没有 → 跳过（本地无证书场景，行为与之前一致）
# =============================================================================
set -euo pipefail

APP="${1:-}"
ENT="${2:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -z "$APP" ]; then
  echo "用法: $(basename "$0") <PicHome.app 路径> [entitlements.plist]" >&2
  exit 2
fi
[ -n "$ENT" ] || ENT="$SCRIPT_DIR/entitlements.plist"

log()  { printf '\033[1;36m[sign]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[sign]\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m[sign]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[sign]\033[0m %s\n' "$*" >&2; exit 1; }

[ -d "$APP" ] || die "找不到 app bundle：$APP"
[ -f "$ENT" ] || die "找不到 entitlements：$ENT"

# ---------------------------------------------------------------------------
# 解析签名身份
# ---------------------------------------------------------------------------
IDENTITY="${APPLE_SIGNING_IDENTITY:-}"
IDENTITY_SRC="环境变量 APPLE_SIGNING_IDENTITY"
if [ -z "$IDENTITY" ]; then
  IDENTITY="$(security find-identity -v -p codesigning 2>/dev/null \
    | sed -n 's/.*"\(Developer ID Application: .*\)"/\1/p' | head -1)"
  IDENTITY_SRC="keychain 自动发现"
fi
if [ -z "$IDENTITY" ]; then
  warn "未找到可用签名身份（APPLE_SIGNING_IDENTITY 为空，keychain 也没有 Developer ID Application）"
  warn "跳过深度签名，产物保持未签名状态。"
  exit 0
fi

log "目标 bundle ：$APP"
log "签名身份    ：${IDENTITY}（来源：${IDENTITY_SRC}）"
log "entitlements：$ENT"

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------
# ⚠️ 这里刻意不用 `cmd | grep -q`：在 `set -o pipefail` 下，`grep -q` 命中即退出，
#    会让上游命令收到 SIGPIPE（退出码 141），整个管道被判定为失败 ——
#    Bash 经典陷阱（本脚本第一版就踩了：所有文件都被误判成「需重签」）。
is_macho() {
  local info
  info="$(file -b "$1" 2>/dev/null)" || true
  case "$info" in
    *Mach-O*) return 0 ;;
    *)        return 1 ;;
  esac
}

# 该 Mach-O 是否「已用目标身份签好、签名有效、且带 Apple 安全时间戳」→ 可安全跳过重签
#   三者缺一不可：公证除了要「签名有效」，还强制要求 secure timestamp，
#   只验 verify 不足以证明它能过公证。
is_already_signed() {
  local f="$1" info
  codesign --verify --strict "$f" >/dev/null 2>&1 || return 1
  info="$(codesign -dv --verbose=2 "$f" 2>&1)" || true
  case "$info" in
    *"Authority=$IDENTITY"*) ;;   # 身份必须一致
    *) return 1 ;;
  esac
  case "$info" in
    *"Timestamp="*) return 0 ;;   # 必须有安全时间戳
    *) return 1 ;;
  esac
}

sign_path() {  # $1=路径  $2=人类可读说明
  local target="$1" label="$2" err
  if err="$(codesign --force --timestamp --options runtime \
               --entitlements "$ENT" --sign "$IDENTITY" "$target" 2>&1)"; then
    echo "  ✔ 重签 $label"
  else
    echo "❌ 签名失败：$target" >&2
    echo "$err" >&2
    exit 1
  fi
}

# 把路径按「字符串长度倒序」输出，用于保证先处理更深的嵌套
by_depth_desc() {
  awk '{ print length($0) "\t" $0 }' | sort -rn | cut -f2-
}

verify_path() {  # $1=路径  $2=说明  $3=附加参数（可选，如 --deep）
  local target="$1" label="$2" extra="${3:-}" err
  # shellcheck disable=SC2086
  if err="$(codesign --verify --strict --verbose=2 $extra "$target" 2>&1)"; then
    echo "  ✔ $label"
    return 0
  else
    echo "  ❌ $label" >&2
    echo "$err" >&2
    return 1
  fi
}

# ---------------------------------------------------------------------------
# 步骤 1/4：确保所有 Mach-O 文件都被「目标身份」签过（已签好的跳过）
# ---------------------------------------------------------------------------
log "步骤 1/4：校验并（必要时）重签所有 Mach-O 文件"
macho_total=0
macho_skipped=0
macho_signed=0
while IFS= read -r f; do
  [ -n "$f" ] || continue
  is_macho "$f" || continue
  macho_total=$((macho_total + 1))
  if is_already_signed "$f"; then
    macho_skipped=$((macho_skipped + 1))
    continue
  fi
  sign_path "$f" "${f#"$APP"/}"
  macho_signed=$((macho_signed + 1))
done < <(find "$APP" -type f -print)
log "  Mach-O 共 $macho_total 个：跳过（已签好）$macho_skipped 个，重签 $macho_signed 个"

# ---------------------------------------------------------------------------
# 步骤 2/4：无条件重签嵌套 bundle（framework / xpc / 内嵌 app），最深优先
# ---------------------------------------------------------------------------
log "步骤 2/4：重签嵌套 bundle（.framework / .xpc / 内嵌 .app，最深优先）"
nested_count=0
while IFS= read -r b; do
  [ -n "$b" ] || continue
  sign_path "$b" "${b#"$APP"/}  [bundle]"
  nested_count=$((nested_count + 1))
done < <(find "$APP" -mindepth 1 -type d \
           \( -name '*.framework' -o -name '*.xpc' -o -name '*.app' \) -print \
         | by_depth_desc)
log "  共重签 $nested_count 个嵌套 bundle"

# ---------------------------------------------------------------------------
# 步骤 3/4：签名最外层 .app（带 entitlements）
# ---------------------------------------------------------------------------
log "步骤 3/4：签名最外层 .app"
sign_path "$APP" "$(basename "$APP")  [app]"

# ---------------------------------------------------------------------------
# 步骤 4/4：全量校验收口
# ---------------------------------------------------------------------------
log "步骤 4/4：全量签名校验（把「公证阶段才暴露的问题」提前到构建阶段）"
verify_fail=0

while IFS= read -r b; do
  [ -n "$b" ] || continue
  verify_path "$b" "${b#"$APP"/}  [bundle]" || verify_fail=1
done < <(find "$APP" -mindepth 1 -type d \
           \( -name '*.framework' -o -name '*.xpc' -o -name '*.app' \) -print \
         | by_depth_desc)

verify_path "$APP/Contents/MacOS/pichome-desktop" "Contents/MacOS/pichome-desktop" || verify_fail=1
SIDECAR_BIN="$APP/Contents/Resources/pichome-server/pichome-server"
if [ -f "$SIDECAR_BIN" ]; then
  verify_path "$SIDECAR_BIN" "Contents/Resources/pichome-server/pichome-server" || verify_fail=1
fi
verify_path "$APP" "$(basename "$APP")  [app / --deep]" "--deep" || verify_fail=1

if [ "$verify_fail" -ne 0 ]; then
  die "存在签名校验不通过的对象（详见上方输出）。这会在公证阶段失败，已提前拦截。"
fi

# ---------------------------------------------------------------------------
# 诊断摘要：framework 的签名形态（应为 Format=bundle 且 Info.plist 已绑定）
# ---------------------------------------------------------------------------
fw_total="$(find "$APP" -mindepth 1 -type d -name '*.framework' -print | wc -l | tr -d ' ')"
if [ "$fw_total" != "0" ]; then
  log "framework 签名形态核对（期望 Format=bundle 且 Info.plist entries 非 0）："
  while IFS= read -r fw; do
    [ -n "$fw" ] || continue
    printf '  %s\n' "${fw#"$APP"/}"
    codesign -dv --verbose=2 "$fw" 2>&1 \
      | grep -E '^(Format|Identifier|Authority|TeamIdentifier)|Info\.plist entries' \
      | sed 's/^/      /' || true
  done < <(find "$APP" -mindepth 1 -type d -name '*.framework' -print)
fi

ok "全部签名校验通过 ✅（${APP}）"
