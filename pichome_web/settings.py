"""
Django 项目配置。
七牛云相关密钥通过环境变量 / .env 文件注入，不写死在代码里。
"""
from pathlib import Path

import os

from dotenv import load_dotenv

# 读取项目根目录下的 .env（如果存在）
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent


# ===== 桌面模式（Tauri / 本地独立运行）=====
# 由环境变量 PICHOME_DESKTOP=1 开启；开启后数据库 / 媒体 / 静态根目录
# 统一落到「用户数据目录」，不再依赖项目根目录，适合打包成桌面 App。
PICHOME_DESKTOP = os.getenv("PICHOME_DESKTOP", "0") == "1"
DESKTOP_PORT = int(os.getenv("PICHOME_DESKTOP_PORT", "14567"))
if PICHOME_DESKTOP:
    # macOS: ~/Library/Application Support/pichome；可用 PICHOME_DATA_DIR 覆盖
    DESKTOP_DATA_DIR = Path(
        os.getenv("PICHOME_DATA_DIR")
        or os.path.expanduser("~/Library/Application Support/pichome")
    )
    DESKTOP_DATA_DIR.mkdir(parents=True, exist_ok=True)
else:
    DESKTOP_DATA_DIR = None


# ===== Django 基础 =====
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-insecure-key-please-change")
DEBUG = os.getenv("DJANGO_DEBUG", "True") == "True"
ALLOWED_HOSTS = [
    h.strip() for h in os.getenv("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if h.strip()
]

# ===== 反向代理(HTTPS)下的 CSRF / 安全配置 =====
if PICHOME_DESKTOP:
    # 桌面模式：本地 http 直连（无反向代理）。
    # 必须显式声明带端口的可信源，否则 Django 6.1 的 Origin 校验会因
    # 浏览器 Origin(http://127.0.0.1:PORT) 与 good_origin(无端口) 不一致而 403。
    SECURE_PROXY_SSL_HEADER = None
    CSRF_TRUSTED_ORIGINS = [
        f"http://127.0.0.1:{DESKTOP_PORT}",
        f"http://localhost:{DESKTOP_PORT}",
    ]
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False
else:
    # nginx 以 HTTPS 对外、HTTP 对内转发；必须告诉 Django 真实协议是 https，
    # 否则 is_secure() 为 False，浏览器 POST 携带的 Origin: https://... 会与
    # good_origin(http://...) 不匹配，触发 CSRF 403。
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    # 显式声明可信源（涵盖 ALLOWED_HOSTS 中所有主机，统一用 https）
    CSRF_TRUSTED_ORIGINS = ["https://" + h for h in ALLOWED_HOSTS]
    # 生产环境(DEBUG=False)下让会话/Cookie 仅通过 HTTPS 传输
    SESSION_COOKIE_SECURE = not DEBUG
    CSRF_COOKIE_SECURE = not DEBUG

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "gallery",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # 生产环境由 Gunicorn 直接提供静态文件，无需 Nginx
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # 演示账号只读拦截：放在认证中间件之后，可拿到 request.user
    "gallery.middleware.DemoReadOnlyMiddleware",
]

ROOT_URLCONF = "pichome_web.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "gallery.context_processors.user_profile",
                "gallery.context_processors.desktop_flag",
            ],
        },
    },
]

WSGI_APPLICATION = "pichome_web.wsgi.application"


# ===== 数据库（开发用 SQLite）=====
# 数据库文件路径可用 DJANGO_DB_PATH 覆盖（Docker 部署时指向持久化卷目录）。
# 本地开发不设置该变量，则默认用项目根目录下的 db.sqlite3，行为不变。
# 桌面模式：数据库落到用户数据目录（可写）；否则用 DJANGO_DB_PATH 或项目根目录
if PICHOME_DESKTOP:
    DB_PATH = str(DESKTOP_DATA_DIR / "db.sqlite3")
else:
    DB_PATH = os.getenv("DJANGO_DB_PATH", str(BASE_DIR / "db.sqlite3"))
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": DB_PATH,
    }
}


# ===== 密码校验（开发环境放宽）=====
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# ===== 国际化（中文）=====
LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True


# ===== 静态资源 / 媒体文件 =====
STATIC_URL = "static/"
if PICHOME_DESKTOP:
    # 静态/媒体都落到用户数据目录（MEDIA 需要可写；STATIC 由 collectstatic 生成）
    STATIC_ROOT = DESKTOP_DATA_DIR / "static_collected"
    MEDIA_ROOT = DESKTOP_DATA_DIR / "media"
else:
    STATIC_ROOT = BASE_DIR / "static_collected"
    MEDIA_ROOT = BASE_DIR / "media"

# 生产环境（DEBUG=False）下，让 Whitenoise 压缩并提供 STATIC_ROOT 里的静态文件
STATICFILES_STORAGE = "whitenoise.storage.CompressedStaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ===== 七牛云对象存储配置 =====
QINIU_ACCESS_KEY = os.getenv("QINIU_ACCESS_KEY", "")
QINIU_SECRET_KEY = os.getenv("QINIU_SECRET_KEY", "")
QINIU_BUCKET = os.getenv("QINIU_BUCKET", "")
QINIU_DOMAIN = os.getenv("QINIU_DOMAIN", "").rstrip("/")

# 列表缩略图使用的七牛云处理样式，留空表示直接用原图。
# 例：?imageView2/2/w/400/q/75   或空间里预置的样式名 -thumb
QINIU_THUMB_STYLE = os.getenv("QINIU_THUMB_STYLE", "?imageView2/2/w/400/q/75")


# ===== 对外 API（CLI / AI Agent 上传）访问令牌 =====
# 设置后，/api/v1/upload 必须携带此令牌（Header: Authorization: Bearer <token>
# 或 query 参数 ?token=<token>）才能调用，否则返回 401。
# 留空时：仅在 DEBUG=True（开发）下允许匿名调用；生产环境务必设置，避免被滥用。
PICHOME_API_TOKEN = os.getenv("PICHOME_API_TOKEN", "")


# ===== 登录鉴权 =====
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
