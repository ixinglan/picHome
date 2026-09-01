"""
图库视图层（全部需要登录）。

页面：
- GET  /                 图库首页（上传区 + 标签筛选 + 搜索 + 卡片网格）
- GET  /recycle/         回收站
- GET  /login/           登录页
- GET  /logout/          退出登录

接口（AJAX）：
- POST /upload            上传单张图片（可带标签）
- POST /delete            删除单张（按 id 或七牛云对象名）
- POST /delete_batch      批量删除（ids[] 或 keys[]）
- POST /set_tags          给一张/多张图片设置标签
- POST /recycle/restore   恢复单张（重新上传七牛云）
- POST /recycle/restore_batch  批量恢复
- POST /recycle/purge     彻底删除单张
- POST /recycle/purge_batch    批量彻底删除
"""
import os
import re
import shutil

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from .models import ImageAsset, Tag
from .qiniu_client import (
    QiniuConfigError,
    build_key,
    delete_file,
    delete_file_strict,
    public_url,
    upload_file,
)

# 允许的图片扩展名
ALLOWED_EXT = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic", ".svg",
}


# ---------- 基础辅助 ----------
def _qiniu_ready() -> bool:
    """七牛云四项配置是否齐全。"""
    return bool(
        settings.QINIU_ACCESS_KEY
        and settings.QINIU_SECRET_KEY
        and settings.QINIU_BUCKET
        and settings.QINIU_DOMAIN
    )


def _uploads_dir():
    d = settings.MEDIA_ROOT / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _recycle_dir():
    d = settings.MEDIA_ROOT / "recycle"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _unique_name(directory, name):
    """在 directory 中取一个不重名的最终文件名（重名则加 (1) (2)...）。"""
    if not (directory / name).exists():
        return name
    base, ext = os.path.splitext(name)
    i = 1
    while (directory / f"{base}({i}){ext}").exists():
        i += 1
    return f"{base}({i}){ext}"


def _apply_tags(asset, raw):
    """把「逗号/空格分隔」的标签串应用到某张图片上（标签不存在则自动创建）。"""
    if raw is None:
        return
    names = [n.strip() for n in re.split(r"[,，、\s]+", raw) if n.strip()]
    tags = []
    for n in names:
        tag, _created = Tag.objects.get_or_create(name=n)
        tags.append(tag)
    asset.tags.set(tags)


def _asset_payload(asset):
    """统一的图片 JSON 结构，前后端共用。"""
    return {
        "id": asset.id,
        "original_name": asset.original_name,
        "qiniu_key": asset.qiniu_key,
        "cdn_url": asset.cdn_url,
        "thumb_url": asset.thumb_url,
        "size": asset.size,
        "tags": [t.name for t in asset.tags.all()],
        "uploaded_at": asset.uploaded_at.strftime("%Y-%m-%d %H:%M:%S"),
    }


# ---------- 核心操作（被单条/批量复用） ----------
def _soft_delete(asset, remote=True):
    """
    删除七牛云对象 + 本地移入回收站 + 标记删除。
    remote=False 时跳过云端删除（用于云端已删除、只需同步本地状态的场景）。

    返回 (True, None) 或 (False, 错误信息)。
    """
    if remote:
        try:
            delete_file(asset.qiniu_key)
        except Exception as e:
            return False, f"七牛云删除失败：{e}"

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
    """从回收站恢复：本地文件重新上传七牛云 + 移回 uploads。"""
    local_path = _recycle_dir() / asset.local_name
    if not local_path.exists():
        return False, "本地回收文件已缺失，无法恢复"

    new_key = build_key(asset.original_name)
    try:
        upload_file(str(local_path), new_key)
    except Exception as e:
        return False, f"重新上传七牛云失败：{e}"

    dst_name = _unique_name(_uploads_dir(), asset.local_name)
    shutil.move(str(local_path), str(_uploads_dir() / dst_name))

    asset.qiniu_key = new_key
    asset.cdn_url = public_url(new_key)
    asset.local_name = dst_name
    asset.status = ImageAsset.STATUS_ACTIVE
    asset.deleted_at = None
    asset.save()
    return True, None


def _purge(asset):
    """彻底删除：删本地回收文件 + 数据库记录。"""
    local_path = _recycle_dir() / asset.local_name
    if local_path.exists():
        local_path.unlink()
    asset.delete()
    return True, None


def _pick_assets(request, status):
    """从请求里解析出要操作的一组图片（支持 id[] 与 key[]）。"""
    ids = [x for x in request.POST.getlist("id") if x.strip()]
    keys = [x.strip() for x in request.POST.getlist("key") if x.strip()]
    qs = ImageAsset.objects.filter(status=status)
    if ids:
        return qs.filter(id__in=ids)
    if keys:
        return qs.filter(qiniu_key__in=keys)
    return qs.none()


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


# ---------- 页面 ----------
@login_required
@ensure_csrf_cookie
def index(request):
    q = request.GET.get("q", "").strip()
    active_tag = request.GET.get("tag", "").strip()

    images = ImageAsset.objects.filter(status=ImageAsset.STATUS_ACTIVE).prefetch_related(
        "tags"
    )
    if q:
        images = images.filter(
            Q(original_name__icontains=q) | Q(qiniu_key__icontains=q)
        )
    if active_tag:
        images = images.filter(tags__name=active_tag)

    # 标签筛选栏：只统计「正常」状态的图片数量
    tags = (
        Tag.objects.filter(assets__status=ImageAsset.STATUS_ACTIVE)
        .annotate(n=Count("assets"))
        .distinct()
        .order_by("-n", "name")
    )
    deleted_count = ImageAsset.objects.filter(
        status=ImageAsset.STATUS_DELETED
    ).count()

    return render(
        request,
        "gallery/index.html",
        {
            "images": images,
            "q": q,
            "tags": tags,
            "active_tag": active_tag,
            "deleted_count": deleted_count,
            "qiniu_configured": _qiniu_ready(),
        },
    )


@login_required
@ensure_csrf_cookie
def recycle(request):
    q = request.GET.get("q", "").strip()
    items = ImageAsset.objects.filter(status=ImageAsset.STATUS_DELETED).prefetch_related(
        "tags"
    )
    if q:
        items = items.filter(
            Q(original_name__icontains=q) | Q(qiniu_key__icontains=q)
        )
    return render(request, "gallery/recycle.html", {"items": items, "q": q})


# ---------- 上传 ----------
@login_required
@require_POST
def upload(request):
    if not _qiniu_ready():
        return JsonResponse(
            {"ok": False, "error": "七牛云尚未配置，请先在 .env 中填写 AK / SK / Bucket / 域名"},
            status=400,
        )

    f = request.FILES.get("file")
    if not f:
        return JsonResponse({"ok": False, "error": "未收到文件"}, status=400)

    ext = os.path.splitext(f.name)[1].lower()
    if ext not in ALLOWED_EXT:
        return JsonResponse(
            {"ok": False, "error": f"不支持的图片格式：{ext or '无扩展名'}"}, status=400
        )

    # 1) 先落本地（保留原始文件名，重名则加后缀，不改原意）
    uploads = _uploads_dir()
    original_name = f.name
    local_name = _unique_name(uploads, original_name)
    local_path = uploads / local_name
    with open(local_path, "wb") as out:
        for chunk in f.chunks():
            out.write(chunk)
    size = local_path.stat().st_size
    mime = f.content_type or ""

    # 2) 上传到七牛云（时间戳重命名）
    key = build_key(original_name)
    try:
        upload_file(str(local_path), key)
    except QiniuConfigError as e:
        local_path.unlink(missing_ok=True)
        return JsonResponse({"ok": False, "error": str(e)}, status=400)
    except Exception as e:  # 上传失败则回滚本地文件，避免脏数据
        local_path.unlink(missing_ok=True)
        return JsonResponse({"ok": False, "error": f"上传七牛云失败：{e}"}, status=500)

    # 3) 记录映射关系 + 标签
    asset = ImageAsset.objects.create(
        original_name=original_name,
        local_name=local_name,
        qiniu_key=key,
        cdn_url=public_url(key),
        size=size,
        mime_type=mime,
    )
    _apply_tags(asset, request.POST.get("tags", ""))
    return JsonResponse({"ok": True, **_asset_payload(asset)})


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
    按七牛云对象名「直接删云端」，不校验本地是否存在记录。

    - 云端存在 → 删除，返回 ok
    - 云端不存在（612）→ 返回 ok=False + 明确提示
    - 删除成功后，若本地恰好有同一 key 的正常记录，则同步移入回收站，避免列表里留着失效图片
    """
    key = request.POST.get("key", "").strip()
    if not key:
        return JsonResponse({"ok": False, "error": "请填写七牛云对象名"}, status=400)
    if not _qiniu_ready():
        return JsonResponse(
            {"ok": False, "error": "七牛云尚未配置，请先在 .env 中填写 AK / SK / Bucket / 域名"},
            status=400,
        )

    try:
        result = delete_file_strict(key)
    except QiniuConfigError as e:
        return JsonResponse({"ok": False, "error": str(e)}, status=400)
    except Exception as e:
        return JsonResponse({"ok": False, "error": f"七牛云删除失败：{e}"}, status=500)

    if result == "missing":
        return JsonResponse(
            {"ok": False, "error": f"七牛云上不存在该对象：{key}"}, status=404
        )

    # 云端删除成功：顺手把本地同一 key 的正常记录同步进回收站
    synced = False
    asset = ImageAsset.objects.filter(qiniu_key=key).first()
    if asset and asset.status == ImageAsset.STATUS_ACTIVE:
        ok, _err = _soft_delete(asset, remote=False)
        synced = ok

    return JsonResponse({"ok": True, "key": key, "synced": synced})


# ---------- 标签 ----------
@login_required
@require_POST
def set_tags(request):
    """给一张或多张图片重设标签。参数：id[] 或 key[]，tags=逗号分隔字符串。"""
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
    return JsonResponse({"ok": True, **_asset_payload(asset)})


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
