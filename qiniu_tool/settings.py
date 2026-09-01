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
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "qiniu_tool.urls"

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

WSGI_APPLICATION = "qiniu_tool.wsgi.application"


# ===== 数据库（开发用 SQLite）=====
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
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

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ===== 七牛云对象存储配置 =====
QINIU_ACCESS_KEY = os.getenv("QINIU_ACCESS_KEY", "")
QINIU_SECRET_KEY = os.getenv("QINIU_SECRET_KEY", "")
QINIU_BUCKET = os.getenv("QINIU_BUCKET", "")
QINIU_DOMAIN = os.getenv("QINIU_DOMAIN", "").rstrip("/")

# 列表缩略图使用的七牛云处理样式，留空表示直接用原图。
# 例：?imageView2/2/w/400/q/75   或空间里预置的样式名 -thumb
QINIU_THUMB_STYLE = os.getenv("QINIU_THUMB_STYLE", "?imageView2/2/w/400/q/75")


# ===== 登录鉴权 =====
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
