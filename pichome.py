#!/usr/bin/env python3
"""
pichome —— picHome 图床命令行客户端（供人与 AI Agent 调用）。

设计要点（满足 3.1 / 3.3）：
- 两种运行模式自动选择：
  1) 容器内（或已配置 Django 环境）用 --in-process：直接调用上传核心，零网络开销；
  2) 宿主机：把图片 POST 到正在运行的服务的 /api/v1/upload，拿到 JSON 结果。
     （推荐：agent 在 docker compose 启动的服务外，直接用这种模式即可。）
- 输出统一为 JSON（markdown / cdn_url / html 等），方便 agent 或脚本消费。
- 暂只支持单张上传（按需求 3.1）。

用法示例：
  # 宿主机（docker compose 默认映射 28080）：直接上传，返回 JSON
  python pichome.py --upload ./photo.png

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


def _print_result(payload: dict, ok: bool):
    json.dump(payload, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    sys.exit(0 if ok else 1)


def _err(msg: str):
    _print_result({"ok": False, "error": msg}, ok=False)


def upload_in_process(path: str, tags: str):
    """容器内模式：直接复用 Web 同一套上传核心（gallery.upload_service）。"""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "qiniu_tool.settings")
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
        default=os.getenv("PICHOME_API_URL", "http://127.0.0.1:28080"),
        help="服务地址（HTTP 模式用），默认 http://127.0.0.1:28080（docker compose 映射端口），"
        "也可用环境变量 PICHOME_API_URL 覆盖",
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
        upload_http(path, args.tags, args.url, args.token)


if __name__ == "__main__":
    main()
