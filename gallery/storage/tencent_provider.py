"""腾讯云 COS 存储实现。"""
from .base import FieldSpec, StorageProvider, _ts_key
from .exceptions import StorageError


class TencentProvider(StorageProvider):
    name = "tencent"
    display_name = "腾讯云 COS"
    fields = [
        FieldSpec("secret_id", "SecretId", secret=True),
        FieldSpec("secret_key", "SecretKey", secret=True),
        FieldSpec("region", "地域 Region", placeholder="ap-guangzhou"),
        FieldSpec("bucket", "Bucket 名称", placeholder="my-bucket-1250000000"),
        FieldSpec(
            "domain",
            "自定义域名（可选）",
            required=False,
            placeholder="https://img.example.com",
            help_text="留空则使用 https://{bucket}.cos.{region}.myqcloud.com/{key}。",
        ),
        FieldSpec(
            "thumb_style",
            "缩略图样式（可选）",
            required=False,
            placeholder="?imageMogr2/thumbnail/400x",
            help_text="留空用原图；COS 的数据处理参数会拼到 URL 后。",
        ),
    ]

    def build_key(self, original_name):
        return _ts_key(original_name, prefix="img/")

    def _client(self):
        from qcloud_cos import CosConfig, CosS3Client

        config = CosConfig(
            Region=self.config["region"],
            SecretId=self.config["secret_id"],
            SecretKey=self.config["secret_key"],
        )
        return CosS3Client(config)

    def upload(self, local_path, key, original_name=""):
        try:
            client = self._client()
        except KeyError as e:
            raise StorageError(f"腾讯云 COS 配置缺失：{e}")
        try:
            client.upload_file(Bucket=self.config["bucket"], Key=key, LocalFilePath=local_path)
        except Exception as e:  # COS 异常类型多，统一捕获
            raise StorageError(f"腾讯云 COS 上传失败：{e}")
        return {"key": key, "url": self.public_url(key)}

    def delete(self, key):
        try:
            client = self._client()
        except KeyError as e:
            raise StorageError(f"腾讯云 COS 配置缺失：{e}")
        try:
            client.delete_object(Bucket=self.config["bucket"], Key=key)
            return "deleted"
        except Exception as e:
            # COS 删除不存在的对象会报 NoSuchKey（404）
            if "NoSuchKey" in str(e) or "404" in str(e):
                return "missing"
            raise StorageError(f"腾讯云 COS 删除失败：{e}")

    def public_url(self, key):
        domain = (self.config.get("domain") or "").strip().rstrip("/")
        if domain:
            return f"{domain}/{key}"
        region = (self.config.get("region") or "").strip()
        bucket = (self.config.get("bucket") or "").strip()
        if not (region and bucket):
            raise StorageError("腾讯云 COS 未配置 Region/Bucket 或自定义域名")
        return f"https://{bucket}.cos.{region}.myqcloud.com/{key}"

    def thumb_url(self, url):
        style = (self.config.get("thumb_style") or "").strip()
        if not url or not style:
            return url
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}{style.lstrip('?&')}"
