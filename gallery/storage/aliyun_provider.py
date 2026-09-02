"""阿里云 OSS 存储实现。"""
from .base import FieldSpec, StorageProvider, _ts_key
from .exceptions import StorageError


class AliyunProvider(StorageProvider):
    name = "aliyun"
    display_name = "阿里云 OSS"
    fields = [
        FieldSpec("access_key_id", "AccessKeyId", secret=True),
        FieldSpec("access_key_secret", "AccessKeySecret", secret=True),
        FieldSpec("endpoint", "Endpoint", placeholder="oss-cn-hangzhou.aliyuncs.com"),
        FieldSpec("bucket", "Bucket 名称", placeholder="my-bucket"),
        FieldSpec(
            "domain",
            "自定义域名（可选）",
            required=False,
            placeholder="https://img.example.com",
            help_text="留空则使用 https://{bucket}.{endpoint}/{key} 形式。",
        ),
        FieldSpec(
            "thumb_style",
            "缩略图样式（可选）",
            required=False,
            placeholder="?x-oss-process=image/resize,w_400",
            help_text="留空用原图；OSS 的图片处理参数会拼到 URL 后。",
        ),
    ]

    def build_key(self, original_name):
        return _ts_key(original_name, prefix="img/")

    def _bucket(self):
        import oss2

        auth = oss2.Auth(self.config["access_key_id"], self.config["access_key_secret"])
        return oss2.Bucket(auth, self.config["endpoint"], self.config["bucket"])

    def upload(self, local_path, key, original_name=""):
        try:
            bucket = self._bucket()
        except KeyError as e:
            raise StorageError(f"阿里云 OSS 配置缺失：{e}")
        try:
            bucket.put_object_from_file(key, local_path)
        except oss2.exceptions.OssError as e:  # type: ignore
            raise StorageError(f"阿里云 OSS 上传失败：{e}")
        return {"key": key, "url": self.public_url(key)}

    def delete(self, key):
        try:
            bucket = self._bucket()
        except KeyError as e:
            raise StorageError(f"阿里云 OSS 配置缺失：{e}")
        try:
            bucket.delete_object(key)
            return "deleted"
        except oss2.exceptions.NoSuchKey:  # type: ignore
            return "missing"
        except oss2.exceptions.OssError as e:  # type: ignore
            raise StorageError(f"阿里云 OSS 删除失败：{e}")

    def public_url(self, key):
        domain = (self.config.get("domain") or "").strip().rstrip("/")
        if domain:
            return f"{domain}/{key}"
        endpoint = (self.config.get("endpoint") or "").strip()
        bucket = (self.config.get("bucket") or "").strip()
        if not (endpoint and bucket):
            raise StorageError("阿里云 OSS 未配置 Endpoint/Bucket 或自定义域名")
        return f"https://{bucket}.{endpoint}/{key}"

    def thumb_url(self, url):
        style = (self.config.get("thumb_style") or "").strip()
        if not url or not style:
            return url
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}{style.lstrip('?&')}"
