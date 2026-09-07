"""模板上下文处理器：为所有页面注入当前用户的资料信息。"""
import os

from django.urls import reverse

from .models import UserProfile


def user_profile(request):
    """已登录时注入 avatar_url / nickname；未登录返回空字典。"""
    if not request.user.is_authenticated:
        return {}

    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    avatar_url = ""
    if profile.avatar and os.path.exists(profile.avatar.path):
        avatar_url = reverse("gallery:account_avatar")

    return {
        "avatar_url": avatar_url,
        "nickname": profile.nickname or request.user.username,
        # 演示账号标记：模板据此隐藏写操作入口（真正的拦截由 DemoReadOnlyMiddleware 兜底）
        "is_demo": bool(profile.is_demo),
    }
