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
    一张图片在「本地 + 七牛云」两侧的映射记录。

    关键设计：
    - original_name：用户上传时的原始文件名（本地图片名不变，仅作展示/搜索用）
    - local_name   ：实际落盘到 media/uploads 的文件名（可能为避免重名加后缀）
    - qiniu_key    ：上传到七牛云后的对象名（时间戳重命名），全局唯一
    - cdn_url      ：七牛云原图的对外访问链接
    - thumb_url    ：拼上七牛云处理样式后的缩略图链接（列表用，省流量）
    - tags         ：分类标签（多对多）
    - status       ：active 正常 / deleted 已移入回收站（本地保留，七牛云已删）
    """

    STATUS_ACTIVE = "active"
    STATUS_DELETED = "deleted"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "正常"),
        (STATUS_DELETED, "已删除"),
    ]

    original_name = models.CharField(max_length=255, verbose_name="本地原名")
    local_name = models.CharField(max_length=255, verbose_name="本地存储名")
    qiniu_key = models.CharField(max_length=255, unique=True, verbose_name="七牛云对象名")
    cdn_url = models.URLField(max_length=512, blank=True, verbose_name="CDN 链接")
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

    @property
    def thumb_url(self):
        """
        列表用的缩略图链接 = 原图链接 + 七牛云处理样式。

        支持两种写法（在 .env 的 QINIU_THUMB_STYLE 里配置）：
        1) 查询参数式：?imageView2/2/w/400/q/75
        2) 分隔符样式：-thumb（需在七牛云空间里先建好对应的样式）
        留空则直接用原图。
        """
        url = self.cdn_url or ""
        style = (getattr(settings, "QINIU_THUMB_STYLE", "") or "").strip()
        if not url or not style:
            return url
        if style.startswith("-"):  # 分隔符样式，直接拼在后面
            return url + style
        style = style.lstrip("?&")
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}{style}"

    def tag_names(self):
        """返回逗号分隔的标签名，用于前端回填输入框。"""
        return ", ".join(self.tags.values_list("name", flat=True))
