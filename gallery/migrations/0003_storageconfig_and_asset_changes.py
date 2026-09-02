from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gallery", "0002_tag_imageasset_tags"),
    ]

    operations = [
        # 原 qiniu_key（七牛云专用）→ 通用的 object_key（任意图床对象名）
        migrations.RenameField(
            model_name="imageasset",
            old_name="qiniu_key",
            new_name="object_key",
        ),
        # 记录每张图片所在的图床类型
        migrations.AddField(
            model_name="imageasset",
            name="provider",
            field=models.CharField(
                default="qiniu", max_length=32, verbose_name="图床"
            ),
        ),
        # 图床配置表（多图床、可配置、单生效）
        migrations.CreateModel(
            name="StorageConfig",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "provider",
                    models.CharField(
                        choices=[
                            ("qiniu", "七牛云 Kodo"),
                            ("aliyun", "阿里云 OSS"),
                            ("tencent", "腾讯云 COS"),
                            ("github", "GitHub 仓库"),
                        ],
                        max_length=32,
                        verbose_name="图床类型",
                    ),
                ),
                (
                    "display_name",
                    models.CharField(max_length=80, verbose_name="配置名称"),
                ),
                (
                    "is_active",
                    models.BooleanField(default=False, verbose_name="是否生效"),
                ),
                (
                    "config",
                    models.JSONField(default=dict, verbose_name="配置参数"),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, verbose_name="创建时间"),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True, verbose_name="更新时间"),
                ),
            ],
            options={
                "verbose_name": "图床配置",
                "verbose_name_plural": "图床配置",
                "ordering": ["-is_active", "-updated_at"],
            },
        ),
    ]
