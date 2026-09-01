# 七牛云图库（Qiniu Gallery）

一个用 Django 写的**七牛云对象存储图床工具**：网页端上传图片到七牛云、拿到 CDN 链接、按标签分类管理、删除后自动进回收站可恢复。

服务端渲染（Django Template）+ 原生 JS 增强，**不做前后端分离**，单进程跑起来就能用。

---

## 一、功能特性

| 分类 | 能力 |
| --- | --- |
| 上传 | 单张 / 多张、点击选择或拖拽、上传前本地缩略图预览、实时进度 |
| 命名 | 本地保留原始文件名；上传七牛云时**自动重命名为时间戳**，数据库保存两者映射关系 |
| CDN | 每张图展示七牛云 CDN 链接，一键复制；列表用七牛云处理样式生成缩略图，省流量 |
| 分类 | 图片标签（上传时打标签、卡片改标签、批量改标签）、标签筛选栏带数量统计 |
| 搜索 | 按本地原名或七牛云对象名模糊搜索，可与标签筛选叠加 |
| 删除 | 单张删除、按对象名直接删除、**勾选批量删除**；均带自定义确认弹窗 |
| 回收站 | 删除只移除七牛云对象，**本地文件移入回收站**；支持恢复（重新上传七牛云）与彻底删除，单条/批量均可 |
| 鉴权 | 全站登录保护，含独立登录页、退出登录、一键初始化账号 |
| 交互 | 自定义 Modal 弹窗（替代原生 confirm/prompt）、Toast 提示、响应式网格布局 |

---

## 二、技术栈

| 组件 | 版本 / 说明 |
| --- | --- |
| Python | 3.14.3（pyenv 管理） |
| Django | 6.1 |
| qiniu SDK | 7.18（官方 Python SDK） |
| python-dotenv | 1.2.3（读取 `.env`） |
| 数据库 | SQLite（`db.sqlite3`，开箱即用，无需额外装数据库） |
| 前端 | Django Template + 原生 CSS / JS，无任何前端构建工具 |

依赖见 `requirements.txt`：`django>=5.2`、`qiniu>=7.10`、`python-dotenv>=1.0`。

---

## 三、快速开始

### 1. 准备虚拟环境

```bash
cd "/Users/ixiaoqiang/WorkBuddy/七牛云"

# 用 pyenv 的 Python 建项目级虚拟环境
/Users/ixiaoqiang/.pyenv/shims/python3 -m venv .venv

# 安装依赖
.venv/bin/pip install -r requirements.txt
```

### 2. 配置七牛云

```bash
cp .env.example .env
```

编辑 `.env`，填入四项必填配置（密钥在 [七牛云控制台](https://portal.qiniu.com) → 个人中心 → 密钥管理 获取）：

```env
QINIU_ACCESS_KEY=你的AccessKey
QINIU_SECRET_KEY=你的SecretKey
QINIU_BUCKET=你的空间名
QINIU_DOMAIN=https://你的空间绑定域名
```

> 没填也能启动：页面会显示黄色提示条，上传接口返回友好错误，不会崩溃。

### 3. 建表

```bash
.venv/bin/python manage.py migrate
```

### 4. 创建登录账号

```bash
.venv/bin/python manage.py inituser                                   # 默认 admin / admin12345
.venv/bin/python manage.py inituser --username xq --password 你的密码   # 自定义
```

> 该命令可重复执行，已存在则重置密码。

### 5. 启动

```bash
.venv/bin/python manage.py runserver
```

浏览器打开 <http://127.0.0.1:8000/> → 用 `admin / admin12345` 登录（若未改密码）。

常用命令：

```bash
.venv/bin/python manage.py runserver 0.0.0.0:8080   # 换端口 / 允许局域网访问
.venv/bin/python manage.py createsuperuser          # 也可用 Django 原生命令建账号
.venv/bin/python manage.py shell                    # 交互式调试
```

---

## 四、目录结构

```
七牛云/
├── manage.py                      # Django 命令行入口
├── requirements.txt               # 依赖清单
├── .env.example                   # 配置模板（复制成 .env 后填写）
├── .env                           # 真实密钥（已 gitignore，勿提交）
├── db.sqlite3                     # SQLite 数据库（自动生成）
├── README.md
│
├── qiniu_tool/                    # 项目配置包
│   ├── settings.py                # 全局配置（含七牛云 / 登录 / 媒体目录）
│   ├── urls.py                    # 根路由，DEBUG 时托管 media/
│   ├── wsgi.py / asgi.py          # 部署入口
│
├── gallery/                       # 图库应用（核心业务）
│   ├── models.py                  # ImageAsset（图片）、Tag（标签）
│   ├── views.py                   # 页面视图 + AJAX 接口
│   ├── urls.py                    # 应用路由
│   ├── admin.py                   # Django Admin 注册
│   ├── qiniu_client.py            # 七牛云 SDK 封装层（上传/删除/拼链接）
│   ├── management/commands/
│   │   └── inituser.py            # 一键创建/重置登录账号
│   ├── migrations/                # 数据库迁移（0001 建表、0002 加标签）
│   ├── templates/gallery/
│   │   ├── base.html              # 母版：顶栏 + 通用弹窗 + Toast
│   │   ├── index.html             # 图库首页
│   │   ├── recycle.html           # 回收站
│   │   └── login.html             # 登录页
│   └── static/gallery/
│       ├── css/style.css          # 全部样式（现代简约风）
│       └── js/app.js              # 全部交互（上传/选择/批量/弹窗）
│
└── media/                         # 本地文件仓库（自动生成，已 gitignore）
    ├── uploads/                   # 正常图片（保留原始文件名）
    └── recycle/                   # 回收站（删除后移到这里）
```

---

## 五、架构设计

### 5.1 分层

```
浏览器
  │  HTTP（页面 GET / 接口 POST）
  ▼
Django URL → views.py ─────────┐
                                │  业务编排：校验 → 落本地 → 传云端 → 写库
                                ▼
                        qiniu_client.py（七牛云 SDK 封装）
                                │
                                ▼
                        七牛云对象存储
```

- **`views.py`** 只做业务编排，不直接碰 SDK；
- **`qiniu_client.py`** 是唯一的七牛云出入口（上传 / 删除 / 拼链接），方便替换存储后端或单测时 mock；
- **本地磁盘 + 七牛云双写**：本地留底用于预览和回收站恢复，云端负责对外访问。

### 5.2 数据模型

**ImageAsset（图片资源）**

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `original_name` | varchar | 上传时的**原始文件名**，始终不变，用于展示和搜索 |
| `local_name` | varchar | 实际落盘文件名（同名时自动加 `(1)` 后缀） |
| `qiniu_key` | varchar(unique) | 七牛云对象名，**时间戳重命名** |
| `cdn_url` | varchar | 七牛云原图访问链接 |
| `size` | int | 文件大小（字节） |
| `mime_type` | varchar | MIME 类型 |
| `tags` | M2M → Tag | 分类标签 |
| `status` | varchar | `active` 正常 / `deleted` 已移入回收站 |
| `uploaded_at` | datetime | 上传时间 |
| `deleted_at` | datetime | 删除时间（可为空） |

**Tag（标签）**：`name`（唯一）、`created_at`。

### 5.3 时间戳重命名规则

由 `qiniu_client.build_key()` 生成：

```
img/20260831_181856_708_28ff.png
    └─ 年月日_时分秒_毫秒 └─ 4位随机(防并发碰撞) └─ 保留原扩展名
```

**映射关系**体现为 `original_name ↔ qiniu_key ↔ cdn_url` 三条字段同存一行：
本地文件名不变，云端对象名是时间戳，页面上三者都可见、都可搜索。

### 5.4 图片生命周期

```
        上传
         │
         ▼
   ┌───────────┐   删除(单条/批量)    ┌───────────┐
   │  active   │ ───────────────────▶ │  deleted  │
   │  uploads/ │                      │  recycle/ │
   │  七牛云有 │ ◀─────────────────── │  七牛云无 │
   └───────────┘   恢复(重新上传云端)  └───────────┘
         │                                   │
         └──────────── 彻底删除 ──────────────┘
                  删本地文件 + 删数据库记录
```

关键点：

- **删除** = 调七牛云删除对象 + 本地文件 `uploads/ → recycle/` + 记录标记 `deleted`（本地文件不丢）；
- **恢复** = 把 `recycle/` 里的本地文件**重新上传**到七牛云（生成新 key 和新链接）+ 移回 `uploads/`；
- **彻底删除** = 删 `recycle/` 文件 + 删数据库记录，不可恢复。

### 5.5 容错设计

| 场景 | 处理 |
| --- | --- |
| 七牛云未配置 | 页面显示黄色提示条；上传接口返回 400 + 中文错误 |
| 上传云端失败 | **回滚已落盘的本���文件**，不留脏数据 |
| 云端对象已不存在（HTTP 612） | 视为删除成功，不报错（避免回收站卡死） |
| 非图片格式 | 校验扩展名白名单，返回明确错误 |
| 本地文件重名 | 自动追加 `(1)` `(2)` 后缀 |
| 未登录访问接口 | 302 跳登录页；前端识别非 JSON 响应并提示"登录状态已失效" |

---

## 六、配置项

全部在 `.env` 中配置，由 `settings.py` 通过 `os.getenv` 读取（`python-dotenv` 自动加载）。

| 变量 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `QINIU_ACCESS_KEY` | ✅ | — | 七牛云 AccessKey |
| `QINIU_SECRET_KEY` | ✅ | — | 七牛云 SecretKey |
| `QINIU_BUCKET` | ✅ | — | 存储空间名 |
| `QINIU_DOMAIN` | ✅ | — | 空间绑定域名（CDN 或测试域名），结尾不要带斜杠 |
| `QINIU_THUMB_STYLE` | ❌ | `?imageView2/2/w/400/q/75` | 列表缩略图处理样式，**留空则用原图** |
| `DJANGO_DEBUG` | ❌ | `True` | 调试模式，生产务必设为 `False` |
| `DJANGO_SECRET_KEY` | ❌ | 开发用默认值 | **生产必须换成随机长字符串** |
| `DJANGO_ALLOWED_HOSTS` | ❌ | `127.0.0.1,localhost` | 允许访问的域名，逗号分隔 |

**缩略图样式两种写法**（`thumb_url` 属性自动识别）：

```env
QINIU_THUMB_STYLE=?imageView2/2/w/400/q/75   # 处理参数式
QINIU_THUMB_STYLE=-thumb                     # 空间里预置的样式名（分隔符式）
```

> 列表卡片用缩略图；「查看」和「复制」按钮给的一直是**原图链接**。

---

## 七、接口一览

除 `/login/`、`/logout/` 外，**所有页面与接口都需要登录**（未登录访问页面会 302 跳登录页，访问接口同样被拦截）。
接口统一返回 JSON：`{"ok": true, ...}` 或 `{"ok": false, "error": "原因"}`。
POST 需带 CSRF（页面已内置，前端 `app.js` 自动从 cookie 读取并附带）。

| 方法 | 路径 | 参数 | 说明 |
| --- | --- | --- | --- |
| GET | `/` | `q` 搜索词、`tag` 标签名 | 图库首页 |
| GET | `/recycle/` | `q` 搜索词 | 回收站 |
| GET | `/login/` | — | 登录页 |
| GET | `/logout/` | — | 退出登录 |
| POST | `/upload` | `file`（文件）、`tags`（可选，逗号分隔） | 上传一张（前端多图时循环调用） |
| POST | `/delete` | `id` 或 `key`（二选一） | 删除单张 → 进回收站 |
| POST | `/delete_batch` | `id[]` 或 `key[]` | 批量删除 |
| POST | `/set_tags` | `id[]` 或 `key[]`、`tags` | 设置标签（覆盖式） |
| POST | `/recycle/restore` | `id` 或 `key` | 恢复单张（重新上传云端） |
| POST | `/recycle/restore_batch` | `id[]` 或 `key[]` | 批量恢复 |
| POST | `/recycle/purge` | `id` 或 `key` | 彻底删除单张 |
| POST | `/recycle/purge_batch` | `id[]` 或 `key[]` | 批量彻底删除 |

上传成功返回示例：

```json
{
  "ok": true,
  "id": 12,
  "original_name": "海边.jpg",
  "qiniu_key": "img/20260831_181856_708_28ff.jpg",
  "cdn_url": "https://cdn.example.com/img/20260831_181856_708_28ff.jpg",
  "thumb_url": "https://cdn.example.com/img/20260831_181856_708_28ff.jpg?imageView2/2/w/400/q/75",
  "size": 204815,
  "tags": ["风景"],
  "uploaded_at": "2026-08-31 18:18:56"
}
```

批量接口额外返回汇总，例如 `{"ok": true, "deleted": 2, "failed": [], "ids": [11, 12]}`。

---

## 八、页面与前端交互

- **首页 `/`**：上传区（拖拽 + 标签输入 + 预览网格）→ 标签筛选栏 → 搜索框 → 批量操作条 → 卡片网格。
- **卡片**：左上角复选框、缩略图、本地原名、七牛云对象名、标签 chips、大小/时间、CDN 链接 + 复制、标签/查看/删除按钮。
- **回收站 `/recycle/`**：同样支持搜索、全选、批量恢复、批量彻底删除。
- **弹窗**：`app.js` 里 `confirmDialog()` / `promptDialog()` 返回 Promise，支持 ESC 关闭、点遮罩关闭、回车提交；危险操作按钮为红色实心。
- **Toast**：右下角轻量提示，2.6 秒自动消失。

支持的文件格式：`.jpg .jpeg .png .gif .webp .bmp .heic .svg`（白名单见 `views.py` 的 `ALLOWED_EXT`）。

---

## 九、常见问题

**Q：上传提示"七牛云尚未配置"？**
A：检查 `.env` 四项是否填全，修改后需**重启服务**（`.env` 只在启动时读取）。

**Q：图片传上去了但列表里显示不出来？**
A：列表用的是 `QINIU_DOMAIN + key`。检查域名是否带 `https://`、是否已备案/CNAME 生效；若空间是**私有空间**，需额外做访问签名（当前版本按公开空间设计）。

**Q：缩略图裂图？**
A：`imageView2` 需要空间开通数据处理（默认开启）。不想用就把 `.env` 里 `QINIU_THUMB_STYLE` 留空，直接用原图。

**Q：删除后七牛云控制台还能看到文件？**
A：删除是同步调用七牛云删除接口，可能有 CDN 缓存延迟。确认回收站里有记录即表示已成功调用。

**Q：忘了密码？**
A：`python manage.py inituser --username admin --password 新密码` 重置即可。

**Q：端口被占用？**
A：`python manage.py runserver 8080` 换端口。

---

## 十、生产部署建议

当前配置面向本地开发，上生产前至少做这些：

1. `DJANGO_DEBUG=False`，并设置 `DJANGO_ALLOWED_HOSTS` 为真实域名；
2. 更换 `DJANGO_SECRET_KEY` 为随机长字符串（可用 `python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"` 生成）；
3. `python manage.py collectstatic` 收集静态文件，由 Nginx 托管；
4. `media/` 目录在 `DEBUG=False` 时 Django 不再托管，需 Nginx 直接服务或改走对象存储；
5. 用 Gunicorn/uWSGI 跑 `qiniu_tool.wsgi:application`，不要用 `runserver`；
6. 并发量大或多人使用时，把 SQLite 换成 PostgreSQL/MySQL；
7. 全站已登录保护，但仍建议加 HTTPS。

---

## 十一、维护记录

| 日期 | 内容 |
| --- | --- |
| 2026-08-21 | 初版：上传（多图/预览/时间戳命名/CDN 链接）、删除 + 回收站、简约风前端 |
| 2026-08-31 | 增强：登录鉴权、图片标签、批量删除/恢复/彻底删除、自定义弹窗、七牛云缩略图样式 |
