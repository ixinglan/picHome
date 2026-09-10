# PicHome 桌面端打包（macOS dmg）说明

> 本文档说明 PicHome macOS 桌面端「打包成 `.dmg` 安装包」使用的技术、整体方案、关键配置项与注意事项。
> 适用对象：需要改动打包流程、排查 CI 构建失败、或本地手动出包的开发者。

---

## 1. 技术方案总览

PicHome 桌面端是一个 **Tauri v2 壳 + Django 后端（冻结为 sidecar）** 的混合桌面应用：

| 角色 | 技术 | 说明 |
| --- | --- | --- |
| 外壳 / 窗口 / 菜单栏 | **Tauri v2（Rust）** | 提供原生 `.app` 窗口、菜单栏托盘图标，WebView 直接加载本地后端地址 |
| 后端服务 | **Django + waitress（Python）** | 实际业务逻辑、图库、图床同步等，被 PyInstaller 冻结为单目录可执行文件 |
| 进程间关系 | Tauri `sidecar` | Rust 壳在启动时 spawn 后端可执行文件，绑定 `http://127.0.0.1:14567` |
| 前端渲染 | 系统 WebView | 窗口 `url` 指向 `http://127.0.0.1:14567`，由 Django 提供页面（非打包静态资源） |

**为什么这么设计**：WebView 不打包任何前端构建产物，运行时完全由本地 Django 提供页面与服务，
因此 `tauri.conf.json` 的 `frontendDist` 仅作为构建期占位目录（详见第 4、6 节）。

整体数据流：

```
用户双击 .app
   └─ Rust 壳启动
        ├─ 定位 Resources/pichome-server/pichome-server（冻结的 Django）
        ├─ spawn 子进程：PICHOME_DESKTOP=1 PICHOME_DESKTOP_PORT=14567
        │     └─ Django + waitress 监听 127.0.0.1:14567（首次启动 migrate/collectstatic）
        ├─ 轮询 14567 就绪（最多 90s）
        └─ 窗口显示，WebView 加载 http://127.0.0.1:14567
```

---

## 2. 本地手动出包流程

在 macOS（Apple Silicon 或 Intel，需装有 Xcode Command Line Tools）上：

```bash
# 0) 前置：本机需要有 python3、node、Rust 工具链（cargo）
# 1) 创建虚拟环境并安装后端冻结依赖
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt pyinstaller waitress

# 2) 冻结后端 -> desktop/src-tauri/bin/pichome-server（onedir，含 _internal/）
bash desktop/build_backend.sh

# 3) 生成前端占位 dist（Tauri 构建期必须存在，但运行时不被加载）
cd desktop && mkdir -p dist && \
  printf '<!doctype html><html><head><meta charset="utf-8"></head><body>Loading PicHome...</body></html>' > dist/index.html

# 4) 构建 .app + .dmg（在 desktop/ 目录执行）
npm install            # 安装 @tauri-apps/cli
npm run tauri build -- --bundles app dmg

# 产物：
#   desktop/src-tauri/target/release/bundle/app/PicHome.app
#   desktop/src-tauri/target/release/bundle/dmg/PicHome.dmg
```

> 说明：第 3 步的 `dist/index.html` 是占位页。运行时 WebView 走的是 Django 的 14567 端口，
> 这个占位文件只是为了让 `tauri build` 在「嵌入前端资源」阶段不报错。

---

## 3. CI 双架构构建流程（GitHub Actions）

配置文件：`.github/workflows/release.yml`

**触发条件**：推送 `v*` 格式的 tag 到 `main`（例如 `git tag v1.0.0 && git push origin v1.0.0`）。

**双架构矩阵**：

| 矩阵项 | Runner | 架构 | 产物 |
| --- | --- | --- | --- |
| `apple-silicon` | `macos-latest` | arm64 | `dmg-apple-silicon` |
| `intel` | `macos-15-intel` | x64 | `dmg-intel` |

> ⚠️ `macos-13` 已于 **2025-12-04** 被 GitHub 完全退役（actions/runner-images#13046），
> pin 它会让 Intel 腿**直接起不来**。改用官方最后一个 x86_64 镜像 `macos-15-intel`。

每个 runner 内部依次执行：

1. `actions/checkout@v5`
2. `setup-python@v5`（3.12）→ 建 `.venv`、装 `requirements.txt` + `pyinstaller` + `waitress`
3. `Setup macOS keychain`：把 Apple 证书导入临时 keychain（未配 `APPLE_SIGNING_IDENTITY` 时整段跳过）
4. `setup-node@v5`（Node 20）→ `npm install`
5. 生成 `desktop/dist/index.html` 占位
6. `tauri-apps/tauri-action@v0`，`args: '--bundles app'`（**只打 `.app`**；dmg 不走 Tauri 内置 create-dmg），`includeUpdaterJson: false`
   - `beforeBuildCommand`（`bash build_backend.sh`）会**自动触发 PyInstaller 冻结**，产出 `src-tauri/bin/pichome-server`
   - **故意不传 `APPLE_ID` / `APPLE_PASSWORD` / `APPLE_TEAM_ID`** → Tauri 跳过内置公证，只签名（原因见 4.5）
7. `Deep-sign app bundle`：`desktop/sign_app_bundle.sh` 对最终 `.app` **由内到外重签** + 全量校验收口（见 4.5）
8. `Notarize & staple app`：`desktop/notarize.sh` 提交公证并装订 `.app`
9. `Package dmg via hdiutil`：`hdiutil create` 挂载临时镜像、加「应用程序」快捷方式、再压缩产出 `.dmg`（完全 headless，见第 6 节）
10. `Notarize & staple dmg`：对 dmg 签名 + 公证 + 装订（否则用户下载 dmg 后会被 Gatekeeper 拦）
11. `upload-artifact@v4` 上传 `src-tauri/target/release/bundle/dmg/*.dmg`

两个架构都成功后，`release` 任务会把两份 dmg 合并进同一个 **draft** GitHub Release。

---

## 4. 关键配置项

### 4.1 `desktop/src-tauri/tauri.conf.json`

| 配置键 | 值 | 作用 |
| --- | --- | --- |
| `productName` | `PicHome` | 决定 `.app` / `.dmg` 文件名与窗口标题 |
| `version` | `1.0.0` | **版本号单一来源**，CI 不额外覆盖；改版本时需同步 `desktop/package.json`、`src-tauri/Cargo.toml` 及两个 lock 文件 |
| `identifier` | `com.pichome.desktop` | macOS bundle identifier |
| `build.devUrl` / `app.windows[].url` | `http://127.0.0.1:14567` | 开发与运行时加载的本地后端地址 |
| `build.frontendDist` | `../dist` | 构建期必须存在的占位目录（运行时不被 WebView 加载） |
| `build.beforeBuildCommand` | `bash build_backend.sh` | 构建前**自动跑 PyInstaller 冻结**（本地 / CI 共用，避免复用旧 sidecar） |
| `build.beforeDevCommand` | `""` | dev 模式不额外构建 |
| `bundle.active` | `true` | 开启打包 |
| `bundle.targets` | `["app"]` | 配置层默认 target；CLI 用 `--bundles app dmg` 实际产出 dmg |
| `bundle.resources` | `{ "bin/pichome-server": "pichome-server" }` | **见第 6 节重点说明** |
| `bundle.icon` | 5 个图标路径 | 必须全部存在，否则打包报错 |
| `bundle.macOS.minimumSystemVersion` | `10.15` | 最低支持系统版本 |

### 4.2 `bundle.resources` 映射方向（极易踩坑）

Tauri v2 的 `resources` 是一个 **`源路径 → 目标路径`** 的 map（键=源、值=目标），源路径相对于 `src-tauri` 目录：

```json
"resources": {
  "bin/pichome-server": "pichome-server"
}
```

- **源** `bin/pichome-server` → 磁盘上 `desktop/src-tauri/bin/pichome-server/`（`build_backend.sh` 的产物，必须存在，否则 `tauri build` 报 `resource not found` 并以退出码 1 失败）。
- **目标** `pichome-server` → 打进 `.app` 后位于 `Contents/Resources/pichome-server/`，正好对齐 `main.rs` 中 `resource_dir().join("pichome-server").join("pichome-server")` 的读取路径。

### 4.3 `release.yml` 关键配置

| 配置 | 值 / 说明 |
| --- | --- |
| 触发 | `on.push.tags: ['v*']`（仅打 tag 触发，不会在普通 push 时跑） |
| 矩阵 | `macos-latest`（arm64）+ `macos-15-intel`（x64；`macos-13` 已退役） |
| `fail-fast` | `false`（一个架构失败不影响另一个继续） |
| Python | `3.12`，装 `pyinstaller waitress` + `requirements.txt` |
| Node | `20` |
| Rust | `dtolnay/rust-toolchain@stable`（用仓库内 `Cargo.lock` 锁版本） |
| tauri-action | `tauri-apps/tauri-action@v0`，`args: '--bundles app'`（仅 `.app`）。**只传证书与签名身份，不传 `APPLE_ID`/`APPLE_PASSWORD`/`APPLE_TEAM_ID`** → Tauri 跳过内置公证 |
| 深度重签 | `desktop/sign_app_bundle.sh` 对最终 `.app` 由内到外重签 + `codesign --verify --strict` 全量收口 |
| 公证 | `desktop/notarize.sh`（`.app` / `.dmg` 各跑一次）：`notarytool submit --wait` → `stapler staple`，失败自动拉 `notarytool log` |
| 手动 dmg | `hdiutil create` 挂载加「应用程序」软链 + 压缩，headless 安全（不用 create-dmg / AppleScript）。**不写死 `-size`**（CI 的 Python.framework 体积远大于本地） |
| 上传 | `upload-artifact@v4`，路径 `src-tauri/target/release/bundle/dmg/*.dmg` |

### 4.4 Apple 开发者签名（6 个 Secrets）

在仓库 `Settings → Secrets and variables → Actions` 配置以下 6 个 Secrets 即可自动签名去 Gatekeeper 拦截；**未配置时变量为空，tauri-action 自动跳过签名（仅生成未签名的 dmg）**，不会因此报错。

| Secret | 含义 |
| --- | --- |
| `APPLE_CERTIFICATE` | 开发者证书（p12 的 base64） |
| `APPLE_CERTIFICATE_PASSWORD` | 证书密码 |
| `APPLE_SIGNING_IDENTITY` | 签名身份（如 `Developer ID Application: ...`） |
| `APPLE_ID` | Apple ID 账号 |
| `APPLE_PASSWORD` | App 专用密码 |
| `APPLE_TEAM_ID` | 开发者团队 ID |

### 4.5 签名与公证流程：为什么必须自己接管（核心）

#### 结论

**不使用 Tauri 的内置公证**。改为在 `tauri build` 之后由两个脚本接管：

```
tauri build（只签名，跳过公证）
  └─ desktop/sign_app_bundle.sh  ← 由内到外深度重签 + 全量校验收口
     └─ desktop/notarize.sh .app ← 公证 + 装订
        └─ Package dmg via hdiutil
           └─ desktop/notarize.sh .dmg ← 签名 + 公证 + 装订
```

#### 为什么关掉 Tauri 的内置公证

Tauri 的 notarize 跑在 `tauri build` 的**最末一步**。等它报错时，`.app` 已经封好，
补救机会为零 —— 这正是 v0.1.1 ~ v0.1.6 反复失败的机制：
报 `failed to notarize app: Finished with status Invalid`，而真正的根因（嵌套 framework
签名形态不对）在那个时刻已经无法修补。

所以 `release.yml` 的 `tauri-action` **只传** `APPLE_CERTIFICATE` /
`APPLE_CERTIFICATE_PASSWORD` / `APPLE_SIGNING_IDENTITY`，**不传** `APPLE_ID` /
`APPLE_PASSWORD` / `APPLE_TEAM_ID`。Tauri 检测不到公证凭据会打印
`skipping app notarization...` 并正常成功退出，剩下的事由 `notarize.sh` 接管。

#### 真正让公证失败的根因：`Python.framework` 在最终 .app 里「不是框架」

CI 的 `notarytool log` 报的是：

```
statusCode 4000  "Archive contains critical validation errors"
path:    PicHome.app/Contents/Resources/pichome-server/_internal/Python.framework/Python
message: "The signature of the binary is invalid."   (arm64)
```

**注意路径是 `Python.framework/Python`（框架根目录），不是 `Versions/3.12/Python`。**
这个细节就是破案线索 —— 它说明 codesign 把**根部那个文件**当成了框架主二进制。

完整链条：

1. PyInstaller 只把框架里的二进制按路径搬进产物（`build_main.py::assemble()`）：

   ```python
   src_path = pathlib.PurePath(python_lib)   # /Library/Frameworks/Python.framework/Versions/3.12/Python
   dst_path = src_path.relative_to(src_path.parent.parent.parent.parent)
   self.binaries.append((str(dst_path), str(src_path), 'BINARY'))
   ```

2. 「补 `Info.plist` + 重建 `Versions/Current` / `<name>` / `Resources` 三个符号链接」
   由 `PyInstaller/utils/osx.py::collect_files_from_framework_bundles()` 负责。
   但该函数里有**多处提前 `continue`**（源路径不满足版本化布局、找不到 `Info.plist` 等），
   一旦命中，产物里就只剩一个「残缺框架」：
   `Python.framework/Versions/3.12/Python`（无 `Info.plist`、无符号链接）。

3. **Tauri 把 sidecar 拷进 `.app` 时会解引用符号链接**。于是 `Python.framework/Python`
   从「指向 `Versions/Current/Python` 的符号链接」变成**真实文件副本**。

4. 至此框架已经**不是版本化布局**了。codesign 看到根部有个叫 `Python` 的真实文件，
   就把它当作主二进制，且找不到任何 `Info.plist`：

   ```
   Executable=.../Python.framework/Python
   Identifier=Python            ← 找不到 Info.plist，回退成目录名（正常应为 org.python.python）
   Format=bundle with Mach-O thin (arm64)
   Info.plist=not bound         ← 决定性的这一行
   ```

5. Apple 公证拿到这种签名，无法确认框架主二进制 → 判 `The signature of the binary is invalid.`

**实测对照**（真实 Developer ID + 官方同款 framework Python，本地 1:1 复现）：

| framework 目录形态 | `codesign -dv` | 公证 |
| --- | --- | --- |
| `Versions/3.12/{Python,Resources/Info.plist}` + `Versions/Current` | `Identifier=org.python.python`、`Info.plist entries=12` | ✅ |
| 只有 `Versions/3.12/Python`（无 Info.plist、无 Current） | codesign **直接拒绝**：`bundle format unrecognized, invalid, or unsuitable` | ❌ |
| 根目录有**真实** `Python` 文件、无 Info.plist（= Tauri 解引用后的最终形态） | `Identifier=Python`、`Info.plist=not bound` | ❌ ← **CI 的实际形态** |

> ⚠️ 关键结论：**问题不是「没签名」或「签的位置不对」，而是「框架本身缺零件」。**
> 所以「在 bincache 里补签」「对 `Versions/3.12/Python` 再 `codesign` 一次」全都无效 ——
> 必须先**把框架结构还原成 Apple 规范形态**，再按 bundle 形态签。

#### Tauri 为什么不管

`tauri-bundler` 的 `add_nested_code_sign_path()` 只扫描 `NESTED_CODE_FOLDER` 的**一层**
（`WalkDir::new(...).min_depth(1).max_depth(1)`），够不到
`Contents/Resources/pichome-server/_internal/Python.framework` 这种深层嵌套。

#### 为什么本地常常复现不了

若本地 Python 是 pyenv / Homebrew 的**非 framework 构建**，PyInstaller 收的是单个
`libpython3.14.dylib`，`_internal/` 里根本没有 `Python.framework`，自然不会踩这个坑。
CI 用 `actions/setup-python` 的 3.12 是 **framework 构建**，才会出现该目录。

#### `desktop/sign_app_bundle.sh`：先还原结构，再由内到外签名

| 顺序 | 对象 | 说明 |
| --- | --- | --- |
| ⓪ | **还原 `.framework` 目录结构** | **核心修复点**。缺 `Info.plist` 就补（优先从 `/Library/Frameworks/<同名>.framework/.../Info.plist` 复制，找不到则合成最小 plist）；`Versions/Current`、根目录 `Resources`、根目录 `<name>` 三个符号链接缺失就补建；被解引用成真实目录/硬拷贝的**还原为符号链接** |
| ① | 所有 Mach-O 文件（`_internal/**/*.so`、`*.dylib`、各种可执行） | 已用目标身份正确签好的**跳过**（CI 上 PyInstaller 已签过，避免数百次 Apple 时间戳请求） |
| ② | 所有嵌套 bundle（`.framework` / `.xpc` / 内嵌 `.app`），最深优先，**无条件 `--force` 重签** | ⓪ 之后框架已是规范形态，`codesign --force <framework>` 即可签出 `Format=bundle` + `Info.plist entries=N` |
| ③ | 最外层 `.app`（带 `entitlements.plist`） | |
| ④ | 全量 `codesign --verify --strict` 收口 | 任一失败立即打印文件路径并 `exit 1` |
| ⑤ | **framework 形态硬校验** | `codesign -dv` 必须出现非 0 的 `Info.plist entries=`，否则打印完整目录结构快照并 `exit 1` —— 把问题从「公证阶段」提前到「构建阶段」，不再白跑一次公证 |

> 顺序不能反：若先签 bundle 再动内部文件，bundle 的 `_CodeSignature` 记录会失效。

本地无证书（`APPLE_SIGNING_IDENTITY` 为空且 keychain 里没有 `Developer ID Application`）时，
脚本自动跳过，`npm run build` 行为不变。

#### `desktop/notarize.sh`

- 传 `.app` → 先 `ditto -c -k --keepParent` 打成 zip（公证要求容器格式）
- 传 `.dmg` → **先 `codesign` 签名**：未签名 dmg 提交公证容易被拒，且 `stapler` 要求目标已签名
- `xcrun notarytool submit … --wait --output-format json`；未通过时自动跑
  `notarytool log <id>`，把每个出问题的文件路径与原因打出来
- 通过后 `xcrun stapler staple` + `stapler validate` 装订
- 未配置 `APPLE_ID` / `APPLE_PASSWORD` / `APPLE_TEAM_ID` 时直接跳过（本地不阻塞构建）

#### 其它要点

1. `desktop/build.spec` 的 `EXE` 设置
   `codesign_identity=os.environ.get("APPLE_SIGNING_IDENTITY") or None` 与 `entitlements_file`。
   PyInstaller 自带的 codesign 会正确处理 `_internal/Python` 的符号链接（只签真实文件）。
   **注意：这一层签名保不住 `Python.framework`（原因见上），最终仍靠 `sign_app_bundle.sh` 收口。**
2. `desktop/build_backend.sh` **不做补签**：脚本里不引用任何 codesign 变量
   （`set -u` 下不会因变量未定义而 `exit 1`）。
3. `desktop/src-tauri/tauri.conf.json` 的 `bundle.macOS`：
   `signingIdentity: "-"` 与 `entitlements: "../entitlements.plist"`。

   > ⚠️ **不要写 `"${env.APPLE_SIGNING_IDENTITY}"`**：Tauri 的配置文件**不做 `${env.*}` 插值**
   > （源码与打包后的二进制里都没有该实现），这串字符会被原样交给 codesign，本地构建必然失败：
   > `${env.APPLE_SIGNING_IDENTITY}: no identity found`
   > → `failed to bundle project: failed codesign application: failed to run command codesign: failed to sign app`。
   > 需要「按环境切换身份」时用环境变量或 `--config` 覆盖，别在 json 里写插值。

   **签名身份来源与优先级**（`crates/tauri-cli/src/interface/rust.rs`：
   `signing_identity = match env::var_os("APPLE_SIGNING_IDENTITY") { Some(v) => …, None => config.macos.signing_identity }`）：

   | 场景 | 身份来源 | 结果 |
   | --- | --- | --- |
   | 本地 `npm run build`（未设环境变量） | 配置里的 `-` | ad-hoc 签名，构建通过、本机可直接运行 |
   | 本地想用真证书 | `APPLE_SIGNING_IDENTITY="Developer ID Application: xxx (TEAMID)" npm run build` | 环境变量覆盖配置，走正式签名 |
   | CI 配了 Secrets | `tauri-action` 注入的 `APPLE_SIGNING_IDENTITY` | 覆盖配置，正式签名（公证由 `notarize.sh` 接手） |
   | CI 未配 Secrets | 配置里的 `-` | ad-hoc（注意下方「空字符串陷阱」） |

   > **空字符串陷阱**：`tauri-bundler` 用 `var_os()` 判断，**空字符串也算「已设置」**。
   > 所以 `env: APPLE_CERTIFICATE: ${{ secrets.X }}` 在 Secret 未配置时会传入 `""`，
   > 触发 `Keychain::with_certificate("")` → `security import` 失败。
   > 正确做法是只在非空时写入 `$GITHUB_ENV`，别把可能为空的 Secret 直接挂到 `env:` 上。

4. `release.yml` 把「导入 Apple 证书到临时 keychain」放在冻结之前：`beforeBuildCommand`
   触发的 PyInstaller 冻结需要证书；该 keychain 在整个 job 内保持解锁，供后续签名步骤复用。

> 本地未配置证书时：`build.spec` 的 `codesign_identity` 为 `None`，PyInstaller 仍会对 sidecar 做
> **ad-hoc 签名**（`codesign -dv` 可见 `flags=0x2(adhoc)`，`codesign --verify` 通过），
> 配合配置里的 `-`，Tauri 对 `.app` 也做 ad-hoc 签名 → 本机可直接运行调试。
---

## 5. 后端冻结要点（`desktop/build.spec` + `build_backend.sh`）

- **PyInstaller onedir 模式**：`run_server.py` 为入口，产物目录 `desktop/src-tauri/bin/pichome-server/`，内含可执行 `pichome-server` 与 `_internal/`。
- **`target_arch=None`**：PyInstaller 按**当前机器架构**原生编译。双架构之所以能分别出包，正是因为两个 runner 架构不同、各自冻结一次。
- **静态收集**：Django 模块需在 `django.setup()` 之后用 `collect_submodules` 收集（否则报 `Apps aren't loaded yet` 被静默跳过）。
- **waitress 而非 gunicorn**：`gunicorn` 的 fork worker 在冻结二进制里会 `SIGSEGV`；`run_server.py` 用纯 Python 的 `waitress` 托管 WSGI。
- **数据目录**：可写资源（SQLite、上传文件）落在用户目录 `~/Library/Application Support/pichome`，由 `settings.py` 的桌面模式接管。
- **`build_backend.sh` 先冻到临时目录再 `cp` 合并**：避免 PyInstaller 在 `COLLECT` 阶段递归删除已存在的 `bin/pichome-server` 引发沙箱拦截。

---

## 6. 注意事项 / 常见踩坑

1. **`build_backend.sh` 必须在 `tauri build` 之前跑**：否则 `src-tauri/bin/pichome-server` 不存在，`resources` 源缺失，`tauri build` 直接退出码 1。
2. **`frontendDist` 占位必须有**：CI 显式 `mkdir -p dist && 写 index.html`；本地出包同样需要先建 `dist/`，否则构建期「嵌入前端资源」失败。
3. **`resources` 键=源、值=目标**：方向写反会导致源找不到（构建失败）或运行时找不到 sidecar（app 起不来）。当前配置方向正确。
4. **`Cargo.lock` 需提交**：保证 Rust 依赖版本在 CI 与本地一致；不要随意 `cargo update` 破坏锁定。
5. **dmg 与 `.app` 都已签名 + 公证 + 装订**：用户从浏览器下载后可直接打开，不再出现「无法验证开发者」；未配置 Secrets 时仍是未签名产物，需右键 → 打开。
6. **`minimumSystemVersion` 与 runner 系统版本**：CI 用较新 macOS 构建，部署目标设为 `10.15` 向下兼容；若调高需确认最低系统。
7. **Intel 腿用 `macos-15-intel`**：`macos-13` 已于 **2025-12-04** 被 GitHub 退役，pin 它会让 job 直接起不来；`macos-15-intel` 是官方现役的 x86_64 镜像。
8. **tag 触发而非分支触发**：CI 仅 `v*` tag 推送时跑；改完代码后**打新 tag 并推送**才会重新出包。
9. **`includeUpdaterJson: false`**：明确关闭 Tauri 更新器 artifact 生成，避免 release 阶段与 release 任务抢着建 GitHub Release 导致 API 冲突。
10. **`.app` 与 `.dmg` 分开产出**：CI 中 Tauri **只打 `.app`**（`--bundles app`），`.dmg` 由后续 `hdiutil` 步骤生成；上传 artifact 只取 `bundle/dmg/*.dmg`。
11. **不要用 Tauri 内置 dmg（create-dmg）**：Tauri 的 `dmg` target 最后会用 `osascript` 调用 Finder 做窗口美化，**在无图形会话的 CI runner（以及无 GUI 的 shell 环境）会卡死/报错**，导致 `tauri build` 以退出码 1 失败。这是本项目早期 CI 报错的根因。务必用第 7 步的 `hdiutil` 手动方案替代。
12. **`hdiutil` 不要写死 `-size`**：CI 的 sidecar 内嵌完整 `Python.framework`（含 stdlib），体积远大于本地构建，写死 `-size 400m` 会 `no space left`；交给 `hdiutil create` 自动计算。挂载后加「应用程序」软链再压缩为 `UDZO`（`hdiutil attach/detach` 是内核级挂载，headless 安全）。
    另：解析 `hdiutil attach` 输出时**不要写 `| sed 1q` / `| head -1`** —— 在 `set -o pipefail` 下这些命令会提前关闭管道、让上游命令收到 SIGPIPE（141），整条管道被判为失败。改为先落盘再 `awk` 解析。
13. **公证失败的头号原因是「`Python.framework` 在最终 `.app` 里不是框架」**（而不是「没签名」或「签的位置不对」）：PyInstaller 只搬了 `Versions/<ver>/Python` 这一个文件，而负责补 `Info.plist` + 重建符号链接的 `collect_files_from_framework_bundles()` 有提前 `continue` 的分支；再加上 Tauri 拷贝 sidecar 时会**解引用符号链接**，最终 framework 变成非版本化布局 → codesign 签出 `Info.plist=not bound` → 公证判 `The signature of the binary is invalid.`。必须先由 `sign_app_bundle.sh` **还原框架结构**再签，详见第 4.5 节。

---

## 7. 故障排查速查

| 现象 | 可能原因 | 排查 |
| --- | --- | --- |
| `tauri build` 退出码 1，报错 `failed to run bundle_dmg.sh` | **Tauri 内置 dmg（create-dmg）最后用 `osascript` 调 Finder 美化，headless CI 下卡死** | 见第 6 节第 11 条：CI 只用 `--bundles app`，dmg 改由 `hdiutil` 手动生成 |
| `tauri build` 退出码 1，报 `resource not found` | `build_backend.sh` 未产出 `src-tauri/bin/pichome-server` | 检查上一步 PyInstaller 是否成功、`requirements.txt` 是否装全 |
| `npm run tauri build` 找不到命令 | `package.json` 缺少 `tauri` script | 确认 `scripts.tauri: "tauri"` 存在 |
| 打包成功但 app 启动报 `未找到 pichome-server sidecar` | `resources` 映射目标路径与 `main.rs` 不一致 | 核对目标是否为 `pichome-server`（对齐 `Resources/pichome-server/...`） |
| 打开 dmg 报「无法验证开发者」 | 未配置 Apple 签名 Secrets（未走公证流程） | 属预期；配置第 4.4 节 Secrets 或右键 → 打开 |
| `tauri build` 退出码 1，报 `failed to bundle project: failed codesign application … no identity found` | `tauri.conf.json` 里写了 `${env.APPLE_SIGNING_IDENTITY}` —— Tauri 配置文件**不做插值** | 见第 4.5 节「其它要点 3」：`signingIdentity` 写 `"-"`，身份靠环境变量覆盖 |
| `notarytool` 返回 `Invalid`，issue 指向 `…/_internal/Python.framework/Versions/*/Python` 的 `The signature of the binary is invalid.` | framework 被签成 **flat 签名**（未绑定 `Info.plist`）—— Tauri 不管、PyInstaller 又在错的位置签 | 见第 4.5 节：`sign_app_bundle.sh` 按 framework bundle 形态 `--force` 重签 |
| `notarytool` 认证失败（`401` / `Invalid credentials`） | `APPLE_PASSWORD` 不是 **App 专用密码** | 到 Apple ID 后台生成 App 专用密码并更新 Secret |
| Intel 腿 job 起不来 / runner 标签不可用 | `macos-13` 已于 2025-12-04 退役 | 见第 6 节第 7 条：改用 `macos-15-intel` |
| 后端起不来 / 白屏 | `frontendDist` 占位缺失或 14567 端口被占 | 确认 `dist/index.html` 存在、端口未被残留进程占用 |
