from django.db import migrations


def create_demo_user(apps, schema_editor):
    """创建演示账号 demo / demo12345，标记为只读（is_demo=True）。

    幂等：多次 migrate 也不会重复建用户；演示账号仅用于「登录浏览体验」，
    不能上传 / 删除 / 改资料 / 导出，服务端由 DemoReadOnlyMiddleware 兜底拦截。
    """
    from django.contrib.auth.models import User

    from gallery.models import UserProfile

    user, _ = User.objects.get_or_create(username="demo")
    user.set_password("demo12345")
    user.is_staff = False
    user.is_superuser = False
    user.save()

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.is_demo = True
    profile.save()


def remove_demo_user(apps, schema_editor):
    from django.contrib.auth.models import User

    User.objects.filter(username="demo").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("gallery", "0005_add_is_demo_to_userprofile"),
    ]

    operations = [
        migrations.RunPython(create_demo_user, remove_demo_user),
    ]
