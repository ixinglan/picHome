"""七牛云 Kodo 存储实现。"""
from .base import FieldSpec, StorageProvider
from .exceptions import StorageError


class QiniuProvider(StorageProvider):
    name = "qiniu"
    display_name = "七牛云 Kodo"
    fields = [
        FieldSpec("access_key", "AccessKey", secret=True, placeholder="七牛云 AK"),
        FieldSpec("secret_key", "SecretKey", secret=True, placeholder="七牛云 SK"),
        FieldSpec("bucket", "存储空间名 Bucket", placeholder="my-bucket"),
        FieldSpec("domain", "访问域名 Domain", placeholder="https://img.example.com"),
        FieldSpec(
            "thumb_style",
            "缩略图样式（可选）",
            required=False,
            placeholder="?imageView2/2/w/400/q/75 或 -thumb",
            help_text="留空则用原图。列表缩略图会拼上该样式省流量。",
        ),
    ]

    def _client(self):
        from qiniu import Auth, BucketManager, put_file

        ak = self.config["access_key"]
        sk = self.config["secret_key"]
        bucket = self.config["bucket"]
        auth = Auth(ak, sk)
        return auth, bucket, put_file, BucketManager

    def upload(self, local_path, key, original_name=""):
        try:
            auth, bucket, put_file, _ = self._client()
        except KeyError as e:
            raise StorageError(f"七牛云配置缺失：{e}")
        token = auth.upload_token(bucket, key, 3600)
        ret, info = put_file(token, key, local_path)
        if not info.ok():
            raise StorageError(f"七牛云上传失败（{info.status_code}）：{info.text_body}")
        return {"key": key, "url": self.public_url(key)}

    def delete(self, key):
        from qiniu import Auth, BucketManager

        try:
            auth, bucket, _, BucketManager = self._client()
        except KeyError as e:
            raise StorageError(f"七牛云配置缺失：{e}")
        mgr = BucketManager(auth)
        ret, info = mgr.delete(bucket, key)
        if info.ok() or info.status_code == 612:
            return "deleted" if info.ok() else "missing"
        raise StorageError(f"七牛云删除失败（{info.status_code}）：{info.text_body}")

    def public_url(self, key):
        domain = (self.config.get("domain") or "").strip().rstrip("/")
        if not domain:
            raise StorageError("七牛云未配置访问域名 Domain")
        return f"{domain}/{key}"

    def thumb_url(self, url):
        style = (self.config.get("thumb_style") or "").strip()
        if not url or not style:
            return url
        if style.startswith("-"):
            return url + style
        style = style.lstrip("?&")
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}{style}"
