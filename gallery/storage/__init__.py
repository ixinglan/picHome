"""存储抽象层包入口。

对外暴露最常用的几个符号，方便业务层一行导入：
    from gallery.storage import create_provider, list_specs, StorageError
"""
from .base import FieldSpec, StorageProvider
from .exceptions import ConfigError, StorageError
from .registry import (
    PROVIDERS,
    create_provider,
    get_provider_class,
    list_specs,
    provider_names,
)

__all__ = [
    "StorageProvider",
    "FieldSpec",
    "StorageError",
    "ConfigError",
    "create_provider",
    "get_provider_class",
    "list_specs",
    "provider_names",
    "PROVIDERS",
]
