"""
图库视图层（全部需要登录）。

页面：
- GET  /                 图库首页（按图床筛选 + 标签筛选 + 搜索 + 卡片网格）
- GET  /recycle/         回收站
- GET  /history/         上传历史（时间倒序）
- GET  /settings/storage/ 图床配置（多图床、必填校验、启用）
- GET  /login/           登录页
- GET  /logout/          退出登录

接口（AJAX，供页面使用）：
- POST /upload            上传单张图片（可带标签）
- POST /delete            删除单张（按 id 或对象名）
- POST /delete_batch      批量删除
- POST /delete_remote     直接删图床对象（不校验本地）
- POST /set_tags          设置标签
- POST /recycle/restore   恢复单张
- POST /recycle/restore_batch
- POST /recycle/purge     彻底删除单张
- POST /recycle/purge_batch

统一对外 API（供 CLI / AI Agent 调用，返回 JSON）：
- POST /api/v1/upload     上传单张，返回 {ok, markdown, cdn_url, html, ...}
"""
import json
import logging
import mimetypes
import os
import re
import shutil

import requests
from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_POST
from django.views.decorators.cache import never_cache

from .django_backend import get_active_provider
from .models import ImageAsset, StorageConfig, Tag, UserProfile
from .storage import ConfigError, StorageError, create_provider, list_specs
from .storage.exceptions import StorageError as _StorageError
from .upload_service import build_payload, upload_image

# 允许的图片扩展名
ALLOWED_EXT = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic", ".svg",
}


# ---------- 基础辅助 ----------
def _uploads_dir():
    d = settings.MEDIA_ROOT / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _recycle_dir():
    d = settings.MEDIA_ROOT / "recycle"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _unique_name(directory, name):
    if not (directory / name).exists():
        return name
    base, ext = os.path.splitext(name)
    i = 1
    while (directory / f"{base}({i}){ext}").exists():
        i += 1
    return f"{base}({i}){ext}"


def _apply_tags(asset, raw):
    if raw is None:
        return
    names = [n.strip() for n in re.split(r"[,，、\s]+", raw) if n.strip()]
    tags = []
    for n in names:
        tag, _created = Tag.objects.get_or_create(name=n)
        tags.append(tag)
    asset.tags.set(tags)


def _pick_assets(request, status):
    ids = [x for x in request.POST.getlist("id") if x.strip()]
    keys = [x.strip() for x in request.POST.getlist("key") if x.strip()]
    qs = ImageAsset.objects.filter(status=status)
    if ids:
        return qs.filter(id__in=ids)
    if keys:
        return qs.filter(object_key__in=keys)
    return qs.none()


# ---------- 核心操作（被单条/批量复用） ----------
def _soft_delete(asset, remote=True):
    """
    删图床对象 + 本地移入回收站 + 标记删除。
    remote=False 时跳过云端删除（用于云端已删、只需同步本地状态的场景）。
    """
    provider = get_active_provider() if remote else None
    if remote and provider is not None:
        try:
            provider.delete(asset.object_key)
        except Exception as e:
            return False, f"图床删除失败：{e}"

    src = _uploads_dir() / asset.local_name
    dst_name = _unique_name(_recycle_dir(), asset.local_name)
    dst = _recycle_dir() / dst_name
    if src.exists():
        shutil.move(str(src), str(dst))
        asset.local_name = dst_name
    asset.status = ImageAsset.STATUS_DELETED
    asset.deleted_at = timezone.now()
    asset.save()
    return True, None


def _restore(asset):
    """从回收站恢复：本地文件重新上传图床 + 移回 uploads。"""
    provider = get_active_provider()
    if provider is None:
        return False, "未配置生效的图床，无法恢复（请先到「设置 → 图床」启用）"

    local_path = _recycle_dir() / asset.local_name
    if not local_path.exists():
        return False, "本地回收文件已缺失，无法恢复"

    new_key = provider.build_key(asset.original_name)
    try:
        result = provider.upload(str(local_path), new_key, asset.original_name)
    except _StorageError as e:
        return False, f"重新上传图床失败：{e}"

    dst_name = _unique_name(_uploads_dir(), asset.local_name)
    shutil.move(str(local_path), str(_uploads_dir() / dst_name))

    asset.object_key = result["key"]
    asset.cdn_url = result["url"]
    asset.local_name = dst_name
    asset.provider = provider.name
    asset.status = ImageAsset.STATUS_ACTIVE
    asset.deleted_at = None
    asset.save()
    return True, None


def _purge(asset):
    local_path = _recycle_dir() / asset.local_name
    if local_path.exists():
        local_path.unlink()
    asset.delete()
    return True, None


# ---------- 登录 / 登出 ----------
def login_view(request):
    if request.user.is_authenticated:
        return redirect("gallery:index")

    error = ""
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect(request.POST.get("next") or "/")
        error = "用户名或密码不正确"
    return render(
        request,
        "gallery/login.html",
        {"error": error, "next": request.GET.get("next", "")},
    )


def logout_view(request):
    logout(request)
    return redirect("gallery:login")


# ---------- 本地文件预览（回收站 / 图库原图兜底） ----------
@login_required
def local_image(request, pk):
    """
    按资源 id 读取本地落盘文件并流式返回（回收站读 recycle 目录，正常图读 uploads 目录）。
    用于回收站卡片展示预览图——云端对象已删，只剩本地文件。
    做了路径穿越防护：解析后的真实路径必须仍落在对应目录下。
    """
    asset = get_object_or_404(ImageAsset, pk=pk)
    base = _recycle_dir() if asset.status == ImageAsset.STATUS_DELETED else _uploads_dir()
    path = (base / asset.local_name).resolve()
    base_resolved = base.resolve()
    if (
        not str(path).startswith(str(base_resolved) + os.sep)
        and str(path) != str(base_resolved)
    ):
        raise Http404()
    if not path.exists() or not path.is_file():
        raise Http404()
    ct, _ = mimetypes.guess_type(str(path))
    return FileResponse(
        open(str(path), "rb"),
        content_type=ct or "application/octet-stream",
        filename=asset.local_name,
    )


# ---------- 用户管理（昵称 / 头像 / 密码） ----------
@login_required
@require_POST
def account(request):
    """保存用户资料：昵称、头像（可选），以及（可选）修改密码。"""
    user = request.user
    profile, _ = UserProfile.objects.get_or_create(user=user)

    nickname = request.POST.get("nickname", "").strip()
    if nickname:
        profile.nickname = nickname

    avatar = request.FILES.get("avatar")
    if avatar:
        if not (avatar.content_type or "").startswith("image/"):
            return JsonResponse({"ok": False, "error": "头像必须是图片文件"}, status=400)
        profile.avatar = avatar

    # 密码：三项任一填写即视为要改密码，需校验当前密码并两次一致
    old = request.POST.get("old_password", "")
    new1 = request.POST.get("new_password", "")
    new2 = request.POST.get("new_password2", "")
    if old or new1 or new2:
        if not user.check_password(old):
            return JsonResponse({"ok": False, "error": "当前密码不正确"}, status=400)
        if new1 != new2:
            return JsonResponse({"ok": False, "error": "两次输入的新密码不一致"}, status=400)
        if len(new1) < 6:
            return JsonResponse({"ok": False, "error": "新密码至少 6 位"}, status=400)
        user.set_password(new1)
        user.save()

    profile.save()
    return JsonResponse(
        {
            "ok": True,
            "nickname": profile.nickname or user.username,
            "avatar_url": reverse("gallery:account_avatar") if profile.avatar else "",
        }
    )


@login_required
def account_avatar(request):
    """返回当前登录用户的头像文件（无头像则 404，前端回退到首字母占位）。"""
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.avatar:
        raise Http404()
    path = profile.avatar.path
    if not os.path.exists(path):
        raise Http404()
    ct, _ = mimetypes.guess_type(path)
    return FileResponse(open(path, "rb"), content_type=ct or "image/*")


# ---------- 页面 ----------
@login_required
@ensure_csrf_cookie
def index(request):
    q = request.GET.get("q", "").strip()
    active_tag = request.GET.get("tag", "").strip()
    active_provider = request.GET.get("provider", "").strip()

    images = ImageAsset.objects.filter(status=ImageAsset.STATUS_ACTIVE).prefetch_related("tags")
    if active_provider:
        images = images.filter(provider=active_provider)
    if q:
        images = images.filter(
            Q(original_name__icontains=q) | Q(object_key__icontains=q)
        )
    if active_tag:
        images = images.filter(tags__name=active_tag)

    # 图床筛选：统计各图床在正常图片里的数量
    provider_counts = (
        ImageAsset.objects.filter(status=ImageAsset.STATUS_ACTIVE)
        .values("provider")
        .annotate(n=Count("id"))
    )
    display_map = {s["name"]: s["display_name"] for s in list_specs()}
    provider_choices = [
        {
            "name": pc["provider"],
            "display": display_map.get(pc["provider"], pc["provider"]),
            "n": pc["n"],
        }
        for pc in provider_counts
    ]

    tags = (
        Tag.objects.filter(assets__status=ImageAsset.STATUS_ACTIVE)
        .annotate(n=Count("assets"))
        .distinct()
        .order_by("-n", "name")
    )
    deleted_count = ImageAsset.objects.filter(status=ImageAsset.STATUS_DELETED).count()

    return render(
        request,
        "gallery/index.html",
        {
            "images": images,
            "q": q,
            "tags": tags,
            "active_tag": active_tag,
            "active_provider": active_provider,
            "provider_choices": provider_choices,
            "deleted_count": deleted_count,
            "storage_configured": get_active_provider() is not None,
        },
    )


@login_required
@ensure_csrf_cookie
def recycle(request):
    q = request.GET.get("q", "").strip()
    items = ImageAsset.objects.filter(status=ImageAsset.STATUS_DELETED).prefetch_related("tags")
    if q:
        items = items.filter(
            Q(original_name__icontains=q) | Q(object_key__icontains=q)
        )
    # 为每条记录附加本地预览地址：仅当回收站里确实存在对应本地文件时才给，
    # 前端用它渲染预览图，缺失则回退到「已删除」占位（onerror 兜底）。
    for it in items:
        local = _recycle_dir() / it.local_name
        it.preview_url = reverse("gallery:local_image", args=[it.id]) if local.exists() else ""
    return render(request, "gallery/recycle.html", {"items": items, "q": q})


@login_required
@ensure_csrf_cookie
def history(request):
    """上传历史：按时间倒序展示全部图片（含已删除，可切换）。"""
    show_deleted = request.GET.get("all") == "1"
    items = ImageAsset.objects.all().prefetch_related("tags")
    if not show_deleted:
        items = items.filter(status=ImageAsset.STATUS_ACTIVE)
    items = items.order_by("-uploaded_at")
    provider_choices = dict(
        (pc["provider"], pc["n"])
        for pc in ImageAsset.objects.values("provider").annotate(n=Count("id"))
    )
    return render(
        request,
        "gallery/history.html",
        {
            "items": items,
            "show_deleted": show_deleted,
            "provider_choices": provider_choices,
            "storage_configured": get_active_provider() is not None,
        },
    )


@login_required
@ensure_csrf_cookie
def storage_settings(request):
    """
    图床配置页。
    GET：渲染所有 provider 的字段模板 + 已保存配置列表。
    POST：
      - action=activate / delete：切换/删除已有配置
      - 否则：新建或更新一条配置，并做必填校验（缺必填项不保存、不启用）
    """
    specs = list_specs()
    configs = StorageConfig.objects.all()

    if request.method == "POST":
        action = request.POST.get("action", "")

        # 启用 / 删除已有配置
        if action in ("activate", "delete"):
            cid = request.POST.get("id", "").strip()
            cfg = get_object_or_404(StorageConfig, pk=cid)
            if action == "activate":
                cfg.is_active = True
                cfg.save()
                return JsonResponse({"ok": True, "activated": cfg.id})
            else:
                cfg.delete()
                return JsonResponse({"ok": True, "deleted": cid})

        # 新建 / 更新配置
        provider = request.POST.get("provider", "").strip()
        display_name = request.POST.get("display_name", "").strip() or (
            dict((s["name"], s["display_name"]) for s in specs).get(provider, provider)
        )
        make_active = request.POST.get("is_active") == "on"
        cid = request.POST.get("id", "").strip()

        # 按该 provider 的字段模板从 POST 收集配置
        spec = next((s for s in specs if s["name"] == provider), None)
        if spec is None:
            return JsonResponse({"ok": False, "error": "未知的图床类型"}, status=400)
        config = {}
        for f in spec["fields"]:
            config[f["name"]] = request.POST.get(f["name"], "").strip()

        # 校验必填
        try:
            prov = create_provider(provider, config)
        except (ConfigError, StorageError) as e:
            return JsonResponse({"ok": False, "error": str(e)}, status=400)
        errors = prov.validate()
        if errors:
            return JsonResponse(
                {"ok": False, "error": "配置不完整，无法保存/启用", "fields": errors},
                status=400,
            )

        if cid:
            cfg = get_object_or_404(StorageConfig, pk=cid)
            cfg.provider = provider
            cfg.display_name = display_name
            cfg.config = config
            cfg.is_active = make_active
            cfg.save()
        else:
            StorageConfig.objects.create(
                provider=provider,
                display_name=display_name,
                config=config,
                is_active=make_active,
            )
        return JsonResponse({"ok": True})

    # 编辑回填：?edit=<id> 时把该配置的数据传给前端预填
    edit = None
    edit_id = request.GET.get("edit", "").strip()
    if edit_id:
        cfg = StorageConfig.objects.filter(pk=edit_id).first()
        if cfg:
            edit = {
                "id": cfg.id,
                "provider": cfg.provider,
                "display_name": cfg.display_name,
                "is_active": cfg.is_active,
                "config": cfg.config or {},
            }

    return render(
        request,
        "gallery/storage_settings.html",
        {
            "specs": specs,
            "configs": configs,
            "edit": edit,
            "active_id": (get_active_provider() and None) or None,
        },
    )


# ---------- 上传 ----------
@login_required
@require_POST
def upload(request):
    f = request.FILES.get("file")
    if not f:
        return JsonResponse({"ok": False, "error": "未收到文件"}, status=400)

    ext = os.path.splitext(f.name)[1].lower()
    if ext not in ALLOWED_EXT:
        return JsonResponse(
            {"ok": False, "error": f"不支持的图片格式：{ext or '无扩展名'}"}, status=400
        )

    try:
        payload = upload_image(
            source=f,
            original_name=f.name,
            tags=request.POST.get("tags", ""),
        )
    except _StorageError as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)
    except Exception as e:  # 兜底
        return JsonResponse({"ok": False, "error": f"上传失败：{e}"}, status=500)

    return JsonResponse({"ok": True, **payload})


@csrf_exempt
@require_POST
def api_upload(request):
    """
    统一对外 API：上传单张图片，返回 JSON（含 markdown / cdn_url / html）。
    供 CLI（pichome）与 AI Agent 调用。
    鉴权：已登录会话 或 持有 PICHOME_API_TOKEN（Header / ?token=）。
    豁免 CSRF，便于脚本/agent 直接调用。
    """
    # 鉴权：已登录会话 或 持有 PICHOME_API_TOKEN
    token = getattr(settings, "PICHOME_API_TOKEN", "")
    configured = bool(token)
    authorized = request.user.is_authenticated
    if configured:
        provided = (
            request.POST.get("token")
            or request.GET.get("token")
            or request.headers.get("Authorization", "").replace("Bearer ", "", 1)
        )
        authorized = provided == token
    # 未配置令牌时：放行（个人/内网便捷使用）。
    # 生产环境请务必设置 PICHOME_API_TOKEN 以启用强制校验，避免被滥用。
    if not authorized:
        if configured:
            return JsonResponse({"ok": False, "error": "未授权：令牌无效"}, status=401)

    f = request.FILES.get("file")
    if not f:
        return JsonResponse({"ok": False, "error": "未收到文件"}, status=400)
    ext = os.path.splitext(f.name)[1].lower()
    if ext not in ALLOWED_EXT:
        return JsonResponse(
            {"ok": False, "error": f"不支持的图片格式：{ext or '无扩展名'}"}, status=400
        )
    try:
        payload = upload_image(
            source=f,
            original_name=f.name,
            tags=request.POST.get("tags", ""),
        )
    except _StorageError as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)
    except Exception as e:
        return JsonResponse({"ok": False, "error": f"上传失败：{e}"}, status=500)
    return JsonResponse({"ok": True, **payload})


# ---------- 删除（单条 / 批量） ----------
@login_required
@require_POST
def delete_asset(request):
    try:
        asset = _pick_assets(request, ImageAsset.STATUS_ACTIVE).first()
    except Exception:
        asset = None
    if not asset:
        return JsonResponse({"ok": False, "error": "未找到对应的正常图片记录"}, status=404)

    ok, err = _soft_delete(asset)
    if not ok:
        return JsonResponse({"ok": False, "error": err}, status=500)
    return JsonResponse(
        {"ok": True, "id": asset.id, "original_name": asset.original_name}
    )


@login_required
@require_POST
def delete_batch(request):
    assets = _pick_assets(request, ImageAsset.STATUS_ACTIVE)
    deleted, failed = [], []
    for asset in assets:
        ok, err = _soft_delete(asset)
        if ok:
            deleted.append(asset.id)
        else:
            failed.append({"id": asset.id, "name": asset.original_name, "error": err})
    return JsonResponse(
        {"ok": True, "deleted": len(deleted), "failed": failed, "ids": deleted}
    )


@login_required
@require_POST
def delete_remote(request):
    """
    按图床对象名「直接删云端」，不校验本地是否存在记录。
    - 云端存在 → 删除，返回 ok
    - 云端不存在 → 返回 ok=False + 明确提示
    - 删除成功后，若本地恰好有同一 key 的正常记录，则同步移入回收站
    """
    key = request.POST.get("key", "").strip()
    if not key:
        return JsonResponse({"ok": False, "error": "请填写图床对象名"}, status=400)
    provider = get_active_provider()
    if provider is None:
        return JsonResponse(
            {"ok": False, "error": "未配置生效的图床，无法删除云端文件"},
            status=400,
        )

    try:
        result = provider.delete(key)
    except _StorageError as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)

    if result == "missing":
        return JsonResponse(
            {"ok": False, "error": f"图床上不存在该对象：{key}"}, status=404
        )

    synced = False
    asset = ImageAsset.objects.filter(object_key=key).first()
    if asset and asset.status == ImageAsset.STATUS_ACTIVE:
        ok, _err = _soft_delete(asset, remote=False)
        synced = ok

    return JsonResponse({"ok": True, "key": key, "synced": synced})


# ---------- 标签 ----------
@login_required
@require_POST
def set_tags(request):
    assets = _pick_assets(request, ImageAsset.STATUS_ACTIVE)
    raw = request.POST.get("tags", "")
    n = 0
    for asset in assets:
        _apply_tags(asset, raw)
        n += 1
    return JsonResponse({"ok": True, "updated": n})


# ---------- 回收站：恢复 / 彻底删除（单条 / 批量） ----------
@login_required
@require_POST
def restore(request):
    assets = _pick_assets(request, ImageAsset.STATUS_DELETED)
    asset = assets.first()
    if not asset:
        return JsonResponse({"ok": False, "error": "未找到回收站记录"}, status=404)
    ok, err = _restore(asset)
    if not ok:
        return JsonResponse({"ok": False, "error": err}, status=400)
    return JsonResponse({"ok": True, **build_payload(asset)})


@login_required
@require_POST
def restore_batch(request):
    assets = _pick_assets(request, ImageAsset.STATUS_DELETED)
    done, failed = [], []
    for asset in assets:
        ok, err = _restore(asset)
        (done if ok else failed).append(
            asset.id if ok else {"id": asset.id, "name": asset.original_name, "error": err}
        )
    return JsonResponse({"ok": True, "restored": len(done), "failed": failed, "ids": done})


@login_required
@require_POST
def purge(request):
    assets = _pick_assets(request, ImageAsset.STATUS_DELETED)
    asset = assets.first()
    if not asset:
        return JsonResponse({"ok": False, "error": "未找到回收站记录"}, status=404)
    _purge(asset)
    return JsonResponse({"ok": True, "id": asset.id})


@login_required
@require_POST
def purge_batch(request):
    assets = _pick_assets(request, ImageAsset.STATUS_DELETED)
    ids = [a.id for a in assets]
    for asset in assets:
        _purge(asset)
    return JsonResponse({"ok": True, "purged": len(ids), "ids": ids})


# ===== 导出：方便备份与迁移（全部 / 多选 / 单张；JSON 清单或原图 ZIP） =====
@login_required
def export_assets(request):
    """导出图库图片，供备份与迁移。

    使用方式（GET）：
      - 全部：/export/?all=1
      - 指定：/export/?ids=1,2,3
      - 格式：fmt=json（默认，导出链接与元信息清单）
              fmt=images（逐张回源图床拉取原图，打包成 ZIP 下载）
    """
    ids_raw = (request.GET.get("ids") or "").strip()
    export_all = request.GET.get("all") == "1"
    fmt = (request.GET.get("fmt") or "json").lower()

    qs = ImageAsset.objects.filter(status=ImageAsset.STATUS_ACTIVE)
    if not export_all and ids_raw:
        id_list = [int(x) for x in ids_raw.split(",") if x.strip().isdigit()]
        qs = qs.filter(id__in=id_list)

    if fmt == "images":
        return _export_images_zip(qs)

    # 默认：JSON 清单（链接 + 元信息，便于迁移到新环境或做备份清单）
    items = []
    for a in qs.prefetch_related("tags"):
        cdn = a.cdn_url or ""
        items.append({
            "id": a.id,
            "original_name": a.original_name,
            "object_key": a.object_key,
            "provider": a.provider,
            "provider_display": a.provider_display(),
            "cdn_url": cdn,
            "size": a.size,
            "uploaded_at": a.uploaded_at.isoformat() if a.uploaded_at else "",
            "tags": [t.name for t in a.tags.all()],
            "markdown": f'![{a.original_name}]({cdn} "{a.original_name}")',
            "html": f'<img src="{cdn}"/>',
        })

    payload = {
        "exported_at": timezone.now().isoformat(),
        "count": len(items),
        "items": items,
    }
    resp = JsonResponse(payload, json_dumps_params={"ensure_ascii": False, "indent": 2})
    resp["Content-Type"] = "application/json; charset=utf-8"
    fname = "pichome-export-%s.json" % timezone.now().strftime("%Y%m%d-%H%M%S")
    resp["Content-Disposition"] = 'attachment; filename="%s"' % fname
    return resp


def _export_images_zip(qs):
    """并行回源图床拉取原图，打包成 ZIP 下载（用于本地备份 / 迁移）。

    相比旧版的三处改进：
    1) 多线程并行拉取（默认 6 线程）：墙钟时间≈最慢单张而不是逐张累加，
       导出多张时明显更快；
    2) 写入临时文件后「流式」返回（StreamingHttpResponse 分块），浏览器可
       立即开始下载并显示进度，不再「点完没反应」地干等；
    3) 流式前文件已完整生成，因此带上 Content-Length，前端能显示真实百分比。

    单张失败会被跳过，至少一张成功才返回 ZIP，否则返回 400 提示链接可能已失效。
    """
    import os
    import tempfile
    import threading
    import urllib3
    import zipfile
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from django.http import StreamingHttpResponse

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    assets = list(qs.prefetch_related("tags"))
    if not assets:
        return JsonResponse({"error": "没有可导出的图片"}, status=400)

    # 先并行把各原图拉到内存，主线程再按完成顺序写入同一个 zip 文件。
    tmp = tempfile.NamedTemporaryFile(
        prefix="pichome-export-", suffix=".zip", delete=False
    )
    tmp_path = tmp.name
    tmp.close()

    written = 0
    used = set()
    lock = threading.Lock()

    def safe_name(i, url):
        # 安全文件名：取 URL 路径末尾，去查询串与非法字符，避免互相覆盖
        base = os.path.basename(url.split("?")[0]) or ("image_%d" % (i + 1))
        base = re.sub(r"[^\w.\-]", "_", base)
        if not base:
            base = "image_%d" % (i + 1)
        with lock:
            name = base
            n = 1
            while name in used:
                stem, dot, ext = base.rpartition(".")
                name = ("%s_%d%s%s" % (stem, n, dot, ext)) if dot else ("%s_%d" % (base, n))
                n += 1
            used.add(name)
        return name

    def fetch(a, i):
        url = a.cdn_url
        if not url:
            return None
        try:
            r = requests.get(url, timeout=15, verify=False)
            if r.status_code != 200 or not r.content:
                return None
            return (safe_name(i, url), r.content)
        except Exception:
            return None

    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as z:
        with ThreadPoolExecutor(max_workers=6) as ex:
            futures = {ex.submit(fetch, a, i): a for i, a in enumerate(assets)}
            for fut in as_completed(futures):
                res = fut.result()
                if not res:
                    continue
                name, data = res
                z.writestr(name, data)
                written += 1

    if written == 0:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return JsonResponse(
            {"error": "没有可下载的图片，可能图床链接已失效或图片已被删除"},
            status=400,
        )

    fname = "pichome-images-%s.zip" % timezone.now().strftime("%Y%m%d-%H%M%S")
    size = os.path.getsize(tmp_path)

    # 分块读出临时文件并流式返回；读完后删除临时文件（无论成功或客户端中断）。
    def gen():
        try:
            with open(tmp_path, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    yield chunk
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    resp = StreamingHttpResponse(gen(), content_type="application/zip")
    resp["Content-Disposition"] = 'attachment; filename="%s"' % fname
    resp["Content-Length"] = str(size)
    return resp


# ===== 背景图代理：绕过浏览器 CORS，由服务端去拉随机壁纸地址 =====
logger = logging.getLogger(__name__)

# 服务端缓存（文件级，跨 gunicorn 多 worker 共享）：
# - _BG_CACHE_FILE：当前展示的图（5 分钟 TTL），普通加载命中即秒回。
# - _BG_POOL_FILE：预取好的「下一批」壁纸地址队列。点切换(force=1)时直接
#   出队一张（秒回，不再现场回源上游），把"点切换→等几秒"的卡顿从后端回源
#   挪走；真实图片仍由浏览器异步下载，但 URL 已即时返回、且前端会预加载，
#   体验上几乎无感。
import os
import time
import threading

_BG_TTL = 300
_BG_CACHE_FILE = "/tmp/pichome_bg_cache.json"
_BG_POOL_FILE = "/tmp/pichome_bg_pool.json"
_BG_POOL_MIN = 4          # 池子低于这个数就后台补满
_BG_UPSTREAM = "https://blog.zhaojq.top/api/bg/random"

_pool_lock = threading.Lock()


def _load_bg_cache():
    try:
        with open(_BG_CACHE_FILE, "r") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("url"):
            return data
    except Exception:
        pass
    return {"url": "", "ts": 0.0}


def _save_bg_cache(url, ts):
    try:
        tmp = _BG_CACHE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"url": url, "ts": ts}, f)
        os.replace(tmp, _BG_CACHE_FILE)
    except Exception:
        pass


def _load_pool():
    try:
        with open(_BG_POOL_FILE, "r") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [u for u in data if isinstance(u, str)]
    except Exception:
        pass
    return []


def _save_pool(pool):
    try:
        tmp = _BG_POOL_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(pool, f)
        os.replace(tmp, _BG_POOL_FILE)
    except Exception:
        pass


def _fetch_one_bg(timeout=6):
    """回源上游拿一个 Bing 壁纸地址；失败返回空串（不抛异常）。"""
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    headers = {"Origin": "https://blog.zhaojq.top"}
    try:
        r = requests.get(
            _BG_UPSTREAM, headers=headers, allow_redirects=False,
            timeout=timeout, verify=False,
        )
        loc = r.headers.get("Location") or r.headers.get("location")
        if not loc:
            try:
                loc = r.json().get("url")
            except Exception:
                loc = None
        return loc or ""
    except Exception:
        return ""


def _topup_pool():
    """后台线程补充预取池（不阻塞请求）。"""
    def _worker():
        try:
            with _pool_lock:
                pool = _load_pool()
                need = max(0, _BG_POOL_MIN - len(pool))
                for _ in range(need):
                    u = _fetch_one_bg()
                    if u:
                        pool.append(u)
                _save_pool(pool)
        except Exception:
            pass
    threading.Thread(target=_worker, daemon=True).start()


@never_cache
def bg_proxy(request):
    """代理 blog.zhaojq.top 的随机背景接口。

    - 普通加载 / 首次：命中 5 分钟缓存即秒回；未命中才回源并写入缓存。
    - force=1（点切换）：优先从预取池出队一张（秒回，不现场回源），并异步补满；
      池空才回退到现场回源，保证点一下一定有反应。返回 {"url", "next"}，
      next 为下一张地址，供前端提前预加载，让再下一次切换近乎瞬时。
    - peek=1：仅返回池子队首供前端预加载，不消费（让下一次切换几乎瞬时）。
    公开接口（登录页也需要背景），不做登录校验。
    """
    force = request.GET.get("force") == "1"
    peek = request.GET.get("peek") == "1"
    now = time.time()
    cached = _load_bg_cache()

    # 池子偏少就异步补满（多数请求都不阻塞）
    if len(_load_pool()) < _BG_POOL_MIN:
        _topup_pool()

    # peek：只预告下一张，不消费
    if peek:
        pool = _load_pool()
        return JsonResponse({"url": pool[0] if pool else ""})

    # 主动换一张：从预取池出队（核心优化点，秒回）
    if force:
        with _pool_lock:
            pool = _load_pool()
            url = pool.pop(0) if pool else ""
            _save_pool(pool)
        if url:
            _save_bg_cache(url, now)
            _topup_pool()  # 异步补满，供下次切换
            nxt = _load_pool()
            return JsonResponse({"url": url, "next": nxt[0] if nxt else ""})
        # 池空：回退现场回源
        url = _fetch_one_bg()
        if url:
            _save_bg_cache(url, now)
            _topup_pool()
            return JsonResponse({"url": url, "next": ""})
        if cached.get("url"):
            return JsonResponse({"url": cached["url"], "next": ""})
        return JsonResponse({"url": "", "next": ""})

    # 普通加载：命中缓存秒回
    if cached.get("url") and (now - cached.get("ts", 0.0)) < _BG_TTL:
        return JsonResponse({"url": cached["url"]})
    # 未命中：现场回源
    url = _fetch_one_bg()
    if url:
        _save_bg_cache(url, now)
        _topup_pool()
        return JsonResponse({"url": url})
    return JsonResponse({"url": ""})


# worker 启动时预热预取池，让首次点击切换也快
_topup_pool()
