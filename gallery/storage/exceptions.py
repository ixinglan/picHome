"""存储层异常定义。"""


class StorageError(Exception):
    """存储后端通用错误（配置缺失、上传/删除失败等）。"""


class ConfigError(StorageError):
    """图床配置不完整或校验未通过。"""
