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


# ===== Django 基础 =====
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-insecure-key-please-change")
DEBUG = os.getenv("DJANGO_DEBUG", "True") == "True"
ALLOWED_HOSTS = [
    h.strip() for h in os.getenv("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if h.strip()
]

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
            ],
        },
    },
]

WSGI_APPLICATION = "pichome_web.wsgi.application"


# ===== 数据库（开发用 SQLite）=====
# 数据库文件路径可用 DJANGO_DB_PATH 覆盖（Docker 部署时指向持久化卷目录）。
# 本地开发不设置该变量，则默认用项目根目录下的 db.sqlite3，行为不变。
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
STATIC_ROOT = BASE_DIR / "static_collected"

MEDIA_URL = "media/"
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
