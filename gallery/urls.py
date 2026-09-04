from django.urls import path

from . import views

app_name = "gallery"

urlpatterns = [
    # 登录 / 登出（无需登录即可访问）
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),

    # 页面
    path("", views.index, name="index"),
    path("recycle/", views.recycle, name="recycle"),
    path("history/", views.history, name="history"),
    path("settings/storage/", views.storage_settings, name="storage_settings"),
    path("settings/account/", views.account, name="account"),
    path("settings/account-avatar/", views.account_avatar, name="account_avatar"),

    # 本地文件预览（回收站卡片用本地文件渲染预览图）
    path("asset/<int:pk>/local-image/", views.local_image, name="local_image"),

    # 图库接口
    path("upload", views.upload, name="upload"),
    path("delete", views.delete_asset, name="delete"),
    path("delete_batch", views.delete_batch, name="delete_batch"),
    path("delete_remote", views.delete_remote, name="delete_remote"),
    path("set_tags", views.set_tags, name="set_tags"),

    # 统一对外 API（CLI / AI Agent）
    path("api/v1/upload", views.api_upload, name="api_upload"),

    # 背景图代理（公开，供所有页面动态获取随机背景）
    path("api/bg/", views.bg_proxy, name="bg_proxy"),

    # 回收站接口
    path("recycle/restore", views.restore, name="restore"),
    path("recycle/restore_batch", views.restore_batch, name="restore_batch"),
    path("recycle/purge", views.purge, name="purge"),
    path("recycle/purge_batch", views.purge_batch, name="purge_batch"),
]
