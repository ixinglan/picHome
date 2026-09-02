"""
上传核心服务（Web 视图与 CLI 共用）。

统一负责：落盘本地 → 调生效图床上传 → 写数据库记录 → 返回含 markdown/html 的载荷。
这样不论是通过 HTTP 接口、还是命令行 pichome，行为完全一致。
"""
import os

from django.utils import timezone

from .django_backend import get_active_provider
from .models import ImageAsset, Tag
from .storage.exceptions import StorageError


def _unique_name(directory: "os.PathLike", name: str) -> str:
    """在 directory 中取一个不重名的最终文件名（重名则加 (1) (2)...）。"""
    if not (directory / name).exists():
        return name
    base, ext = os.path.splitext(name)
    i = 1
    while (directory / f"{base}({i}){ext}").exists():
        i += 1
    return f"{base}({i}){ext}"


def _apply_tags(asset: ImageAsset, raw: str):
    """把「逗号/空格分隔」的标签串应用到某张图片上（标签不存在则自动创建）。"""
    import re

    if raw is None:
        return
    names = [n.strip() for n in re.split(r"[,，、\s]+", raw) if n.strip()]
    tags = []
    for n in names:
        tag, _created = Tag.objects.get_or_create(name=n)
        tags.append(tag)
    asset.tags.set(tags)


def build_payload(asset: ImageAsset) -> dict:
    """统一的图片 JSON 结构（前后端 / CLI 共用）。"""
    cdn = asset.cdn_url or ""
    name = asset.original_name or ""
    return {
        "id": asset.id,
        "original_name": name,
        "object_key": asset.object_key,
        "provider": asset.provider,
        "provider_display": asset.provider_display(),
        "cdn_url": cdn,
        "thumb_url": asset.thumb_url,
        "size": asset.size,
        "tags": [t.name for t in asset.tags.all()],
        "uploaded_at": asset.uploaded_at.strftime("%Y-%m-%d %H:%M:%S"),
        # 3.1：直接给出 Markdown / HTML 片段，方便 agent 或用户粘贴使用
        "markdown": f'![{name}]({cdn} "{name}")' if cdn else "",
        "html": f'<img src="{cdn}"/>' if cdn else "",
    }


def upload_image(*, source, original_name: str, tags: str = "", provider=None) -> dict:
    """
    上传一张图片（被 Web 与 CLI 共用）。

    :param source: 本地文件路径（str/Path）或 Django UploadedFile 对象
    :param original_name: 原始文件名（用于命名与展示）
    :param tags: 逗号分隔的标签串
    :param provider: 指定图床 provider 实例；默认用当前生效图床
    :return: build_payload 结构的 dict
    """
    from django.conf import settings

    provider = provider or get_active_provider()
    if provider is None:
        raise StorageError("未配置生效的图床，请先到「设置 → 图床」中启用一个图床配置")

    uploads = settings.MEDIA_ROOT / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)

    # 1) 落本地（保留原始文件名，重名则加后缀）
    local_name = _unique_name(uploads, original_name)
    local_path = uploads / local_name
    if hasattr(source, "read"):  # Django UploadedFile
        with open(local_path, "wb") as out:
            for chunk in source.chunks():
                out.write(chunk)
        size = local_path.stat().st_size
        mime = getattr(source, "content_type", "") or ""
    else:  # 本地路径
        import shutil

        shutil.copyfile(str(source), str(local_path))
        size = local_path.stat().st_size
        mime = ""

    # 2) 上传到图床（时间戳重命名）
    key = provider.build_key(original_name)
    try:
        result = provider.upload(str(local_path), key, original_name)
    except StorageError:
        local_path.unlink(missing_ok=True)
        raise

    # 3) 写数据库记录
    asset = ImageAsset.objects.create(
        original_name=original_name,
        local_name=local_name,
        object_key=result["key"],
        provider=provider.name,
        cdn_url=result["url"],
        size=size,
        mime_type=mime,
    )
    _apply_tags(asset, tags)
    return build_payload(asset)
