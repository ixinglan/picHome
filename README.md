# picHome

一个自托管的**多图床图片管理工具**：网页上传图片 → 落本地磁盘留底 → 上传到你选定的图床 → 拿到 CDN / Markdown / HTML 三种链接，支持标签与图床双维度筛选、上传历史、回收站恢复。

除网页端外，还提供 **HTTP API** 与 **命令行 `pichome`**，让 AI Agent 在服务运行时直接上传图片并拿到 JSON 链接。

支持图床：**七牛云 Kodo**、**阿里云 OSS**、**腾讯云 COS**、**GitHub 仓库**（可继续扩展）。

服务端渲染（Django Template）+ 原生 JS 增强，**不做前后端分离**，单进程跑起来就能用。

---

## 一、功能特性

| 分类 | 能力 |
| --- | --- |
| 多图床 | 七牛云 / 阿里云 OSS / 腾讯云 COS / GitHub，**页面上填配置即可切换**，无需改代码或配置文件 |
| 配置校验 | 每个图床自带「字段模板」，页面自动渲染表单；必填项缺失时**无法启用**并行内报错 |
| 上传方式 | ① 点击选择 ② **拖拽图片到页面任意位置** ③ **粘贴剪贴板图片**（Ctrl/Cmd+V 或点按钮）④ HTTP API ⑤ 命令行 |
| 链接格式 | 每张图同时给出 **CDN 原图链接 / Markdown / HTML**，逐个一键复制 |
| 命名 | 本地保留原始文件名；上传图床时**自动重命名为时间戳**，数据库保存映射关系 |
| 筛选 | **按图床筛选**（chips，带数量）+ 按标签筛选 + 关键词搜索，三者可叠加 |
| 上传历史 | 独立页面，按时间倒序展示全部上传记录，可直接复制三种链接 |
| 长名展示 | 卡片文件名过长时截断，**悬浮显示完整名称**，并可一键复制原名 |
| 分类 | 图片标签（上传时打标签、卡片改标签、批量改标签） |
| 删除 | 单张 / 按对象名 / 勾选批量；均带自定义确认弹窗 |
| 回收站 | 删除只移除图床对象，**本地文件移入回收站**；支持恢复（重新上传）与彻底删除 |
| 鉴权 | 全站登录保护 + 独立登录页；对外 API 走独立 Token |
| CLI / Agent | `pichome --upload x.png` 返回 JSON（cdn / markdown / html），已封装为标准 Skill |

---

## 二、技术栈

| 组件 | 版本 / 说明 |
| --- | --- |
| Python | 3.13（容器） / 3.14（本地 pyenv） |
| Django | 6.1 |
| 图床 SDK | `qiniu` 7.18、`oss2`（阿里云）、`cos-python-sdk-v5`（腾讯云）、`requests`（GitHub API） |
| python-dotenv | 读取 `.env` |
| 数据库 | SQLite（`db.sqlite3`，开箱即用） |
| 前端 | Django Template + 原生 CSS / JS，无构建工具 |
| 部署 | Docker Compose + Gunicorn + Whitenoise |

> 各图床 SDK 都是**惰性导入**（用到才 import），只用七牛云时不会因为没装 `oss2` 而报错。

---

## 三、快速开始

### 1. 准备虚拟环境

```bash
cd "/Users/ixiaoqiang/WorkBuddy/七牛云"
/Users/ixiaoqiang/.pyenv/shims/python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 2. 建表 + 建账号

```bash
.venv/bin/python manage.py migrate
.venv/bin/python manage.py inituser                                    # 默认 admin / admin12345
.venv/bin/python manage.py inituser --username xq --password 你的密码    # 自定义
```

### 3. 启动并配置图床

```bash
.venv/bin/python manage.py runserver
```

打开 <http://127.0.0.1:8000/> 登录后，点右上角**齿轮图标 → 图床设置**：

1. 选一个图床（七牛云 / 阿里云 / 腾讯云 / GitHub）；
2. 页面会**自动渲染该图床需要的字段**（含占位示例与说明）；
3. 保存 → 点「启用」。必填项没填全时按钮不可用并提示原因。

> 若 `.env` 里已有 `QINIU_*` 四项，首次启动会由 `initstorage` 命令**自动生成一条启用中的七牛云配置**，可直接用，也可在页面上改。

---

## 四、目录结构

```
七牛云/
├── manage.py
├── pichome.py                     # ★ 命令行客户端（人 / AI Agent 用）
├── requirements.txt
├── .env.example / .env            # 环境配置（.env 已 gitignore）
├── Dockerfile / docker-compose.yml / docker-entrypoint.sh
├── README.md
│
├── .workbuddy/skills/pichome-upload/   # ★ 标准 Skill（可被 agent 直接调用）
│   ├── SKILL.md
│   └── scripts/pichome.py             # 与根目录 pichome.py 保持同步
│
├── pichome_web/                   # Django 项目配置包（settings / urls / wsgi / asgi）
│   ├── settings.py                # 含 PICHOME_API_TOKEN / 媒体目录 / 登录配置
│   ├── urls.py / wsgi.py / asgi.py
│
├── gallery/
│   ├── storage/                   # ★ 存储抽象层（纯 Python，不依赖 Django）
│   │   ├── base.py                #   FieldSpec + StorageProvider 抽象基类
│   │   ├── registry.py            #   注册表：create_provider / list_specs
│   │   ├── qiniu_provider.py      #   七牛云 Kodo
│   │   ├── aliyun_provider.py     #   阿里云 OSS
│   │   ├── tencent_provider.py    #   腾讯云 COS
│   │   ├── github_provider.py     #   GitHub 仓库
│   │   └── exceptions.py          #   StorageError / ConfigError
│   ├── upload_service.py          # ★ 上传核心：落盘 → 上传图床 → 写库 → 出 payload
│   ├── django_backend.py          # 从 StorageConfig 取出「当前启用的 provider」
│   ├── models.py                  # ImageAsset / Tag / StorageConfig
│   ├── views.py                   # 页面视图 + AJAX 接口 + 对外 API
│   ├── urls.py / admin.py
│   ├── management/commands/
│   │   ├── inituser.py            # 创建/重置登录账号
│   │   └── initstorage.py         # 从 .env 播种七牛云配置（幂等）
│   ├── migrations/                # 0001 建表 / 0002 标签 / 0003 多图床改造
│   ├── templates/gallery/
│   │   ├── base.html              # 母版：品牌 picHome + 导航 + 弹窗 + Toast
│   │   ├── index.html             # 图库首页（图床筛选 + 标签筛选 + 卡片三链接）
│   │   ├── history.html           # ★ 上传历史（时间倒序）
│   │   ├── storage_settings.html  # ★ 图床配置页（表单由字段模板自动渲染）
│   │   ├── recycle.html           # 回收站
│   │   └── login.html             # 登录页（卡片上移、禁止纵向滚动）
│   └── static/gallery/
│       ├── css/style.css
│       └── js/app.js, storage.js
│
└── media/
    ├── uploads/                   # 正常图片（保留原始文件名）
    └── recycle/                   # 回收站
```

---

## 五、架构设计

### 5.1 分层：核心与 Django 解耦

这是本次改造的重点 —— **保存到磁盘 + 上传图床的核心，不依赖 Django、不依赖 HTTP**，因此可以被网页、HTTP API、命令行三条入口复用，未来也能直接被桌面客户端复用。

```
        ┌──────────────┐   ┌──────────────┐   ┌────────────────────┐
入口层  │  浏览器页面   │   │  HTTP API    │   │  CLI  pichome.py   │
        │ POST /upload │   │ /api/v1/     │   │  --upload x.png    │
        └──────┬───────┘   └──────┬───────┘   └─────┬────────┬─────┘
               │                  │                 │HTTP    │in-process
               ▼                  ▼                 ▼        │
        ┌──────────────────────────────────────────────┐     │
编排层  │            gallery/views.py                  │     │
        │  （只做参数校验 / 鉴权 / 组织响应）            │     │
        └──────────────────┬───────────────────────────┘     │
                           ▼                                 │
        ┌──────────────────────────────────────────────┐◀────┘
核心层  │       gallery/upload_service.py               │
        │  落本地磁盘 → 调 provider 上传 → 写库 → payload │
        └──────────────────┬───────────────────────────┘
                           ▼
        ┌──────────────────────────────────────────────┐
存储层  │  gallery/storage/  （纯 Python，可独立复用）    │
        │  StorageProvider 抽象 + 4 个实现 + 注册表      │
        └──────────────────┬───────────────────────────┘
                           ▼
              七牛云 / 阿里云 OSS / 腾讯云 COS / GitHub
```

要点：

- **`storage/` 完全不 import Django**，只认「配置 dict + 文件字节」，所以桌面客户端可以直接把它当 SDK 用；
- **`upload_service.upload_image()` 是唯一上传入口**，网页 / API / CLI 三条路走的是同一段代码，行为绝对一致；
- **`django_backend.py` 是唯一的胶水层**，负责「从数据库读出启用中的配置 → 造出 provider 实例」；
- 换/加图床 = 加一个 `XxxProvider` 子类 + 在 `registry.REGISTER` 里登记一行，**业务代码零改动**。

### 5.2 图床扩展方式（新增一个图床要写什么）

```python
# gallery/storage/smms_provider.py
from .base import FieldSpec, StorageProvider

class SmmsProvider(StorageProvider):
    name = "smms"                     # 唯一标识，入库用
    display_name = "SM.MS 图床"        # 页面展示名
    fields = [                        # ★ 字段模板：同时驱动「表单渲染」和「启用校验」
        FieldSpec("token", "API Token", secret=True),
    ]

    def upload(self, key, data, mime_type=None): ...   # 上传，返回 (key, url)
    def delete(self, key): ...                          # 删除
    def public_url(self, key): ...                      # 拼原图链接
    # thumb_url 可不实现，默认返回原图
```

最后在 `registry.py` 的 `REGISTER` 列表加上 `SmmsProvider` —— 配置页会自动多出一个选项，表单自动生成，**不用改任何模板或视图**。

### 5.3 数据模型

**StorageConfig（图床配置）**

| 字段 | 说明 |
| --- | --- |
| `provider` | 图床标识（`qiniu` / `aliyun` / `tencent` / `github`） |
| `display_name` | 自定义备注名（如「主站七牛」） |
| `is_active` | 是否启用；`save()` 里做了**单一启用约束**，启用新的会自动停用旧的 |
| `config` | JSONField，存该图床的字段值（结构由 `FieldSpec` 决定） |

**ImageAsset（图片资源）**

| 字段 | 说明 |
| --- | --- |
| `original_name` | 上传时的原始文件名，用于展示与搜索 |
| `local_name` | 实际落盘文件名（重名自动加 `(1)`） |
| `object_key` | 图床对象名（原 `qiniu_key`，多图床后改名），时间戳命名 |
| `provider` | ★ 这张图存在**哪个图床**（用于筛选与删除时选对 SDK） |
| `cdn_url` | 原图访问链接 |
| `size` / `mime_type` | 文件大小 / MIME |
| `tags` | M2M → Tag |
| `status` | `active` 正常 / `deleted` 已进回收站 |
| `uploaded_at` / `deleted_at` | 上传 / 删除时间 |

**Tag（标签）**：`name`（唯一）、`created_at`。

### 5.4 时间戳重命名规则

由 `StorageProvider.build_key()` 生成（各图床可覆写前缀）：

```
img/20260903_002758_191_99fb.png
    └─ 年月日_时分秒_毫秒 └─ 4位随机(防并发碰撞) └─ 保留原扩展名
```

映射关系体现为 `original_name ↔ object_key ↔ cdn_url` 同存一行，页面三者都可见、都可搜索。

### 5.5 图片生命周期

```
        上传
         │
         ▼
   ┌───────────┐   删除(单条/批量)    ┌───────────┐
   │  active   │ ───────────────────▶ │  deleted  │
   │  uploads/ │                      │  recycle/ │
   │  图床有   │ ◀─────────────────── │  图床无   │
   └───────────┘   恢复(重新上传)      └───────────┘
         │                                   │
         └──────────── 彻底删除 ──────────────┘
                  删本地文件 + 删数据库记录
```

- **删除** = 调图床删除对象 + 本地文件 `uploads/ → recycle/` + 标记 `deleted`（本地不丢）；
- **恢复** = 把 `recycle/` 的本地文件**重新上传**到当前启用的图床（生成新 key 与新链接）；
- **彻底删除** = 删本地文件 + 删数据库记录，不可恢复。

### 5.6 容错设计

| 场景 | 处理 |
| --- | --- |
| 没有启用中的图床 | 首页显示提示条并给出「去配置」入口；上传接口返回 400 + 中文原因 |
| 图床必填项缺失 | 配置页启用按钮不可用 + 行内标红报错，说明缺哪个字段 |
| 上传图床失败 | **回滚已落盘的本地文件**，不留脏数据 |
| 云端对象已不存在 | 视为删除成功，不报错（避免回收站卡死） |
| 非图片格式 | 扩展名白名单校验，返回明确错误 |
| 本地文件重名 | 自动追加 `(1)` `(2)` |
| 未登录访问接口 | 302 跳登录页；前端识别非 JSON 响应并提示"登录状态已失效" |
| SDK 未安装 | 惰性导入 + 明确报错（提示装哪个包），不影响其它图床 |

---

## 六、配置项

图床密钥**推荐在页面上配**（存数据库），`.env` 只放服务级配置。

| 变量 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `DJANGO_DEBUG` | ❌ | `True` | 生产务必 `False`（compose 里已强制覆盖） |
| `DJANGO_SECRET_KEY` | ❌ | 开发默认值 | **生产必须换成随机长字符串** |
| `DJANGO_ALLOWED_HOSTS` | ❌ | `127.0.0.1,localhost` | 允许访问的域名，逗号分隔 |
| `DJANGO_DB_PATH` | ❌ | 项目内 `db.sqlite3` | 数据库路径（容器里指向持久化卷） |
| `PICHOME_API_TOKEN` | ❌ | 空 | ★ 对外 API 令牌。**留空 = 不校验**（仅建议本机）；填值后 CLI 必须带令牌 |
| `PICHOME_API_URL` | ❌ | `http://127.0.0.1:28080` | CLI 默认要访问的服务地址 |
| `QINIU_ACCESS_KEY` 等 | ❌ | — | 仅用于首次 `initstorage` 播种七牛云配置，之后以页面配置为准 |

各图床在配置页需要填的字段：

| 图床 | 必填 | 可选 |
| --- | --- | --- |
| 七牛云 Kodo | AccessKey、SecretKey、Bucket、Domain | 缩略图样式（如 `?imageView2/2/w/400/q/75`） |
| 阿里云 OSS | AccessKeyId、AccessKeySecret、Endpoint、Bucket | 自定义域名、缩略图样式（`?x-oss-process=image/resize,w_400`） |
| 腾讯云 COS | SecretId、SecretKey、Region、Bucket | 自定义域名、缩略图样式（`?imageMogr2/thumbnail/400x`） |
| GitHub 仓库 | Token（repo 权限）、`owner/name`、分支、存放目录 | Raw 基础地址、提交者名称 / 邮箱 |

---

## 七、接口一览

除 `/login/`、`/logout/`、`/api/v1/*` 外，**所有页面与接口都需要登录**。
接口统一返回 JSON：`{"ok": true, ...}` 或 `{"ok": false, "error": "原因"}`。

### 7.1 页面

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/` | `q` 搜索词、`tag` 标签、`provider` 图床 | 图库首页 |
| GET | `/history/` | — | ★ 上传历史（时间倒序） |
| GET | `/settings/storage/` | `edit` 配置 id | ★ 图床配置页 |
| GET | `/recycle/` | `q` | 回收站 |
| GET | `/login/` `/logout/` | — | 登录 / 退出 |

### 7.2 站内接口（需登录 + CSRF）

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| POST | `/upload` | `file`、`tags` | 上传一张（多图时前端循环调用） |
| POST | `/settings/storage/` | `provider`、各字段、`action=save/activate/delete` | 保存 / 启用 / 删除图床配置 |
| POST | `/delete` | `id` 或 `key` | 删除单张 → 进回收站 |
| POST | `/delete_batch` | `id[]` 或 `key[]` | 批量删除 |
| POST | `/delete_remote` | `key` | 按对象名直接删云端 |
| POST | `/set_tags` | `id[]`/`key[]`、`tags` | 设置标签（覆盖式） |
| POST | `/recycle/restore` `/recycle/restore_batch` | `id`/`key` | 恢复（重新上传图床） |
| POST | `/recycle/purge` `/recycle/purge_batch` | `id`/`key` | 彻底删除 |

### 7.3 对外 API（给 CLI / AI Agent）

```
POST /api/v1/upload
Content-Type: multipart/form-data
```

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `file` | ✅ | 图片文件 |
| `tags` | ❌ | 标签，逗号分隔 |

鉴权（三选一，取决于服务是否设了 `PICHOME_API_TOKEN`）：

- 未设 `PICHOME_API_TOKEN`：**匿名可调**（默认，便于本机 / 内网自用）；
- 已设：请求头 `Authorization: Bearer <token>` 或 query `?token=<token>`。

该接口 `csrf_exempt`，不需要 Cookie 会话，专为脚本设计。返回：

```json
{
  "ok": true,
  "id": 4,
  "original_name": "photo.png",
  "object_key": "img/20260903_002758_191_99fb.png",
  "provider": "qiniu",
  "provider_display": "七牛云 Kodo",
  "cdn_url": "https://img.example.com/img/20260903_002758_191_99fb.png",
  "thumb_url": "https://img.example.com/img/20260903_002758_191_99fb.png?imageView2/2/w/400/q/75",
  "size": 70,
  "tags": ["CLI验证"],
  "uploaded_at": "2026-09-03 00:27:58",
  "markdown": "![photo.png](https://img.example.com/img/20260903_002758_191_99fb.png \"photo.png\")",
  "html": "<img src=\"https://img.example.com/img/20260903_002758_191_99fb.png\"/>"
}
```

失败时 `ok=false` + `error`，HTTP 状态码 400 / 401 / 500。

---

## 八、命令行 `pichome`

一个零依赖单文件 CLI（只用标准库），**两种模式自动适配**：

| 模式 | 何时用 | 原理 |
| --- | --- | --- |
| HTTP（默认） | 宿主机 / 别的机器，服务已在跑 | 本地读文件字节 → POST 到 `/api/v1/upload`，**不需要共享目录** |
| `--in-process` | 在容器内，或本地已配好 Django 环境 | `django.setup()` 后直接调 `upload_image()`，零网络开销 |

```bash
# 1) 最常用：服务已由 docker compose 起着（宿主机端口 28080）
python pichome.py --upload ./photo.png

# 2) 带标签
python pichome.py --upload ./photo.png --tags "风景,旅行"

# 3) 指定服务地址（例如本地 runserver 在 8000）
python pichome.py --upload ./photo.png --url http://127.0.0.1:8000

# 4) 服务设了令牌
PICHOME_API_TOKEN=xxxx python pichome.py --upload ./photo.png
python pichome.py --upload ./photo.png --token xxxx

# 5) 文件已经在容器里（容器内模式）
docker compose exec -T web python pichome.py --in-process --upload /app/inbox/photo.png
```

约定：

- **stdout 只输出一行 JSON**（便于 `jq` / agent 解析），成功 `exit 0`，失败 `exit 1` 且 JSON 里带 `error`；
- 目前**一次一张**（按需求），批量就外层循环；
- 拿链接示例：`python pichome.py --upload a.png | jq -r .markdown`。

### Docker Compose 下命令行怎么交互？

两条路径，按文件在哪儿选：

1. **文件在宿主机（绝大多数情况，agent 就用这条）** → 用默认 HTTP 模式。CLI 在宿主机读字节走 HTTP 发进容器，**不需要把目录挂进容器**：
   ```bash
   docker port pichome-web 8000      # 确认宿主端口，默认 28080
   python pichome.py --upload ./photo.png
   ```
2. **文件已在容器里** → `docker compose exec -T web python pichome.py --in-process --upload /app/xxx.png`。

---

## 九、AI Agent 用的 Skill

CLI 已按 skill-creator 规范封装成标准 Skill，放在项目内：

```
.workbuddy/skills/pichome-upload/
├── SKILL.md                 # 触发条件 / 用法 / 输出格式
└── scripts/pichome.py       # CLI（与根目录同步）
```

安装（拷到用户级 skills 目录即可全局可用）：

```bash
cp -R .workbuddy/skills/pichome-upload ~/.workbuddy/skills/
```

之后对 agent 说「把这张图传到 picHome 并给我 markdown 链接」，它会调用该 Skill 拿到 JSON 结果直接嵌入回复。

> 改了根目录 `pichome.py` 记得同步：`cp pichome.py .workbuddy/skills/pichome-upload/scripts/pichome.py`

---

## 十、页面与前端交互

- **首页 `/`**：上传坞（点击选择 / 拖拽 / 粘贴 + 标签输入 + 预览网格）→ **图床筛选 chips** → 标签筛选 → 搜索 → 批量操作条 → 卡片网格。
- **卡片**：复选框、缩略图、**图床角标**、文件名（过长悬浮显示全名 + 复制按钮）、标签 chips、大小/时间、**CDN / MD / HTML 三行链接各带复制**、标签/查看/删除按钮。
- **拖拽上传**：拖动图片进入窗口时全屏出现半透明投放蒙层与提示文案，松手即进入上传队列；拖离自动消失，避免误触。
- **剪贴板上传**：页面任意处 `Ctrl/Cmd+V` 直接读取剪贴板图片；也可点上传坞的「粘贴」按钮（用于用户不习惯快捷键的场景）。
- **上传历史 `/history/`**：时间倒序列表，含图床、时间、三种链接复制。
- **图床设置 `/settings/storage/`**：左侧已有配置列表（含启用状态、启用/编辑/删除），右侧表单**按所选图床的字段模板自动渲染**；密钥字段用密码框；校验失败时字段标红并给出中文原因。
- **登录页**：卡片整体上移居中，`overflow: hidden` **禁止纵向滚动**。
- **弹窗 / Toast**：`confirmDialog()` / `promptDialog()` 返回 Promise，支持 ESC、点遮罩关闭、回车提交；Toast 右下角 2.6 秒自动消失。

支持格式：`.jpg .jpeg .png .gif .webp .bmp .heic .svg`（白名单见 `views.py` 的 `ALLOWED_EXT`）。

---

## 十一、Docker Compose 部署

内置 `Dockerfile` + `docker-compose.yml`，单容器上线，**无需额外 Nginx**（Whitenoise 经 Gunicorn 托管静态文件）。

- `docker-entrypoint.sh` 启动顺序 = 迁移数据库 → 首次建管理员（`inituser`）→ **播种图床配置（`initstorage`）** → 收集静态文件 → 拉起 Gunicorn。
- compose 项目名 `pichome`，容器名 `pichome-web`，宿主端口 **28080** → 容器 8000。
- 数据卷：`pichome_db_data`（SQLite）、`pichome_media_data`（uploads + recycle）。

```bash
docker compose up -d --build            # 构建并启动
open http://localhost:28080/login/      # 默认 admin / admin12345，建议立刻改
docker compose exec web python manage.py inituser --password 你的强密码

docker compose logs -f                  # 看日志
docker compose down                     # 停止（数据卷保留）
docker port pichome-web 8000            # 查宿主端口
```

### 从旧版（`qiniu-gallery`）升级

项目更名后卷名前缀也变了，把旧数据拷过去即可（旧卷保留作备份）：

```bash
docker compose -p qiniu-gallery down
docker run --rm -v qiniu-gallery_db_data:/from -v pichome_db_data:/to \
  alpine sh -c 'cp -a /from/. /to/'
docker run --rm -v qiniu-gallery_media_data:/from -v pichome_media_data:/to \
  alpine sh -c 'cp -a /from/. /to/'
docker compose up -d --build
```

### 部署到服务器注意点

1. `DJANGO_DEBUG` 已在 compose 中强制 `False`；
2. **必须**把域名 / 公网 IP 加进 `DJANGO_ALLOWED_HOSTS`，否则 `DisallowedHost`；
3. `DJANGO_SECRET_KEY` 换成随机长字符串；
4. **公网暴露时务必设置 `PICHOME_API_TOKEN`**，否则 `/api/v1/upload` 匿名可用；
5. 备份：`docker compose exec web cp /app/data/db.sqlite3 /app/data/backup.sqlite3` 后拷出；
6. 多人并发时把 SQLite 换成 PostgreSQL。

---

## 十二、常见问题

**Q：提示"尚未配置可用图床"？**
A：去 齿轮 → 图床设置，填完必填项并点「启用」。必填缺失时会明确指出缺哪个字段。

**Q：图传上去了但列表显示不出来？**
A：检查配置里的域名是否带 `https://`、是否已 CNAME / 备案生效；私有空间需要签名访问（当前按公开空间设计）。

**Q：缩略图裂图？**
A：缩略图样式是可选项，留空即用原图；用样式需对应云商开通图片处理。

**Q：能同时用多个图床吗？**
A：配置可以存多条，但**同一时刻只有一个启用**（新图往启用的那个传）。历史图片会记住各自的 `provider`，删除/恢复时按自己的图床处理，首页也能按图床筛选。

**Q：CLI 报 403 / 401？**
A：服务设了 `PICHOME_API_TOKEN`，加 `--token` 或导出同名环境变量。

**Q：CLI 连不上服务？**
A：默认地址是 `http://127.0.0.1:28080`（compose 映射）。本地 `runserver` 请用 `--url http://127.0.0.1:8000`，或设 `PICHOME_API_URL`。

**Q：忘了密码？**
A：`python manage.py inituser --username admin --password 新密码`。

---

## 十三、后续可做

- **桌面客户端**：`gallery/storage/` 已与 Django 解耦，可直接被 PySide/Tauri 壳复用；上传核心若要脱离 Django ORM，只需把 `upload_service` 里的写库部分抽成可替换的 repository。
- **CLI 批量上传 / 目录监听**：当前按需求只做单张。

---

## 十四、维护记录

| 日期 | 内容 |
| --- | --- |
| 2026-08-21 | 初版：上传（多图/预览/时间戳命名/CDN 链接）、删除 + 回收站、简约风前端 |
| 2026-08-31 | 增强：登录鉴权、图片标签、批量删除/恢复/彻底删除、自定义弹窗、缩略图样式 |
| 2026-09-01 | Docker Compose 部署：Dockerfile + 入口脚本 + 命名卷持久化，Whitenoise + Gunicorn |
| 2026-09-02 | **改名 picHome + 多图床架构改造**（`dev-0902`）：存储抽象层（七牛/阿里/腾讯/GitHub）、页面化图床配置与校验、按图床筛选、上传历史页、Markdown/HTML 链接、长名悬浮+复制、拖拽与剪贴板上传、对外 API `/api/v1/upload`、命令行 `pichome`、pichome-upload Skill、登录页布局修正 |
