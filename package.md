# PicHome 桌面端打包（macOS dmg）说明

> 本文档说明 PicHome macOS 桌面端「打包成 `.dmg` 安装包」的技术方案、关键配置、CI 流程与排错方法。
> 适用对象：需要改动打包流程、排查 CI 构建失败、或本地手动出包的开发者。

## 目录

- [1. 技术方案总览](#1-技术方案总览)
- [2. 本地手动出包](#2-本地手动出包)
- [3. CI 双架构构建流程](#3-ci-双架构构建流程)
- [4. 关键配置项](#4-关键配置项)
  - [4.1 `tauri.conf.json`](#41-tauriconfjson)
  - [4.2 `bundle.resources` 映射方向（易踩坑）](#42-bundleresources-映射方向极易踩坑)
  - [4.3 `release.yml`](#43-releaseyml-关键配置)
  - [4.4 Apple 签名所需 Secrets](#44-apple-开发者签名6-个-secrets)
  - [4.5 签名与公证：为什么必须自己接管（核心）](#45-签名与公证为什么必须自己接管核心)
- [5. 后端冻结要点](#5-后端冻结要点)
- [6. 注意事项](#6-注意事项)
- [7. 故障排查速查](#7-故障排查速查)
- [8. 改版本号的完整清单](#8-改版本号的完整清单)

---

## 1. 技术方案总览

PicHome 桌面端是一个 **Tauri v2 壳 + Django 后端（冻结为 sidecar）** 的混合桌面应用：

| 角色 | 技术 | 说明 |
| --- | --- | --- |
| 外壳 / 窗口 / 菜单栏 | **Tauri v2（Rust）** | 提供原生 `.app` 窗口与菜单栏托盘，WebView 直接加载本地后端地址 |
| 后端服务 | **Django + waitress（Python）** | 业务逻辑、图库、图床同步；被 PyInstaller 冻结为单目录可执行文件 |
| 进程间关系 | Tauri `sidecar` | Rust 壳启动时 spawn 后端可执行文件，绑定 `http://127.0.0.1:14567` |
| 前端渲染 | 系统 WebView | 窗口 `url` 指向 `127.0.0.1:14567`，页面完全由 Django 提供（不打包前端产物） |

**为什么这么设计**：不打包任何前端构建产物，运行时页面与服务全部来自本地 Django。
因此 `tauri.conf.json` 的 `frontendDist` 只是一个**构建期占位目录**（见 4.1、第 6 节）。

整体数据流：

```
用户双击 .app
   └─ Rust 壳启动
        ├─ 定位 Resources/pichome-server/pichome-server（冻结后的 Django）
        ├─ spawn 子进程：PICHOME_DESKTOP=1 PICHOME_DESKTOP_PORT=14567
        │     └─ Django + waitress 监听 127.0.0.1:14567（首次启动会 migrate / collectstatic）
        ├─ 轮询 14567 就绪（最多 90s）
        └─ 窗口显示，WebView 加载 http://127.0.0.1:14567
```

> `waitress` 而非 `gunicorn`：`gunicorn` 的 fork worker 在冻结二进制里会 `SIGSEGV`（见第 5 节）。

---

## 2. 本地手动出包

前置：macOS（Apple Silicon 或 Intel）+ Xcode Command Line Tools + `python3` + `node` + Rust 工具链（cargo）。

```bash
# 1) 虚拟环境 + 后端冻结依赖
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt pyinstaller waitress

# 2) 冻结后端 → desktop/src-tauri/bin/pichome-server（onedir，含 _internal/）
bash desktop/build_backend.sh

# 3) 生成前端占位 dist（构建期必须存在，运行时不被加载）
cd desktop && mkdir -p dist && \
  printf '<!doctype html>\n<html lang="zh-CN">\n<head><meta charset="utf-8"><title>PicHome</title></head>\n<body><p>Loading PicHome...</p></body>\n</html>\n' > dist/index.html

# 4) 构建 .app + .dmg
npm install                                   # 安装 @tauri-apps/cli
npm run tauri build -- --bundles app dmg
```

产物：

```
desktop/src-tauri/target/release/bundle/macos/PicHome.app
desktop/src-tauri/target/release/bundle/dmg/PicHome_<版本>_<架构>.dmg
```

> 第 2 步在 `tauri build` 时会被 `beforeBuildCommand` **自动执行一遍**，手动跑一次只是为了
> 提前暴露冻结阶段的问题。想省事可以直接跳到第 3 步。
>
> 第 1 步的 venv 是**后端冻结**用的；日常只调前端/壳代码用 `cd desktop && npm run dev` 即可。

---

## 3. CI 双架构构建流程

配置文件：`.github/workflows/release.yml`

**触发条件**：推送 `v*` 格式的 tag（例如 `git tag v1.0.0 && git push origin v1.0.0`）。

**双架构矩阵**：

| 矩阵项 | Runner | 架构 | 产物名 |
| --- | --- | --- | --- |
| `apple-silicon` | `macos-latest` | arm64 | `PicHome_<版本>_aarch64.dmg` |
| `intel` | `macos-15-intel` | x64 | `PicHome_<版本>_x64.dmg` |

> ⚠️ `macos-13` 已于 **2025-12-04** 被 GitHub 完全退役（actions/runner-images#13046），
> pin 它会让 Intel 腿**直接起不来**。改用官方现役的 x86_64 镜像 `macos-15-intel`。

每个 runner 内部依次执行：

| # | 步骤 | 说明 |
| --- | --- | --- |
| 1 | `actions/checkout@v5` | 拉代码 |
| 2 | `setup-python@v5`（3.12） | 建 `.venv`，装 `requirements.txt` + `pyinstaller` + `waitress` |
| 3 | `Setup macOS keychain` | 导入 Apple 证书到临时 keychain；未配 `APPLE_SIGNING_IDENTITY` 时整段跳过 |
| 4 | `setup-node@v5`（Node 20）+ `setup Rust` | 准备前端与 Rust 工具链 |
| 5 | 生成 `desktop/dist/index.html` 占位 | 构建期必须存在 |
| 6 | `tauri-apps/tauri-action@v0`，`args: '--bundles app'` | **只打 `.app`**，且**只签名不公证**（见 4.5）；`beforeBuildCommand` 会顺带触发 PyInstaller 冻结 |
| 7 | `Deep-sign app bundle` | `desktop/sign_app_bundle.sh`：**先还原 framework 结构，再由内到外重签**，最后全量校验收口 |
| 8 | `Notarize & staple app` | `desktop/notarize.sh` 提交公证并装订 `.app` |
| 9 | `Package dmg via hdiutil` | `hdiutil` 挂载临时镜像 → 加「应用程序」快捷方式 → 压缩为 `UDZO` 的 `.dmg`（headless 安全） |
| 10 | `Notarize & staple dmg` | dmg 也要签名 + 公证 + 装订，否则用户下载后会被 Gatekeeper 拦 |
| 11 | `upload-artifact@v4` | 上传 `src-tauri/target/release/bundle/dmg/*.dmg` |

两个架构都成功后，`release` 任务把两份 dmg 合并进**同一个 draft GitHub Release**
（draft 需到 Releases 页手动点「Publish release」才会公开）：

| 步骤 | 说明 |
| --- | --- |
| `download-artifact@v4`（`path: artifacts`） | 产物落到 `artifacts/<artifact 名>/*.dmg`，即 `artifacts/dmg-apple-silicon/`、`artifacts/dmg-intel/` |
| `gh release create`（draft） | ⚠️ **该 job 没有 `actions/checkout`，工作区不是 git 仓库**，所以每条 `gh` 命令都必须显式带 `--repo "$GITHUB_REPOSITORY"`；否则会报 `failed to run git: fatal: not a git repository`。已做幂等：Release 已存在时改用 `gh release upload --clobber` 补传覆盖 |

> Release 正文会**按是否配置 `APPLE_SIGNING_IDENTITY` 自动切换**：有证书就写「已签名并通过
> Apple 公证」，没有就写「未签名，需右键打开」—— 避免文案与产物实际状态不符。

---

## 4. 关键配置项

### 4.1 `desktop/src-tauri/tauri.conf.json`

| 配置键 | 值 | 作用 |
| --- | --- | --- |
| `productName` | `PicHome` | 决定 `.app` / `.dmg` 名称与窗口标题 |
| `version` | `1.0.0` | **版本号单一来源**，CI 不额外覆盖；改版本需同步 5 个文件，见第 8 节 |
| `identifier` | `com.pichome.desktop` | macOS bundle identifier |
| `build.devUrl` / `app.windows[].url` | `http://127.0.0.1:14567` | 开发与运行时加载的本地后端地址 |
| `build.frontendDist` | `../dist` | 构建期必须存在的占位目录（运行时不被 WebView 加载） |
| `build.beforeBuildCommand` | `bash build_backend.sh` | 构建前**自动跑 PyInstaller 冻结**（本地 / CI 共用，避免复用旧 sidecar） |
| `build.beforeDevCommand` | `""` | dev 模式不额外构建 |
| `bundle.active` | `true` | 开启打包 |
| `bundle.targets` | `["app"]` | 配置层默认 target；本地可用 CLI `--bundles app dmg` 额外产出 dmg |
| `bundle.resources` | `{ "bin/pichome-server": "pichome-server" }` | 见 4.2 |
| `bundle.icon` | 5 个图标路径 | 必须全部存在，否则打包报错 |
| `bundle.macOS.minimumSystemVersion` | `10.15` | 最低支持系统版本 |
| `bundle.macOS.signingIdentity` | `"-"` | **不要写成 `${env.*}`**，原因见 4.5「其它要点」 |

### 4.2 `bundle.resources` 映射方向（极易踩坑）

Tauri v2 的 `resources` 是 **`源路径 → 目标路径`** 的 map（**键 = 源、值 = 目标**），源路径相对于 `src-tauri/`：

```json
"resources": {
  "bin/pichome-server": "pichome-server"
}
```

- **源** `bin/pichome-server` → 磁盘上的 `desktop/src-tauri/bin/pichome-server/`（`build_backend.sh` 的产物；不存在会报 `resource not found` 并退出码 1）。
- **目标** `pichome-server` → 打进 `.app` 后位于 `Contents/Resources/pichome-server/`，正好对齐 `main.rs` 里 `resource_dir().join("pichome-server").join("pichome-server")` 的读取路径。

> 方向写反 → 要么构建期找不到源，要么运行期找不到 sidecar（App 起不来）。当前配置方向正确。

### 4.3 `release.yml` 关键配置

| 配置 | 值 / 说明 |
| --- | --- |
| 触发 | `on.push.tags: ['v*']`（仅打 tag 触发，普通 push 不跑） |
| 矩阵 | `macos-latest`（arm64）+ `macos-15-intel`（x64） |
| `fail-fast` | `false`（一个架构失败不影响另一个） |
| Python | `3.12`，装 `pyinstaller` + `waitress` + `requirements.txt` |
| Node | `20` |
| Rust | `dtolnay/rust-toolchain@stable`（依赖版本由仓库内 `Cargo.lock` 锁定） |
| tauri-action | `tauri-apps/tauri-action@v0`，`args: '--bundles app'`，`includeUpdaterJson: false`；**只传证书与签名身份，不传 `APPLE_ID`/`APPLE_PASSWORD`/`APPLE_TEAM_ID`** → Tauri 跳过内置公证 |
| 深度重签 | `desktop/sign_app_bundle.sh`（还原 framework 结构 + 由内到外重签 + `codesign --verify --strict` 收口） |
| 公证 | `desktop/notarize.sh`（`.app` / `.dmg` 各跑一次）：`notarytool submit --wait` → `stapler staple`，失败自动拉 `notarytool log` |
| dmg 生成 | `hdiutil create` + 挂载加「应用程序」软链 + `UDZO` 压缩；**不写死 `-size`**（CI 的 `Python.framework` 体积远大于本地） |
| 上传 | `upload-artifact@v4`，路径 `src-tauri/target/release/bundle/dmg/*.dmg` |

### 4.4 Apple 开发者签名（6 个 Secrets）

在仓库 `Settings → Secrets and variables → Actions` 配置以下 Secrets 即可自动签名、公证、去 Gatekeeper 拦截。

**未配置时变量为空，tauri-action 自动跳过签名**（只出未签名 dmg），不会因此报错。

| Secret | 含义 |
| --- | --- |
| `APPLE_CERTIFICATE` | 开发者证书（p12 的 base64） |
| `APPLE_CERTIFICATE_PASSWORD` | 证书密码 |
| `APPLE_SIGNING_IDENTITY` | 签名身份，如 `Developer ID Application: xxx (TEAMID)` |
| `APPLE_ID` | Apple ID 账号 |
| `APPLE_PASSWORD` | **App 专用密码**（不是 Apple ID 登录密码） |
| `APPLE_TEAM_ID` | 开发者团队 ID |

### 4.5 签名与公证：为什么必须自己接管（核心）

#### 结论

**不使用 Tauri 的内置公证**，改由两个脚本在 `tauri build` 之后接管：

```
tauri build（只签名，跳过公证）
  └─ desktop/sign_app_bundle.sh    ← 还原 framework 结构 → 由内到外深度重签 → 全量校验收口
     └─ desktop/notarize.sh .app   ← 公证 + 装订
        └─ Package dmg via hdiutil
           └─ desktop/notarize.sh .dmg  ← 签名 + 公证 + 装订
```

**原因**：Tauri 的内置公证跑在 `tauri build` 的**最末一步**，报错时 `.app` 已封好，补救机会为零
（早期版本反复出现 `failed to notarize app: Finished with status Invalid`，而真正的根因
——嵌套 framework 签名形态不对 —— 在那个时刻已无法修补）。

所以 `tauri-action` **只传** `APPLE_CERTIFICATE` / `APPLE_CERTIFICATE_PASSWORD` / `APPLE_SIGNING_IDENTITY`。
Tauri 检测不到公证凭据时会打印 `skipping app notarization...` 并正常成功退出，剩下的事由脚本接管。

#### 公证失败的真正根因：`Python.framework` 在最终 `.app` 里「不是框架」

`notarytool log` 的报错：

```
statusCode 4000  "Archive contains critical validation errors"
path:    PicHome.app/Contents/Resources/pichome-server/_internal/Python.framework/Python
message: "The signature of the binary is invalid."   (arm64)
```

**注意路径是 `Python.framework/Python`（框架根目录），而不是 `Versions/3.12/Python`** ——
这个细节说明 codesign 把根部那个文件当成了框架主二进制，是破案的关键线索。

完整因果链：

1. PyInstaller 只把框架里的二进制按路径搬进产物（`build_main.py::assemble()`），
   即只有 `Python.framework/Versions/3.12/Python`。
2. 负责「补 `Info.plist` + 重建 `Versions/Current` / `<name>` / `Resources` 三个符号链接」的
   `PyInstaller/utils/osx.py::collect_files_from_framework_bundles()` 里有**多处提前 `continue`**，
   命中后产物里就只剩一个「残缺框架」。
3. **Tauri 把 sidecar 拷进 `.app` 时会解引用符号链接** → `Python.framework/Python`
   从「指向 `Versions/Current/Python` 的符号链接」变成**真实文件副本**。
4. 框架不再是版本化布局，codesign 找不到 `Info.plist`：

   ```
   Executable=.../Python.framework/Python
   Identifier=Python            ← 找不到 Info.plist，回退成目录名（正常应为 org.python.python）
   Format=bundle with Mach-O thin (arm64)
   Info.plist=not bound         ← 决定性的一行
   ```

5. Apple 公证无法确认框架主二进制 → 判 `The signature of the binary is invalid.`

**实测对照**（真实 Developer ID + 官方同款 framework Python，本地 1:1 复现）：

| framework 目录形态 | `codesign -dv` | 公证 |
| --- | --- | --- |
| `Versions/3.12/{Python,Resources/Info.plist}` + `Versions/Current` | `Identifier=org.python.python`、`Info.plist entries=12` | ✅ |
| 只有 `Versions/3.12/Python`（无 Info.plist、无 Current） | codesign **直接拒绝**：`bundle format unrecognized, invalid, or unsuitable` | ❌ |
| 根目录有**真实** `Python` 文件、无 Info.plist（= Tauri 解引用后的最终形态） | `Identifier=Python`、`Info.plist=not bound` | ❌ ← **CI 的实际形态** |

> ⚠️ **关键结论：问题不是「没签名」，也不是「签的位置不对」，而是「框架本身缺零件」。**
> 因此「在 bincache 里补签」「对 `Versions/3.12/Python` 再 `codesign` 一次」全都无效 ——
> 必须**先把框架结构还原成 Apple 规范形态**，再按 bundle 形态签。

#### 两个常见困惑

- **Tauri 为什么不管？** `tauri-bundler` 的 `add_nested_code_sign_path()` 只扫描
  `NESTED_CODE_FOLDER` 的**一层**（`min_depth(1).max_depth(1)`），够不到
  `Contents/Resources/pichome-server/_internal/Python.framework` 这种深层嵌套。
- **为什么本地复现不了？** 若本地 Python 是 pyenv / Homebrew 的**非 framework 构建**，
  PyInstaller 收的是单个 `libpython3.14.dylib`，`_internal/` 里根本没有 `Python.framework`。
  CI 用 `actions/setup-python` 的 3.12 是 **framework 构建**，才会出现该目录。

#### `sign_app_bundle.sh`：先还原结构，再由内到外签名

| 顺序 | 对象 | 说明 |
| --- | --- | --- |
| ⓪ | **还原 `.framework` 目录结构** | **核心修复点**。缺 `Info.plist` 就补（优先从 `/Library/Frameworks/<同名>.framework/.../Info.plist` 复制，找不到则合成最小 plist）；`Versions/Current`、根目录 `Resources`、根目录 `<name>` 三个符号链接缺失就补建；被解引用成真实目录 / 硬拷贝的**还原为符号链接**（真实目录内容先合并，避免丢文件） |
| ① | 所有 Mach-O 文件（`_internal/**/*.so`、`*.dylib`、可执行文件） | 已用目标身份正确签好的**跳过**（CI 上 PyInstaller 已签过，避免数百次 Apple 时间戳请求） |
| ② | 所有嵌套 bundle（`.framework` / `.xpc` / 内嵌 `.app`），最深优先，**无条件 `--force` 重签** | ⓪ 之后框架已是规范形态，`codesign --force <framework>` 即可签出 `Format=bundle` + `Info.plist entries=N` |
| ③ | 最外层 `.app`（带 `entitlements.plist`） | |
| ④ | 全量 `codesign --verify --strict` 收口 | 任一失败立即打印文件路径并 `exit 1` |
| ⑤ | **framework 形态硬校验** | `codesign -dv` 必须出现非 0 的 `Info.plist entries=`，否则打印完整目录结构快照并 `exit 1` —— 把问题从「公证阶段」提前到「构建阶段」，不再白跑一次公证 |

> 顺序不能反：若先签 bundle 再动内部文件，bundle 的 `_CodeSignature` 记录会失效。

本地无证书（`APPLE_SIGNING_IDENTITY` 为空且 keychain 里没有 `Developer ID Application`）时，
脚本自动跳过，`npm run build` 行为不变。

#### `notarize.sh`

- 传 `.app` → 先 `ditto -c -k --keepParent` 打成 zip（公证要求的容器格式）
- 传 `.dmg` → **先 `codesign` 签名**：未签名 dmg 提交公证容易被拒，且 `stapler` 要求目标已签名
- `xcrun notarytool submit … --wait --output-format json`；未通过时自动跑 `notarytool log <id>`，
  把每个出问题的文件路径与原因打出来
- 通过后 `xcrun stapler staple` + `stapler validate` 装订
- 未配置 `APPLE_ID` / `APPLE_PASSWORD` / `APPLE_TEAM_ID` 时直接跳过（本地不阻塞构建）

#### 其它要点

1. `desktop/build.spec` 的 `EXE` 设置了
   `codesign_identity=os.environ.get("APPLE_SIGNING_IDENTITY") or None` 与 `entitlements_file`。
   PyInstaller 自带的 codesign 会正确处理 `_internal/` 下的符号链接（只签真实文件）。
   **注意：这一层签名保不住 `Python.framework`（原因见上），最终仍靠 `sign_app_bundle.sh` 收口。**
2. `desktop/build_backend.sh` **不做补签**：脚本里不引用任何 codesign 变量，保证 `set -u` 下不会因变量未定义而退出。
3. `release.yml` 把「导入 Apple 证书到临时 keychain」放在冻结之前：`beforeBuildCommand` 触发的
   PyInstaller 冻结需要证书；该 keychain 在整个 job 内保持解锁，供后续签名步骤复用。
4. `tauri.conf.json` 的 `bundle.macOS`：`signingIdentity: "-"` 与 `entitlements: "../entitlements.plist"`。

   > ⚠️ **不要写 `"${env.APPLE_SIGNING_IDENTITY}"`**：Tauri 的配置文件**不做 `${env.*}` 插值**，
   > 这串字符会被原样交给 codesign，本地构建必然失败：
   > `${env.APPLE_SIGNING_IDENTITY}: no identity found` →
   > `failed to bundle project: failed codesign application: failed to run command codesign: failed to sign app`。
   > 需要「按环境切换身份」时用环境变量或 `--config` 覆盖，别在 json 里写插值。

   **签名身份的来源与优先级**（`crates/tauri-cli/src/interface/rust.rs`：
   `signing_identity = match env::var_os("APPLE_SIGNING_IDENTITY") { Some(v) => …, None => config.macos.signing_identity }`）：

   | 场景 | 身份来源 | 结果 |
   | --- | --- | --- |
   | 本地 `npm run build`（未设环境变量） | 配置里的 `-` | ad-hoc 签名，构建通过、本机可直接运行 |
   | 本地想用真证书 | `APPLE_SIGNING_IDENTITY="Developer ID Application: xxx (TEAMID)" npm run build` | 环境变量覆盖配置，走正式签名 |
   | CI 配了 Secrets | tauri-action 注入的 `APPLE_SIGNING_IDENTITY` | 覆盖配置，正式签名（公证由 `notarize.sh` 接手） |
   | CI 未配 Secrets | 配置里的 `-` | ad-hoc（注意下方「空字符串陷阱」） |

   > **空字符串陷阱**：`tauri-bundler` 用 `var_os()` 判断，**空字符串也算「已设置」**。
   > 所以 `env: APPLE_CERTIFICATE: ${{ secrets.X }}` 在 Secret 未配置时会传入 `""`，
   > 触发 `Keychain::with_certificate("")` → `security import` 失败。
   > 正确做法是只在非空时写入 `$GITHUB_ENV`，别把可能为空的 Secret 直接挂在 `env:` 上。

> 本地未配置证书时：`build.spec` 的 `codesign_identity` 为 `None`，PyInstaller 仍会对 sidecar 做
> **ad-hoc 签名**（`codesign -dv` 可见 `flags=0x2(adhoc)`，`codesign --verify` 通过），
> 配合配置里的 `-`，Tauri 对 `.app` 也做 ad-hoc 签名 → 本机可直接运行调试。

---

## 5. 后端冻结要点

对应文件：`desktop/build.spec` + `desktop/build_backend.sh`

- **PyInstaller onedir 模式**：入口 `run_server.py`，产物目录 `desktop/src-tauri/bin/pichome-server/`，
  内含可执行 `pichome-server` 与 `_internal/`。
- **`target_arch=None`**：PyInstaller 按**当前机器架构**原生编译。双架构能分别出包，正是因为
  两个 runner 架构不同、各自冻结一次。
- **静态收集**：Django 模块须在 `django.setup()` 之后用 `collect_submodules` 收集，
  否则会因 `Apps aren't loaded yet` 被静默跳过。
- **`waitress` 而非 `gunicorn`**：`gunicorn` 的 fork worker 在冻结二进制里会 `SIGSEGV`；
  `run_server.py` 用纯 Python 的 `waitress` 托管 WSGI。
- **数据目录**：可写资源（SQLite、上传文件）落在 `~/Library/Application Support/pichome`，
  由 `settings.py` 的桌面模式（`PICHOME_DESKTOP=1`）接管。
- **`build_backend.sh` 先冻到临时目录再 `cp` 合并**：避免 PyInstaller 在 `COLLECT` 阶段
  递归删除已存在的 `bin/pichome-server` 引发沙箱拦截。

---

## 6. 注意事项

1. **`build_backend.sh` 必须在 `tauri build` 之前跑**：否则 `src-tauri/bin/pichome-server` 不存在，
   `resources` 源缺失，`tauri build` 直接退出码 1。（CI 里由 `beforeBuildCommand` 自动完成。）
2. **`frontendDist` 占位必须有**：CI 显式 `mkdir -p dist` 并写 `index.html`；本地出包同样需要先建 `dist/`。
3. **`resources` 键 = 源、值 = 目标**：方向写反会导致构建失败或 App 起不来（见 4.2）。
4. **`Cargo.lock` 需提交**：保证 Rust 依赖版本在 CI 与本地一致；不要随意 `cargo update` 破坏锁定。
5. **`.app` 与 `.dmg` 分开产出**：CI 里 Tauri **只打 `.app`**（`--bundles app`），`.dmg` 由后续
   `hdiutil` 步骤生成，artifact 只取 `bundle/dmg/*.dmg`。
6. **不要用 Tauri 内置 dmg（create-dmg）**：它的 `dmg` target 最后会用 `osascript` 调 Finder 做窗口美化，
   **在无图形会话的 CI runner 上会卡死 / 报错**，导致 `tauri build` 退出码 1 失败。
   这是项目早期 CI 报错的根因，务必用第 9 步的 `hdiutil` 手动方案替代。
7. **`hdiutil` 不要写死 `-size`**：CI 的 sidecar 内嵌完整 `Python.framework`（含 stdlib），体积远大于本地构建，
   写死 `-size 400m` 会 `no space left`，交给 `hdiutil create` 自动计算。
8. **`hdiutil attach` 输出别用 `| sed 1q` / `| head -1` 解析**：在 `set -o pipefail` 下这些命令读完一行就退出，
   会让上游命令收到 SIGPIPE（141），整条管道被判为失败。改为先落盘再用 `awk` 解析。
9. **`minimumSystemVersion` 与 runner 系统版本**：CI 用较新 macOS 构建，部署目标设为 `10.15` 向下兼容。
10. **`includeUpdaterJson: false`**：明确关闭 Tauri 更新器 artifact 生成，避免 release 阶段与 release 任务
    抢着建 GitHub Release 导致 API 冲突。
11. **公证失败的头号原因是「`Python.framework` 在最终 `.app` 里不是框架」**（而不是「没签名」或
    「签的位置不对」）：必须先由 `sign_app_bundle.sh` **还原框架结构**再签，详见 4.5。
12. **`.app` / `.dmg` 都已签名 + 公证 + 装订**后，用户从浏览器下载可直接打开；未配置 Secrets 时产物未签名，
    需右键 → 打开。

---

## 7. 故障排查速查

| 现象 | 可能原因 | 排查 / 解决 |
| --- | --- | --- |
| `tauri build` 退出码 1，报 `failed to run bundle_dmg.sh` | Tauri 内置 dmg 最后用 `osascript` 调 Finder 美化，headless 下卡死 | 见第 6 节第 6 条：CI 只用 `--bundles app`，dmg 改由 `hdiutil` 手动生成 |
| `tauri build` 退出码 1，报 `resource not found` | `build_backend.sh` 未产出 `src-tauri/bin/pichome-server` | 检查 PyInstaller 是否正确执行、`requirements.txt` 是否装全 |
| `npm run tauri build` 找不到命令 | `package.json` 缺 `scripts.tauri` | 确认 `"tauri": "tauri"` 存在 |
| 打包成功但 App 启动报「未找到 pichome-server sidecar」 | `resources` 映射目标路径与 `main.rs` 不一致 | 核对目标是否为 `pichome-server`（对齐 `Resources/pichome-server/...`） |
| `tauri build` 退出码 1，报 `failed codesign application … no identity found` | `tauri.conf.json` 里写了 `${env.APPLE_SIGNING_IDENTITY}` —— Tauri 配置文件**不做插值** | 见 4.5「其它要点 3」：`signingIdentity` 写 `"-"`，身份靠环境变量覆盖 |
| `notarytool` 返回 `Invalid`，issue 指向 `…/_internal/Python.framework/…` 的 `The signature of the binary is invalid.` | framework 结构残缺（缺 `Info.plist` / 符号链接被解引用）→ 签出 `Info.plist=not bound` | 见 4.5：`sign_app_bundle.sh` 的步骤 ⓪ 先还原结构再重签；步骤 ⑤ 会提前拦截 |
| `notarytool` 认证失败（`401` / `Invalid credentials`） | `APPLE_PASSWORD` 不是 **App 专用密码** | 到 Apple ID 后台生成 App 专用密码并更新 Secret |
| Intel 腿 job 起不来 / runner 标签不可用 | `macos-13` 已于 2025-12-04 退役 | 见第 3 节：改用 `macos-15-intel` |
| `Create Release (both archs)` 报 `failed to run git: fatal: not a git repository (or any of the parent directories): .git` | `release` job 没有 `actions/checkout`，工作区不是 git 仓库，而 `gh` 默认要调 `git` 推断仓库 | 给所有 `gh` 命令加 `--repo "$GITHUB_REPOSITORY"`（或在该 job 里加 `actions/checkout`）。**两个 build 步骤此前已全绿，说明签名/公证链路是通的**，只差这一步 |
| 打开 dmg 报「无法验证开发者」 | 未配置签名 Secrets（未走公证流程） | 属预期；配置 4.4 的 Secrets，或右键 → 打开 |
| 后端起不来 / 白屏 | `frontendDist` 占位缺失，或 14567 端口被残留进程占用 | 确认 `dist/index.html` 存在；`lsof -i:14567` 查残留进程 |

---

## 8. 改版本号的完整清单

`tauri.conf.json` 的 `version` 是 CI 的**唯一版本来源**（CI 不额外覆盖），但仓库里还有几处必须同步，
否则本地构建 / dmg 名称会不一致：

| 文件 | 位置 |
| --- | --- |
| `desktop/src-tauri/tauri.conf.json` | `"version": "x.y.z"` ← **唯一来源** |
| `desktop/package.json` | `"version": "x.y.z"` |
| `desktop/src-tauri/Cargo.toml` | `[package]` 段的 `version` |
| `desktop/src-tauri/Cargo.lock` | `name = "pichome-desktop"` 条目下的 `version` |
| `desktop/package-lock.json` | 顶层的 `"version"` 与 `packages.""` 下的 `"version"`（共 2 处） |

改完后：

```bash
cd desktop/src-tauri && cargo check        # 确认 Cargo.lock 与 Cargo.toml 一致
cd ../.. && git tag vx.y.z && git push origin vx.y.z   # 推送 tag 触发 CI 出包
```
