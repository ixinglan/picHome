# 七牛云图床管理工具 - 生产镜像
# 基础镜像用 python:3.13-slim（Django 6.x 需要 Python 3.13+，且本项目依赖都是纯 Python，无需编译）
FROM python:3.13-slim

# 关闭输出缓冲 / 不写 .pyc，减小镜像体积
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 1) 先只装依赖：只要 requirements.txt 不变，这一层会被缓存，无需重复下载
COPY requirements.txt .
RUN pip install -r requirements.txt

# 2) 再拷源码（.dockerignore 已排除 .env / db.sqlite3 等，密钥不会进镜像）
COPY . .

# 赋予启动脚本执行权限
RUN chmod +x docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./docker-entrypoint.sh"]
