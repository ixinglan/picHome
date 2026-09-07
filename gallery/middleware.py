"""演示账号只读中间件。

核心目的：让标记为 is_demo 的用户「只能登录浏览，不能做任何写操作」。
- 即使前端把操作按钮藏了，这里也在服务端兜底拦截，绕过 UI 直接 POST 也会被 403。
- 只拦截写方法（POST/PUT/PATCH/DELETE），GET/HEAD 等读请求全部放行（浏览/预览/历史/导出）。
- 白名单放行认证相关与公开读接口：/login/、/logout/（演示账号也得能登入退出）、
  /api/bg/（公开随机背景，GET 读）。
"""

from django.contrib.auth.models import User
from django.http import HttpResponseForbidden, JsonResponse

# 演示账号允许通过的路径（均为认证 / 公开读，不涉及数据写）
DEMO_EXEMPT_PATHS = ("/login/", "/logout/", "/api/bg/")
# 只读方法（放行）
DEMO_SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}


def _is_demo(user):
    if not user or not user.is_authenticated:
        return False
    try:
        profile = user.profile
    except Exception:
        # user.profile 尚未创建（极端情况）：非演示账号，放行
        return False
    return bool(profile and profile.is_demo)


class DemoReadOnlyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # AuthenticationMiddleware 已在前面把 request.user 准备好
        if _is_demo(getattr(request, "user", None)):
            method = (request.method or "GET").upper()
            path = request.path
            # 写方法且不在白名单 → 拒绝
            if method not in DEMO_SAFE_METHODS and path not in DEMO_EXEMPT_PATHS:
                # 区分 AJAX / JSON 请求与普通页面，返回合适的 403
                accept = request.META.get("HTTP_ACCEPT", "")
                xrw = request.META.get("HTTP_X_REQUESTED_WITH", "")
                is_ajax = xrw == "XMLHttpRequest" or "application/json" in (
                    request.content_type or ""
                )
                if is_ajax or "application/json" in accept:
                    return JsonResponse(
                        {"error": "演示账号仅可浏览，不能执行任何操作"}, status=403
                    )
                return HttpResponseForbidden("演示账号仅可浏览，不能执行任何操作")
        return self.get_response(request)
