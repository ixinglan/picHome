from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gallery", "0006_create_demo_user"),
    ]

    operations = [
        migrations.AddField(
            model_name="imageasset",
            name="synced_to_cloud",
            field=models.BooleanField(
                default=False, verbose_name="是否已同步到图床"
            ),
        ),
        # 数据回填：历史上已上传且有 cdn_url（即已在图床）的记录，视为已同步。
        # 之后「未配置图床直接上传」产生的记录 cdn_url 为空 → 保持 False，等待手动同步。
        migrations.RunPython(
            lambda apps, schema_editor: apps.get_model("gallery", "ImageAsset")
            .objects.exclude(cdn_url="")
            .update(synced_to_cloud=True),
            migrations.RunPython.noop,
        ),
    ]
