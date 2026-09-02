---
name: pichome-upload
description: >-
  This skill uploads images to the picHome image host and returns ready-to-use
  links (Markdown, HTML, raw CDN URL) as JSON. Use it when an AI agent or user
  needs to push a local image into picHome (a multi-backend image bed: Qiniu /
  Aliyun OSS / Tencent COS / GitHub) and get back embeddable links, especially
  while a picHome service (Docker Compose or local) is running. Triggers include
  "upload this image to picHome", "把图片传到 picHome", "用 picHome 上传并给我
  markdown 链接", or any agent task that must persist an image and embed it in
  chat/markdown/html output.
agent_created: true
---

# picHome Upload

Upload an image to a running picHome instance and receive a JSON payload with
the CDN URL plus Markdown and HTML snippets. Designed so an AI agent can call it
during a session without leaving the conversation.

## When to use

- Persisting a generated or downloaded image so it can be linked in markdown/HTML.
- Any task where the user asks to "upload to picHome" or needs an image URL.
- Agent workflows that produce images and must return embeddable links.

## How it works

The skill ships `scripts/pichome.py` — a single-file CLI with two modes:

1. **HTTP mode (default, recommended for agents).** POSTs the file to a running
   picHome service at `/api/v1/upload`. No Django environment required on the
   caller side.
2. **In-process mode (`--in-process`).** Runs inside the picHome container and
   calls the upload core directly (zero network hop).

## Usage

### Prerequisites
- A picHome service reachable over HTTP. With Docker Compose the host port is
  `28080` by default (container listens on `8000`); verify with
  `docker port pichome-web 8000`.
- The service must have an **active storage backend** configured (Settings →
  Storage). If none is active, uploads are rejected with `error`.
- If the service sets `PICHOME_API_TOKEN`, pass `--token` or export
  `PICHOME_API_TOKEN`; when unset the API accepts anonymous calls.

### Host mode (agent, service already running)
```bash
# default service URL http://127.0.0.1:28080 (or set PICHOME_API_URL)
python scripts/pichome.py --upload /path/to/photo.png

# with tags, custom service URL (e.g. local `manage.py runserver`)
python scripts/pichome.py --upload /path/to/photo.png --tags "风景,旅行" \
    --url http://127.0.0.1:8000
```

### Docker Compose interaction (3.1)
When picHome is started via `docker compose`, the agent on the host should use
**host HTTP mode** — the CLI reads the file bytes locally and sends them over
HTTP, so no shared volume is required:
```bash
docker port pichome-web 8000        # find the mapped host port (28080 by default)
python scripts/pichome.py --upload ./photo.png --url http://127.0.0.1:28080
```
If a file already lives inside the container (e.g. produced by another container
step), run in-process instead:
```bash
docker compose exec -T web python pichome.py --in-process --upload /app/inbox/photo.png
```

### Output (stdout, JSON, one line)
```json
{
  "ok": true,
  "id": 42,
  "original_name": "photo.png",
  "object_key": "img/20260902_060518_123_ab12.png",
  "provider": "qiniu",
  "cdn_url": "https://img.example.com/img/20260902_060518_123_ab12.png",
  "thumb_url": "https://img.example.com/img/20260902_060518_123_ab12.png?imageView2/2/w/400/q/75",
  "size": 123456,
  "tags": ["风景", "旅行"],
  "uploaded_at": "2026-09-02 06:05:18",
  "markdown": "![photo.png](https://img.example.com/img/20260902_060518_123_ab12.png \"photo.png\")",
  "html": "<img src=\"https://img.example.com/img/20260902_060518_123_ab12.png\"/>"
}
```
On failure, `ok` is `false` and an `error` field explains the cause (e.g. missing
backend config, unsupported format, network error). Exit code is `1`.

## Notes
- Single image per invocation (per current requirement). Loop over files to batch.
- Supported formats: jpg, jpeg, png, gif, webp, bmp, heic, svg.
- The `--url` / `PICHOME_API_URL` controls the target service; no code changes
  needed to point at a different deployment.
