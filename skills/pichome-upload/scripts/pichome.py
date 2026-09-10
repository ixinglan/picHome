#!/usr/bin/env python3
"""
pichome —— picHome 图床命令行客户端（供人与 AI Agent 调用）。

设计要点（满足 3.1 / 3.3）：
- 两种运行模式自动选择：
  1) 容器内（或已配置 Django 环境）用 --in-process：直接调用上传核心，零网络开销；
  2) 宿主机：把图片 POST 到正在运行的服务的 /api/v1/upload，拿到 JSON 结果。
     （推荐：agent 在 docker compose 启动的服务外，直接用这种模式即可。）
- **桌面版优先**：picHome 有两套服务形态，端口不同——
    · 桌面版（Tauri 原生 App）：后端随 App 启动，监听 127.0.0.1:14567；
    · Web 版（docker compose / runserver）：默认 127.0.0.1:28080（容器 8000）/ 本地 runserver 8000。
  未显式给定 --url 时，脚本会**先探测桌面版 14567 是否在线，在线则优先用桌面版**，
  否则回退到 Web 版默认端口。这样“打开桌面 App 后让 Agent 上传”能自动命中正确端口。
- 输出统一为 JSON（markdown / cdn_url / html 等），方便 agent 或脚本消费。
- 暂只支持单张上传（按需求 3.1）。

用法示例：
  # 桌面版已打开（推荐，自动探测 14567）：直接上传，返回 JSON
  python pichome.py --upload ./photo.png

  # 强制走桌面版端口 / 强制走 Web 版端口
  python pichome.py --upload ./photo.png --desktop
  python pichome.py --upload ./photo.png --web

  # 本地 runserver（8000）或其它部署，显式指定服务地址
  python pichome.py --upload ./photo.png --url http://127.0.0.1:8000

  # Docker 容器内（in-process，走 Django 核心）
  docker compose exec -T web python pichome.py --in-process --upload /app/inbox/photo.png

  # 带标签
  python pichome.py --upload ./photo.png --tags "风景,旅行"
"""
import argparse
import json
import os
import sys
import urllib.parse


# ===== 端口约定（与 desktop/src-tauri/src/main.rs 保持一致）=====
# 桌面版：Tauri 壳随 App 拉起 Django(waitress)，绑定 127.0.0.1:14567
DESKTOP_PORT = int(os.getenv("PICHOME_DESKTOP_PORT", "14567"))
# Web 版默认回退端口：docker compose 映射 28080（容器内 8000）
WEB_PORT = int(os.getenv("PICHOME_WEB_PORT", "28080"))


def _print_result(payload: dict, ok: bool):
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    sys.exit(0 if ok else 1)


def _err(msg: str):
    _print_result({"ok": False, "error": msg}, ok=False)


def _probe(base: str, timeout: float = 1.0) -> bool:
    """快速探测某服务地址是否在线（桌面版优先用）。GET / 不关心响应体。"""
    import urllib.request

    try:
        urllib.request.urlopen(base.rstrip("/") + "/", timeout=timeout)
        return True
    except Exception:  # noqa: BLE001
        return False


def _resolve_base_url(args) -> str:
    """按优先级解析最终要请求的服务地址。

    优先级：--desktop > --web > 显式 --url > 环境变量 PICHOME_API_URL
            > 探测桌面版 14567（在线则优先）> Web 默认端口
    """
    if args.desktop:
        return f"http://127.0.0.1:{DESKTOP_PORT}"
    if args.web:
        return f"http://127.0.0.1:{WEB_PORT}"
    if args.url:
        return args.url.rstrip("/")
    env_url = os.getenv("PICHOME_API_URL")
    if env_url:
        return env_url.rstrip("/")
    # 桌面版优先：未显式指定时，若 14567 在线就用桌面版
    desktop_url = f"http://127.0.0.1:{DESKTOP_PORT}"
    if not args.no_probe and _probe(desktop_url):
        return desktop_url
    return f"http://127.0.0.1:{WEB_PORT}"


def upload_in_process(path: str, tags: str):
    """容器内模式：直接复用 Web 同一套上传核心（gallery.upload_service）。"""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pichome_web.settings")
    import django

    django.setup()
    from gallery.upload_service import upload_image

    try:
        payload = upload_image(source=path, original_name=os.path.basename(path), tags=tags)
    except Exception as e:  # noqa: BLE001
        _err(f"上传失败：{e}")
    _print_result(payload, ok=True)


def upload_http(path: str, tags: str, api_base: str, token: str = ""):
    """宿主机模式：把文件 POST 到运行中的服务 /api/v1/upload。"""
    import urllib.request

    url = api_base.rstrip("/") + "/api/v1/upload"
    if token:
        url += "?" + urllib.parse.urlencode({"token": token})
    boundary = "----pichomeboundary"
    # 构造 multipart/form-data
    body = bytearray()
    if tags:
        body += f"--{boundary}\r\n".encode()
        body += b'Content-Disposition: form-data; name="tags"\r\n\r\n'
        body += tags.encode() + b"\r\n"
    body += f"--{boundary}\r\n".encode()
    body += b'Content-Disposition: form-data; name="file"; filename="%s"\r\n' % os.path.basename(path).encode()
    body += b"Content-Type: application/octet-stream\r\n\r\n"
    try:
        with open(path, "rb") as f:
            body += f.read()
    except OSError as e:
        _err(f"无法读取文件：{e}")
    body += f"\r\n--{boundary}--\r\n".encode()

    req = urllib.request.Request(url, data=bytes(body), method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:300]
        _err(f"服务返回错误（{e.code}）：{detail}")
    except Exception as e:  # noqa: BLE001
        _err(f"请求服务失败：{e}")

    try:
        result = json.loads(data)
    except json.JSONDecodeError:
        _err(f"服务返回非 JSON：{data[:200]}")
    _print_result(result, ok=bool(result.get("ok")))


def main():
    p = argparse.ArgumentParser(
        prog="pichome", description="picHome 图床命令行客户端：上传图片并返回 JSON 链接"
    )
    p.add_argument("--upload", required=True, metavar="PATH", help="要上传的图片路径")
    p.add_argument("--tags", default="", help="标签，逗号分隔（可选）")
    p.add_argument(
        "--url",
        default=None,
        help="服务地址（HTTP 模式用）。不传时自动探测：先试桌面版 14567，再回退 Web 版 28080；"
        "也可用环境变量 PICHOME_API_URL 覆盖。--desktop/--web 可强制指定形态",
    )
    p.add_argument(
        "--desktop",
        action="store_true",
        help="强制使用桌面版端口（127.0.0.1:14567，Tauri App 自带后端）",
    )
    p.add_argument(
        "--web",
        action="store_true",
        help="强制使用 Web 版端口（127.0.0.1:28080 / docker compose 映射；本地 runserver 用 --url 指定 8000）",
    )
    p.add_argument(
        "--no-probe",
        action="store_true",
        help="不做在线探测，直接用 Web 版默认地址（适合确定只跑 Web 版时跳过 1 秒探测）",
    )
    p.add_argument(
        "--in-process",
        action="store_true",
        help="容器内/已配置 Django 时使用：直接调用上传核心，不走 HTTP",
    )
    p.add_argument(
        "--token",
        default=os.getenv("PICHOME_API_TOKEN", ""),
        help="API 令牌（服务设了 PICHOME_API_TOKEN 时必填），或环境变量 PICHOME_API_TOKEN",
    )
    args = p.parse_args()

    path = args.upload
    if not os.path.isfile(path):
        _err(f"文件不存在：{path}")

    if args.in_process:
        upload_in_process(path, args.tags)
    else:
        base = _resolve_base_url(args)
        # 把选用的地址打到 stderr，避免污染 stdout 的 JSON
        print(f"[pichome] 目标服务：{base}（桌面版优先自动探测）", file=sys.stderr)
        upload_http(path, args.tags, base, args.token)


if __name__ == "__main__":
    main()
