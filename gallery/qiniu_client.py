"""
七牛云对象存储封装层。

把「上传 / 删除 / 拼 CDN 链接」等七牛云操作单独抽出来，
视图层只调用这里的函数，方便以后替换存储后端或做单元测试。
"""
import os
import uuid
from datetime import datetime

from django.conf import settings
from qiniu import Auth, BucketManager, put_file


class QiniuConfigError(Exception):
    """七牛云未配置或配置不完整时抛出。"""


def _check_config():
    ak = settings.QINIU_ACCESS_KEY
    sk = settings.QINIU_SECRET_KEY
    bucket = settings.QINIU_BUCKET
    if not (ak and sk and bucket):
        raise QiniuConfigError(
            "七牛云未配置：请在 .env 中设置 QINIU_ACCESS_KEY / "
            "QINIU_SECRET_KEY / QINIU_BUCKET / QINIU_DOMAIN"
        )
    return ak, sk, bucket


def build_key(original_filename: str) -> str:
    """
    根据原文件名生成七牛云对象名（key）。

    规则：img/年月日_时分秒_毫秒_随机4位.扩展名
    —— 即「时间戳重命名」，同时保留原扩展名，并加少量随机避免并发碰撞。
    """
    ext = os.path.splitext(original_filename)[1].lower()
    now = datetime.now()
    ts = now.strftime("%Y%m%d_%H%M%S") + f"_{int(now.microsecond / 1000):03d}"
    rand = uuid.uuid4().hex[:4]
    return f"img/{ts}_{rand}{ext}"


def upload_file(local_path: str, key: str) -> None:
    """
    上传本地文件到七牛云指定 key。成功返回 None，失败抛异常。
    """
    ak, sk, bucket = _check_config()
    auth = Auth(ak, sk)
    # 3600 秒有效期的上传凭证
    token = auth.upload_token(bucket, key, 3600)
    ret, info = put_file(token, key, local_path)
    if not info.ok():
        raise RuntimeError(f"七牛云上传失败（{info.status_code}）：{info.text_body}")


def delete_file(key: str) -> None:
    """
    从七牛云删除指定 key 的对象。
    612 表示资源不存在，视为「已删除」成功，不报错。
    """
    ak, sk, bucket = _check_config()
    auth = Auth(ak, sk)
    bucket_mgr = BucketManager(auth)
    ret, info = bucket_mgr.delete(bucket, key)
    if info.ok():
        return
    if info.status_code == 612:
        return
    raise RuntimeError(f"七牛云删除失败（{info.status_code}）：{info.text_body}")


def delete_file_strict(key: str) -> str:
    """
    直接从七牛云删除指定 key，不关心本地是否存在对应记录。

    返回：
      "deleted" —— 云端存在并已删除
      "missing" —— 云端本来就没有这个对象（HTTP 612）

    其他错误抛 RuntimeError。
    """
    ak, sk, bucket = _check_config()
    auth = Auth(ak, sk)
    bucket_mgr = BucketManager(auth)
    ret, info = bucket_mgr.delete(bucket, key)
    if info.ok():
        return "deleted"
    if info.status_code == 612:
        return "missing"
    raise RuntimeError(f"七牛云删除失败（{info.status_code}）：{info.text_body}")


def public_url(key: str) -> str:
    """把七牛云 key 拼成可访问的 CDN 链接。"""
    domain = settings.QINIU_DOMAIN.rstrip("/")
    return f"{domain}/{key}"
