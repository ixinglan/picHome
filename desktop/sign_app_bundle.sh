#!/usr/bin/env bash
# =============================================================================
# PicHome —— 对最终 .app 执行「框架结构还原 → 由内到外深度签名 → 全量校验收口」
#
# 【为什么需要这个脚本】
#   问题根因（已按 PyInstaller 源码逐行核实）：
#
#   1) Tauri 的嵌套签名（tauri-bundler 的 add_nested_code_sign_path）只扫一层目录，
#      够不到 sidecar 里深层嵌套的 `_internal/Python.framework`，所以我们必须在
#      Tauri 之后自己把整个 .app 重签一遍。
#
#   2) 更关键的坑在 PyInstaller 侧。`PyInstaller/building/build_main.py` 的
#      `assemble()` 只把 Python 框架里的那个二进制按路径搬进产物：
#          src  = /Library/Frameworks/Python.framework/Versions/3.12/Python
#          dest = Python.framework/Versions/3.12/Python
#      随后由 `PyInstaller/utils/osx.py::collect_files_from_framework_bundles()`
#      负责「补 Info.plist + 重建 Versions/Current、<name>、Resources 三个符号链接」。
#      但该函数有多个提前 `continue` 的分支（源路径不满足 framework 版本化布局 /
#      找不到 Info.plist 等）。一旦走进去，产物里就只剩：
#          Python.framework/Versions/3.12/Python     ← 一个"残缺框架"
#      codesign 在这种框架上找不到 Info.plist，只能退化成「按目录名签名」：
#          Identifier=Python          （正常应为 org.python.python）
#          且没有 `Info.plist entries=` 这一行
#      Apple 公证时无法确认框架主二进制，直接判：
#          "The signature of the binary is invalid."
#          path: .../Python.framework/Python
#      —— 这正是 v0.1.x ~ v1.0.0 反复失败的真正原因。只"重签框架"是治不好的：
#         框架本身就缺零件，怎么签都不对。
#
#   因此本脚本在签名之前新增「步骤 0」：把每个 .framework 还原成 Apple 规范形态
#   （版本目录 + Current 符号链接 + 顶层 Resources / <name> 符号链接 + Info.plist），
#   再按由内到外的顺序签名。最后用「硬校验」确认 framework 签名确实绑定了
#   Info.plist —— 把问题从「公证阶段」提前到「构建阶段」。
#
# 【签名顺序：必须由内到外】
#   0) 还原 framework 目录结构（缺 Info.plist / 缺符号链接 / 被解引用成硬拷贝）
#   1) 所有 Mach-O 文件（framework 内的二进制 / dylib / 可执行）
#      —— 已用「目标身份」正确签好的直接跳过（CI 上 PyInstaller 已签过绝大多数，
#         逐个重签会触发数百次 Apple 时间戳请求，任一次网络抖动都会让流水线失败）
#   2) 所有嵌套 bundle（.framework / .xpc / 内嵌 .app），最深优先，**无条件 --force 重签**
#      —— `codesign --force <framework>` 会把框架主二进制按「bundle 主二进制」形态重签
#         （绑住 Info.plist），这是「扁平签名」缺的那一步。
#      顺序不能反：若先签 bundle 再改内部文件，bundle 的 _CodeSignature 记录会失效
#      （"code has no resources but signature indicates they must be present"）。
#   3) 最外层 .app（带 entitlements）
#   4) 全量 codesign --verify --strict 收口
#   5) framework 形态硬校验：签名必须绑定 Info.plist，否则直接失败并打印完整结构
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
    | sed -n 's/.*"\(Developer ID Application: .*\)"/\1/p' | head -1 || true)"
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

# 列出所有 .framework（真实目录；符号链接不会被 follow）
list_frameworks() {
  find "$APP" -mindepth 1 -type d -name '*.framework' -print
}

# 打印 framework 的目录结构（诊断用：把 CI 上「看不见的产物状态」打到日志里）
dump_framework() {  # $1=framework 绝对路径
  local fw="$1" d
  echo "      --- 结构快照 ---"
  ls -la "$fw" 2>&1 | sed 's/^/        /'
  if [ -d "$fw/Versions" ]; then
    ls -la "$fw/Versions" 2>&1 | sed 's/^/        /'
    for d in "$fw"/Versions/*/; do
      [ -d "$d" ] || continue
      [ "$(basename "$d")" = "Current" ] && continue   # 避免把符号链接再列一遍
      echo "        [$d]"
      ls -la "$d" 2>&1 | sed 's/^/          /'
    done
  fi
}

# 合成一个最小可用的 framework Info.plist（系统里找不到同名框架可拷贝时的兜底）
synth_info_plist() {  # $1=framework 名（不含 .framework）  $2=版本号
  local n="$1" v="$2" ident="com.pichome.embedded.${1}"
  case "$n" in
    Python)  ident="org.python.python" ;;
    Python3) ident="org.python.python3" ;;
  esac
  cat <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleIdentifier</key><string>${ident}</string>
  <key>CFBundleName</key><string>${n}</string>
  <key>CFBundleExecutable</key><string>${n}</string>
  <key>CFBundlePackageType</key><string>FMWK</string>
  <key>CFBundleVersion</key><string>${v}</string>
  <key>CFBundleShortVersionString</key><string>${v}</string>
</dict>
</plist>
PLIST
}

# ---------------------------------------------------------------------------
# 步骤 0/5：把 .framework 还原成 Apple 规范形态
#   PyInstaller / Tauri 的拷贝可能让框架丢掉 Info.plist 或把符号链接解引用成硬拷贝，
#   这会让 codesign 签出「没绑 Info.plist 的 bundle 签名」→ 公证必挂。
#   这里把它修回 python.org 官方 framework 的标准布局：
#     F.framework/
#       F            -> Versions/Current/F          (符号链接)
#       Resources    -> Versions/Current/Resources  (符号链接)
#       Versions/
#         Current    -> <ver>                       (符号链接)
#         <ver>/
#           F                                        (真身 Mach-O)
#           Resources/Info.plist                     (真身 plist)
# ---------------------------------------------------------------------------
# >>> normalize-framework
normalize_framework() {
  local fw="$1"
  local name; name="$(basename "$fw")"; name="${name%.framework}"
  local vdir="$fw/Versions"
  local cur="$vdir/Current"
  local ver="" entry

  # --- 1) 解析当前版本号 ---
  if [ -L "$cur" ]; then
    ver="$(readlink "$cur")"
  fi
  if [ -z "$ver" ] || [ ! -d "$vdir/$ver" ]; then
    ver=""
    for entry in "$vdir"/*; do
      [ -d "$entry" ] || continue
      [ "$(basename "$entry")" = "Current" ] && continue
      ver="$(basename "$entry")"
      break
    done
  fi
  if [ -z "$ver" ]; then
    echo "  · ${name}.framework：非版本化布局，跳过结构还原"
    return 0
  fi

  local vr="$vdir/$ver"
  local top="$fw/$name"
  local res="$fw/Resources"
  local plist="$vr/Resources/Info.plist"
  local changed=""

  echo "  · ${name}.framework  当前版本=${ver}"

  # --- 2) 主二进制必须落在 Versions/<ver>/<name> ---
  if [ ! -e "$vr/$name" ] && [ -f "$top" ] && [ ! -L "$top" ]; then
    mv -f "$top" "$vr/$name"
    echo "      ↑ 顶层 ${name} 真身文件已归位到 Versions/${ver}/"
    changed="1"
  fi

  # --- 3) Versions/Current 必须是符号链接 -> <ver> ---
  if [ -L "$cur" ]; then
    if [ ! -e "$cur" ]; then
      rm -f "$cur"; ln -s "$ver" "$cur"
      echo "      ↑ 修复悬空的 Versions/Current"
      changed="1"
    fi
  elif [ -d "$cur" ]; then
    if [ -e "$vr/$name" ]; then
      rsync -a "$cur/" "$vr/" >/dev/null 2>&1 || true
      rm -rf "$cur"
      ln -s "$ver" "$cur"
      echo "      ↑ Versions/Current 被解引用成真实目录，已还原为符号链接"
      changed="1"
    else
      warn "      ⚠️ Versions/Current 是真实目录且 Versions/${ver}/${name} 缺失，跳过修复"
    fi
  else
    ln -s "$ver" "$cur"
    echo "      ↑ 补建 Versions/Current -> ${ver}"
    changed="1"
  fi

  # --- 4) 顶层 Resources 必须是符号链接 -> Versions/Current/Resources ---
  if [ -L "$res" ]; then
    if [ ! -e "$res" ]; then
      rm -f "$res"; ln -s "Versions/Current/Resources" "$res"
      echo "      ↑ 修复悬空的 Resources 符号链接"
      changed="1"
    fi
  elif [ -d "$res" ]; then
    mkdir -p "$vr/Resources"
    rsync -a "$res/" "$vr/Resources/" >/dev/null 2>&1 || true
    rm -rf "$res"
    ln -s "Versions/Current/Resources" "$res"
    echo "      ↑ 顶层 Resources 被解引用成真实目录，内容已并入 Versions/${ver}/Resources 并还原为符号链接"
    changed="1"
  else
    mkdir -p "$vr/Resources"
    ln -s "Versions/Current/Resources" "$res"
    echo "      ↑ 补建 Resources -> Versions/Current/Resources"
    changed="1"
  fi

  # --- 5) 顶层 <name> 必须是符号链接 -> Versions/Current/<name> ---
  if [ -L "$top" ]; then
    if [ ! -e "$top" ]; then
      rm -f "$top"; ln -s "Versions/Current/$name" "$top"
      echo "      ↑ 修复悬空的 ${name} 符号链接"
      changed="1"
    fi
  elif [ -f "$top" ]; then
    rm -f "$top"
    ln -s "Versions/Current/$name" "$top"
    echo "      ↑ 顶层 ${name} 是硬拷贝，已还原为符号链接（避免 Apple 校验到未随框架包签名的副本）"
    changed="1"
  elif [ -e "$vr/$name" ]; then
    ln -s "Versions/Current/$name" "$top"
    echo "      ↑ 补建 ${name} -> Versions/Current/${name}"
    changed="1"
  fi

  # --- 6) Info.plist 必须存在于 Versions/<ver>/Resources/ ---
  mkdir -p "$vr/Resources"
  if [ ! -f "$plist" ]; then
    local sys_plist="" cand
    for cand in \
      "/Library/Frameworks/${name}.framework/Versions/${ver}/Resources/Info.plist" \
      "/Library/Frameworks/${name}.framework/Resources/Info.plist" \
      "/Applications/Xcode.app/Contents/Developer/Library/Frameworks/${name}.framework/Versions/${ver}/Resources/Info.plist"
    do
      if [ -f "$cand" ]; then sys_plist="$cand"; break; fi
    done
    if [ -z "$sys_plist" ]; then
      sys_plist="$(find /Library/Frameworks -maxdepth 5 -type f -name Info.plist \
                     -path "*${name}.framework*" 2>/dev/null | head -1 || true)"
    fi
    if [ -n "$sys_plist" ] && [ -f "$sys_plist" ]; then
      cp -f "$sys_plist" "$plist"
      echo "      ↑ 缺失 Info.plist：已从系统框架复制（${sys_plist}）"
    else
      synth_info_plist "$name" "$ver" > "$plist"
      echo "      ↑ 缺失 Info.plist：已合成最小 Info.plist（系统中未找到同名框架）"
    fi
    changed="1"
  fi

  if [ -n "$changed" ]; then
    dump_framework "$fw"
  fi
  return 0
}
# <<< normalize-framework

log "步骤 0/5：还原 .framework 目录结构（补 Info.plist / 重建符号链接）"
fw_seen=0
while IFS= read -r fw; do
  [ -n "$fw" ] || continue
  # 安全护栏：只处理目标 .app 内部的路径
  case "$fw" in
    "$APP"/*) : ;;
    *) die "拒绝处理 app 之外的路径：$fw" ;;
  esac
  normalize_framework "$fw"
  fw_seen=$((fw_seen + 1))
done < <(list_frameworks)
log "  共检查 $fw_seen 个 .framework"

# ---------------------------------------------------------------------------
# 步骤 1/5：确保所有 Mach-O 文件都被「目标身份」签过（已签好的跳过）
# ---------------------------------------------------------------------------
log "步骤 1/5：校验并（必要时）重签所有 Mach-O 文件"
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
# 步骤 2/5：无条件重签嵌套 bundle（framework / xpc / 内嵌 app），最深优先
# ---------------------------------------------------------------------------
log "步骤 2/5：重签嵌套 bundle（.framework / .xpc / 内嵌 .app，最深优先）"
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
# 步骤 3/5：签名最外层 .app（带 entitlements）
# ---------------------------------------------------------------------------
log "步骤 3/5：签名最外层 .app"
sign_path "$APP" "$(basename "$APP")  [app]"

# ---------------------------------------------------------------------------
# 步骤 4/5：全量校验收口
# ---------------------------------------------------------------------------
log "步骤 4/5：全量签名校验（把「公证阶段才暴露的问题」提前到构建阶段）"
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
# 步骤 5/5：framework 形态硬校验
#   Apple 公证要求 framework 的签名必须是「bundle 形态且绑定 Info.plist」。
#   判据：`codesign -dv --verbose=2` 必须出现 `Info.plist entries=` 且 Identifier
#   不能退化成框架目录名（退化成目录名 = codesign 没找到 Info.plist）。
#   这一条若不过，公证 100% 会以
#   "The signature of the binary is invalid."（path: <fw>/<name>）失败。
# ---------------------------------------------------------------------------
log "步骤 5/5：framework 签名形态硬校验（必须绑定 Info.plist）"
fw_bad=0
while IFS= read -r fw; do
  [ -n "$fw" ] || continue
  name="$(basename "$fw")"; name="${name%.framework}"
  dv="$(codesign -dv --verbose=2 "$fw" 2>&1 || true)"
  entries=""
  case "$dv" in
    *"Info.plist entries="*)
      entries="$(printf '%s\n' "$dv" | sed -n 's/^Info\.plist entries=\([0-9]*\).*/\1/p' | head -1 || true)"
      ;;
  esac
  printf '  %s\n' "${fw#"$APP"/}"
  # 注意用 -E（BSD sed 的 BRE 不支持 \| 交替）
  printf '%s\n' "$dv" | sed -nE 's/^(Identifier|Format|Executable|TeamIdentifier)=/      \1=/p'
  if [ -z "$entries" ] || [ "$entries" = "0" ]; then
    echo "      ❌ 签名未绑定 Info.plist（Identifier 已退化为目录名）——公证必挂" >&2
    dump_framework "$fw" >&2
    fw_bad=1
  else
    echo "      ✔ Info.plist entries=${entries}"
  fi
done < <(list_frameworks)

if [ "$fw_bad" -ne 0 ]; then
  die "存在未绑定 Info.plist 的 framework（详见上方结构快照）。已提前拦截，避免白跑一次公证。"
fi

ok "全部签名校验通过 ✅（${APP}）"
