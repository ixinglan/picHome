#!/usr/bin/env python3
"""
pichome 桌面端后端入口（供 PyInstaller 冻结为可执行文件）。

职责：
1. 确保桌面模式开启（PICHOME_DESKTOP=1）。
2. Django 启动前完成一次性引导：迁移数据库、初始化管理员、初始化图床配置、收集静态文件。
   这些可写资源落在「用户数据目录」（~/Library/Application Support/pichome），
   由 settings.py 的桌面模式接管（不再用项目根目录）。
3. 用 gunicorn 编程式 API 内嵌拉起 WSGI 服务，绑定 127.0.0.1:固定端口。

Tauri 壳会 spawn 本可执行文件作为 sidecar，再用 WebView 加载 http://127.0.0.1:PORT。
"""
import os
import sys

# 桌面模式标记必须在导入 Django settings 之前设置
os.environ.setdefault("PICHOME_DESKTOP", "1")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pichome_web.settings")


def _bootstrap():
    """Django 启动前的一次性初始化（幂等，可重复运行）。"""
    import django
    from django.core.management import call_command

    django.setup()
    # 必须在 django.setup() 之后才能 import app 模型，否则 AppRegistryNotReady
    from django.contrib.auth.models import User

    # 1) 数据库迁移（幂等）
    call_command("migrate", "--noinput", verbosity=0)

    # 2) 初始化管理员账号（当库里还没有任何「超级管理员」时）。
    #    注意：演示账号 demo 是普通用户（非超级管理员），会先被 0006 迁移创建，
    #    因此不能用 `User.objects.exists()` 判断，否则 admin 永远建不出来。
    if not User.objects.filter(is_superuser=True).exists():
        try:
            call_command("inituser")
        except Exception as e:  # noqa: BLE001
            print(f"[pichome] inituser 跳过：{e}")

    # 3) 初始化图床配置（仅当无任何图床配置，从 .env 的 QINIU_* 播种）
    try:
        call_command("initstorage")
    except Exception as e:  # noqa: BLE001
        print(f"[pichome] initstorage 跳过：{e}")

    # 4) 收集静态文件到用户数据目录（供 Whitenoise 提供）
    call_command("collectstatic", "--noinput", verbosity=0)


def main():
    _bootstrap()

    from pichome_web.wsgi import application
    from waitress import serve

    port = int(os.getenv("PICHOME_DESKTOP_PORT", "14567"))
    print(f"[pichome] 服务已启动：http://127.0.0.1:{port}")
    # waitress 是纯 Python WSGI 服务器（线程模型、无 fork），比 gunicorn 更适合
    # 冻结分发：gunicorn 的 fork worker 在 PyInstaller 二进制里会 SIGSEGV。
    serve(application, host="127.0.0.1", port=port, threads=4)


if __name__ == "__main__":
    main()
