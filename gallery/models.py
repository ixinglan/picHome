from django.conf import settings
from django.db import models


class Tag(models.Model):
    """图片分类标签。上传时可按逗号分隔自动创建。"""

    name = models.CharField(max_length=50, unique=True, verbose_name="标签名")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        ordering = ["name"]
        verbose_name = "标签"
        verbose_name_plural = "标签"

    def __str__(self):
        return self.name


class ImageAsset(models.Model):
    """
    一张图片在「本地 + 某个图床」两侧的映射记录。

    关键设计：
    - original_name：用户上传时的原始文件名（本地图片名不变，仅作展示/搜索用）
    - local_name   ：实际落盘到 media/uploads 的文件名（可能为避免重名加后缀）
    - object_key   ：上传到图床后的对象名（时间戳重命名），全局唯一
    - provider     ：该图片所在的图床（qiniu / aliyun / tencent / github）
    - cdn_url      ：图床原图的对外访问链接
    - thumb_url    ：列表用的缩略图链接（由各图床 provider 按自身样式拼，省流量）
    - tags         ：分类标签（多对多）
    - status       ：active 正常 / deleted 已移入回收站（本地保留，图床已删）
    """

    STATUS_ACTIVE = "active"
    STATUS_DELETED = "deleted"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "正常"),
        (STATUS_DELETED, "已删除"),
    ]

    original_name = models.CharField(max_length=255, verbose_name="本地原名")
    local_name = models.CharField(max_length=255, verbose_name="本地存储名")
    object_key = models.CharField(max_length=255, unique=True, verbose_name="图床对象名")
    provider = models.CharField(max_length=32, default="qiniu", verbose_name="图床")
    cdn_url = models.URLField(max_length=512, blank=True, verbose_name="访问链接")
    size = models.PositiveIntegerField(default=0, verbose_name="文件大小(字节)")
    mime_type = models.CharField(max_length=100, blank=True, verbose_name="MIME 类型")
    tags = models.ManyToManyField(
        Tag, blank=True, related_name="assets", verbose_name="标签"
    )
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_ACTIVE, verbose_name="状态"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name="上传时间")
    deleted_at = models.DateTimeField(null=True, blank=True, verbose_name="删除时间")

    class Meta:
        ordering = ["-uploaded_at"]
        verbose_name = "图片资源"
        verbose_name_plural = "图片资源"

    def __str__(self):
        return self.original_name

    @property
    def is_deleted(self):
        return self.status == self.STATUS_DELETED

    def provider_display(self):
        """图床的中文展示名（取自注册表）。"""
        from .storage.registry import get_provider_class

        cls = get_provider_class(self.provider)
        return cls.display_name if cls else self.provider

    @property
    def thumb_url(self):
        """
        列表用的缩略图链接。
        优先用「当前生效图床」的 provider 拼样式（各图床样式规则不同）；
        拿不到 provider 时直接返回原图。
        """
        url = self.cdn_url or ""
        if not url:
            return url
        try:
            # 延迟导入，避免 models <-> django_backend 循环依赖
            from .django_backend import get_active_provider

            provider = get_active_provider()
            if provider is not None:
                return provider.thumb_url(url)
        except Exception:
            pass
        return url

    def tag_names(self):
        """返回逗号分隔的标签名，用于前端回填输入框。"""
        return ", ".join(self.tags.values_list("name", flat=True))


class StorageConfig(models.Model):
    """
    图床（存储后端）配置。每种图床可建多条，但同一时刻只有一个 is_active=True。

    设计要点（满足"可配置、扩展性强、缺必填不能启用"）：
    - provider：图床类型，对应 gallery.storage.registry 里的注册名
    - config  ：该图床的参数字典（AK/SK/Bucket/域名…），由对应 provider 的
               FieldSpec 驱动渲染与校验，不写死字段
    - is_active：是否生效。保存为 True 时会自动把其它配置置为 False（全局唯一）
    """

    PROVIDER_CHOICES = [
        ("qiniu", "七牛云 Kodo"),
        ("aliyun", "阿里云 OSS"),
        ("tencent", "腾讯云 COS"),
        ("github", "GitHub 仓库"),
    ]

    provider = models.CharField(max_length=32, choices=PROVIDER_CHOICES, verbose_name="图床类型")
    display_name = models.CharField(max_length=80, verbose_name="配置名称")
    is_active = models.BooleanField(default=False, verbose_name="是否生效")
    config = models.JSONField(default=dict, verbose_name="配置参数")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        ordering = ["-is_active", "-updated_at"]
        verbose_name = "图床配置"
        verbose_name_plural = "图床配置"

    def __str__(self):
        return f"{self.display_name}（{self.get_provider_display()}）"

    def save(self, *args, **kwargs):
        # 保证全局只有一个生效配置
        if self.is_active:
            StorageConfig.objects.filter(is_active=True).exclude(pk=self.pk).update(
                is_active=False
            )
        super().save(*args, **kwargs)

    def provider_display(self):
        return dict(self.PROVIDER_CHOICES).get(self.provider, self.provider)


class UserProfile(models.Model):
    """
    用户扩展资料（一对一关联 Django 自带 User）。
    - nickname：昵称（展示用，默认回退到 username）
    - avatar   ：头像图片（存于 MEDIA_ROOT/avatars，由 account_avatar 视图按需返回）
    """

    user = models.OneToOneField(
        "auth.User", on_delete=models.CASCADE, related_name="profile", verbose_name="用户"
    )
    nickname = models.CharField(max_length=40, blank=True, verbose_name="昵称")
    # 用 FileField 而非 ImageField：仅存文件路径，图片合法性在视图层按 content_type 校验，
    # 避免依赖 Pillow（容器内当前未安装），头像展示由 account_avatar 视图流式返回。
    avatar = models.FileField(upload_to="avatars/", blank=True, verbose_name="头像")

    class Meta:
        verbose_name = "用户资料"
        verbose_name_plural = "用户资料"

    def __str__(self):
        return self.nickname or self.user.username
