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

    # 图库接口
    path("upload", views.upload, name="upload"),
    path("delete", views.delete_asset, name="delete"),
    path("delete_batch", views.delete_batch, name="delete_batch"),
    path("delete_remote", views.delete_remote, name="delete_remote"),
    path("set_tags", views.set_tags, name="set_tags"),

    # 回收站接口
    path("recycle/restore", views.restore, name="restore"),
    path("recycle/restore_batch", views.restore_batch, name="restore_batch"),
    path("recycle/purge", views.purge, name="purge"),
    path("recycle/purge_batch", views.purge_batch, name="purge_batch"),
]
