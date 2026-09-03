#!/bin/sh
# 容器启动入口：迁移数据库 -> 首次建管理员 -> 收集静态文件 -> 拉起 Gunicorn
set -e

echo "==> 执行数据库迁移"
python manage.py migrate --noinput

echo "==> 初始化管理员账号（仅当库里没有任何账号时才创建，不会覆盖已有账号）"
if [ "$(python manage.py shell -c 'from django.contrib.auth.models import User; print(User.objects.exists())' 2>/dev/null)" != "True" ]; then
    python manage.py inituser
else
    echo "   账号已存在，跳过初始化"
fi

echo "==> 初始化图床配置（仅当库里没有任何图床配置时，从 .env 的 QINIU_* 播种）"
python manage.py initstorage

echo "==> 收集静态文件（交由 Whitenoise 直接由 Gunicorn 提供，无需 Nginx）"
python manage.py collectstatic --noinput

echo "==> 启动 Gunicorn（0.0.0.0:8000）"
exec gunicorn pichome_web.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 3 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
