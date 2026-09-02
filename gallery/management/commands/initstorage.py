"""
初始化图床配置：把 .env 里的 QINIU_* 自动转换成一条「生效」的七牛云 StorageConfig。

仅在库里还没有任何 StorageConfig 时触发，不会覆盖已有配置。
这样老项目（一直用 .env 配七牛云）升级到多图床架构后，原有图片与上传能力无缝保留。
"""
import os

from django.core.management.base import BaseCommand
from django.db import transaction

from gallery.models import StorageConfig


class Command(BaseCommand):
    help = "若库里无图床配置，则从 .env 的 QINIU_* 播种一条生效的七牛云配置"

    def handle(self, *args, **options):
        if StorageConfig.objects.exists():
            self.stdout.write("图床配置已存在，跳过初始化。")
            return

        ak = os.getenv("QINIU_ACCESS_KEY", "").strip()
        sk = os.getenv("QINIU_SECRET_KEY", "").strip()
        bucket = os.getenv("QINIU_BUCKET", "").strip()
        domain = os.getenv("QINIU_DOMAIN", "").strip()
        thumb = os.getenv("QINIU_THUMB_STYLE", "").strip()

        if not (ak and sk and bucket and domain):
            self.stdout.write(
                self.style.WARNING(
                    "未检测到 .env 的 QINIU_* 配置，未创建任何图床配置。"
                    "请到「设置 → 图床」手动添加。"
                )
            )
            return

        with transaction.atomic():
            StorageConfig.objects.create(
                provider="qiniu",
                display_name="七牛云（来自 .env）",
                is_active=True,
                config={
                    "access_key": ak,
                    "secret_key": sk,
                    "bucket": bucket,
                    "domain": domain,
                    "thumb_style": thumb,
                },
            )
        self.stdout.write(self.style.SUCCESS("已从 .env 创建并启用七牛云图床配置。"))
