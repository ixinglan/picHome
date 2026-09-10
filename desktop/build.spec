# -*- mode: python ; coding: utf-8 -*-
"""pichome 桌面端后端冻结 spec（onedir 模式）。

把 Django + gunicorn + whitenoise 打包成 macOS 可执行 pichome-server，
由 Tauri 壳作为 sidecar 拉起。资源根目录由 sys.argv[0] 推导。

关键坑（Django 冻结）：PyInstaller 在静态收集阶段会真正 import 各模块，
但此时 Django 尚未 setup，项目 app 模块 import 会抛 "Apps aren't loaded yet" 被静默跳过。
因此必须先在构建期 django.setup()，collect_submodules 才能成功收集项目模块。
"""
import os
import sys

SPECPATH = os.path.dirname(os.path.abspath(sys.argv[0]))
ROOT = os.path.dirname(SPECPATH)  # desktop/ 的上一级 = 项目根

# 让 PyInstaller 能找到并成功导入项目包（Django 需要 setup 后才能 import app 模块）
sys.path.insert(0, ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pichome_web.settings")
os.environ.setdefault("PICHOME_DESKTOP", "1")
import django
django.setup()

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# 模板 / 静态 / 迁移作为数据打包。
# 注意：dest 不要加 _internal 前缀 —— PyInstaller onedir 已把所有内容放进 _internal/，
# 加前缀会变成 _internal/_internal 双层嵌套。
datas = [
    (os.path.join(ROOT, "gallery", "templates"), "gallery/templates"),
    (os.path.join(ROOT, "gallery", "static"), "gallery/static"),
    (os.path.join(ROOT, "gallery", "migrations"), "gallery/migrations"),
]

hiddenimports = [
    # waitress 纯 Python WSGI 服务器（无 fork，避免 gunicorn 冻结后 SIGSEGV）
    *collect_submodules("waitress"),
    "whitenoise",
    "whitenoise.storage",
    "whitenoise.middleware",
    "dotenv",
    # Django 通过字符串(DJANGO_SETTINGS_MODULE / INSTALLED_APPS)动态加载，
    # 必须在 django.setup() 之后收集，否则 import 失败被跳过
    *collect_submodules("gallery"),
    *collect_submodules("pichome_web"),
    "qiniu",
    "oss2",
    "qcloud_cos",
    "requests",
]

a = Analysis(
    [os.path.join(ROOT, "desktop", "run_server.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="pichome-server",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    target_arch=None,
    # 配置了 APPLE_SIGNING_IDENTITY 时（CI 中），由 PyInstaller 在冻结阶段递归签名
    # 整个 sidecar：主可执行 pichome-server 附带 Python 运行时所需的 entitlements
    # （allow-jit / allow-unsigned-executable-memory / disable-library-validation），
    # _internal 下所有 .so/.dylib/Python 解释器用 runtime option 签名。
    # 本地开发未配置证书时两者为 None，PyInstaller 不签名（仅出未签名产物）。
    # 关键：必须在 tauri build / notarize 之前签好，否则 Tauri 的 notarize 会先跑、扫到
    # 未签名的 _internal 直接判 invalid（这正是之前 v0.1.1~v0.1.4 反复失败的根因）。
    codesign_identity=os.environ.get("APPLE_SIGNING_IDENTITY") or None,
    entitlements_file=(
        os.path.join(SPECPATH, "entitlements.plist")
        if os.environ.get("APPLE_SIGNING_IDENTITY")
        else None
    ),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="pichome-server",
)
