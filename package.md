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

**触发条件**：推送 `v*` 格式的 tag 到 `main`（例如 `git tag v0.1.0 && git push origin v0.1.0`）。

**双架构矩阵**：

| 矩阵项 | Runner | 架构 | 产物 |
| --- | --- | --- | --- |
| `apple-silicon` | `macos-latest` | arm64 | `dmg-apple-silicon` |
| `intel` | `macos-13` | x64 | `dmg-intel` |

每个 runner 内部依次执行：

1. `actions/checkout@v5`
2. `setup-python@v5`（3.12）→ 建 `.venv`、装 `requirements.txt` + `pyinstaller` + `waitress`
3. `bash desktop/build_backend.sh` → 生成 `src-tauri/bin/pichome-server`（**按当前 runner 架构原生编译**）
4. `setup-node@v5`（Node 20）→ `npm install`
5. 生成 `desktop/dist/index.html` 占位
6. `tauri-apps/tauri-action@v0`，`args: '--bundles app'`（**只打 `.app`**；dmg 不走 Tauri 内置 create-dmg），`includeUpdaterJson: false`
7. `Package dmg via hdiutil`：用 `hdiutil create` 挂载临时镜像、加入「应用程序」快捷方式、再压缩，手动产出 `.dmg`（完全 headless，详见第 6 节）
8. `upload-artifact@v4` 上传 `src-tauri/target/release/bundle/dmg/*.dmg`

两个架构都成功后，`release` 任务会把两份 dmg 合并进同一个 **draft** GitHub Release。

---

## 4. 关键配置项

### 4.1 `desktop/src-tauri/tauri.conf.json`

| 配置键 | 值 | 作用 |
| --- | --- | --- |
| `productName` | `PicHome` | 决定 `.app` / `.dmg` 文件名与窗口标题 |
| `version` | `0.1.0` | **版本号单一来源**，CI 不额外覆盖；改版本改这里 |
| `identifier` | `com.pichome.desktop` | macOS bundle identifier |
| `build.devUrl` / `app.windows[].url` | `http://127.0.0.1:14567` | 开发与运行时加载的本地后端地址 |
| `build.frontendDist` | `../dist` | 构建期必须存在的占位目录（运行时不被 WebView 加载） |
| `build.beforeBuildCommand` / `beforeDevCommand` | `""` | 不执行额外前端构建命令 |
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
| 矩阵 | `macos-latest`（arm64）+ `macos-13`（x64） |
| `fail-fast` | `false`（一个架构失败不影响另一个继续） |
| Python | `3.12`，装 `pyinstaller waitress` + `requirements.txt` |
| Node | `20` |
| Rust | `dtolnay/rust-toolchain@stable`（用仓库内 `Cargo.lock` 锁版本） |
| tauri-action | `tauri-apps/tauri-action@v0`，`args: '--bundles app'`（仅 `.app`；dmg 用 hdiutil 手动生成，见下） |
| 手动 dmg | `hdiutil create` 挂载加「应用程序」软链 + 压缩，headless 安全（不用 create-dmg / AppleScript） |
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

### 4.5 公证（notarize）必须先递归签名 sidecar

配置了第 4.4 节的 6 个 Secrets 后，tauri-action 会自动走「签名 + 公证」。但
**Tauri 自带的 codesign 只签 `.app` 主二进制，不会递归签名
`Resources/pichome-server` 这个 PyInstaller 冻结出的第三方 bundle**——它内部的
`.so` / `.dylib` / `Python` 解释器仍是未签名状态。Apple 公证会扫描整个 `.app`，
发现这些未签名二进制会直接判定 `Invalid` 并失败，最终 `tauri build` 退出码 1，报错
`failed to notarize app: Finished with status Invalid`。

**修复**：在 `tauri build` 之前，先用 `codesign --force --timestamp --options runtime
-s "$APPLE_SIGNING_IDENTITY"` 递归给整个 `bin/pichome-server` 目录签名（主可执行再附加
`desktop/entitlements.plist`），再交给 Tauri 打包。该逻辑已写入 `release.yml` 的
「Codesign PyInstaller sidecar」步骤，并在 `APPLE_SIGNING_IDENTITY` 为空时自动跳过。

> 本地未配置证书时无需此步：本地构建出未签名 `.app`，macOS 对「本机开发者自己构建的
> app」不强制公证，可直接运行调试。

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
5. **未签名 dmg 的 Gatekeeper 提示**：首次打开可能提示「无法验证开发者」，右键 → 打开 即可；配置了第 4.4 节的 6 个 Secrets 后可消除。
6. **`minimumSystemVersion` 与 runner 系统版本**：CI 用较新 macOS 构建，部署目标设为 `10.15` 向下兼容；若调高需确认最低系统。
7. **`macos-13` 是 GitHub 唯一仍提供 Intel 的 runner**：双架构里的 x64 只能用它；若未来该 runner 下线需调整。
8. **tag 触发而非分支触发**：CI 仅 `v*` tag 推送时跑；改完代码后**打新 tag 并推送**才会重新出包。
9. **`includeUpdaterJson: false`**：明确关闭 Tauri 更新器 artifact 生成，避免 release 阶段与 release 任务抢着建 GitHub Release 导致 API 冲突。
10. **`.app` 与 `.dmg` 分开产出**：CI 中 Tauri **只打 `.app`**（`--bundles app`），`.dmg` 由后续 `hdiutil` 步骤生成；上传 artifact 只取 `bundle/dmg/*.dmg`。
11. **不要用 Tauri 内置 dmg（create-dmg）**：Tauri 的 `dmg` target 最后会用 `osascript` 调用 Finder 做窗口美化，**在无图形会话的 CI runner（以及无 GUI 的 shell 环境）会卡死/报错**，导致 `tauri build` 以退出码 1 失败。这是本项目早期 CI 报错的根因。务必用第 7 步的 `hdiutil` 手动方案替代。
12. **`hdiutil` 方案需 `-size` 留足空间**：临时 `UDRW` 镜像用 `-size 400m` 留余量（实际 `.app` 约 88M），挂载后加「应用程序」软链再压缩为 `UDZO`。`hdiutil attach/detach` 是内核级挂载，headless 安全。
13. **公证（notarize）依赖 sidecar 已被递归签名**：这是「配了 Apple 证书却仍 `tauri build` 退出码 1」的最常见原因，详见第 4.5 节。

---

## 7. 故障排查速查

| 现象 | 可能原因 | 排查 |
| --- | --- | --- |
| `tauri build` 退出码 1，报错 `failed to run bundle_dmg.sh` | **Tauri 内置 dmg（create-dmg）最后用 `osascript` 调 Finder 美化，headless CI 下卡死** | 见第 6 节第 11 条：CI 只用 `--bundles app`，dmg 改由 `hdiutil` 手动生成 |
| `tauri build` 退出码 1，报 `resource not found` | `build_backend.sh` 未产出 `src-tauri/bin/pichome-server` | 检查上一步 PyInstaller 是否成功、`requirements.txt` 是否装全 |
| `npm run tauri build` 找不到命令 | `package.json` 缺少 `tauri` script | 确认 `scripts.tauri: "tauri"` 存在 |
| 打包成功但 app 启动报 `未找到 pichome-server sidecar` | `resources` 映射目标路径与 `main.rs` 不一致 | 核对目标是否为 `pichome-server`（对齐 `Resources/pichome-server/...`） |
| 打开 dmg 报「无法验证开发者」 | 未配置 Apple 签名 Secrets | 属预期；配置第 4.4 节 Secrets 或右键打开 |
| `tauri build` 退出码 1，报 `failed to notarize app: Finished with status Invalid` | 配了 Apple 证书，但 `pichome-server` 内部 `.so`/`.dylib` 未签名，公证被拒 | 见第 4.5 节：CI 在 `tauri build` 前递归 codesign sidecar；确认 `APPLE_SIGNING_IDENTITY` 是有效的 `Developer ID Application` |
| 后端起不来 / 白屏 | `frontendDist` 占位缺失或 14567 端口被占 | 确认 `dist/index.html` 存在、端口未被残留进程占用 |
