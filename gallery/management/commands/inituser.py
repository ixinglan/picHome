"""
初始化 / 重置图库登录账号。

用法：
    .venv/bin/python manage.py inituser
    .venv/bin/python manage.py inituser --username xiaoqiang --password 123456
"""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "创建或重置图库的登录账号（默认 admin / admin12345）"

    def add_arguments(self, parser):
        parser.add_argument("--username", default="admin", help="用户名，默认 admin")
        parser.add_argument("--password", default="admin12345", help="密码，默认 admin12345")

    def handle(self, *args, **opts):
        username = opts["username"]
        password = opts["password"]
        user, created = User.objects.get_or_create(username=username)
        user.set_password(password)
        user.is_staff = True
        user.is_superuser = True
        user.save()

        action = "已创建账号" if created else "已重置该账号的密码"
        self.stdout.write(self.style.SUCCESS(f"{action}：用户名={username}  密码={password}"))
        self.stdout.write("登录地址：http://127.0.0.1:8000/login/")
        if password == "admin12345":
            self.stdout.write(self.style.WARNING("提示：建议用 --password 换成你自己的密码。"))
