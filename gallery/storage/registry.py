"""
存储后端注册表（纯 Python，不依赖 Django）。

- 新增图床：在对应 provider 模块定义子类后，在此 REGISTER 列表里登记即可。
- create_provider(name, config)：按名字造一个已注入配置的 provider 实例。
- list_specs()：返回所有图床的字段模板，供配置页自动渲染。
"""
from .aliyun_provider import AliyunProvider
from .base import StorageProvider
from .exceptions import ConfigError, StorageError
from .github_provider import GitHubProvider
from .qiniu_provider import QiniuProvider
from .tencent_provider import TencentProvider

# 所有支持的图床。新增图床只需在此追加。
REGISTER: list[type[StorageProvider]] = [
    QiniuProvider,
    AliyunProvider,
    TencentProvider,
    GitHubProvider,
]

PROVIDERS: dict[str, type[StorageProvider]] = {cls.name: cls for cls in REGISTER}


def get_provider_class(name: str) -> type[StorageProvider] | None:
    return PROVIDERS.get(name)


def create_provider(name: str, config: dict | None = None) -> StorageProvider:
    """按名字创建一个注入 config 的 provider 实例。名字不存在抛 ConfigError。"""
    cls = PROVIDERS.get(name)
    if cls is None:
        raise ConfigError(f"未知的图床类型：{name}")
    return cls(config or {})


def list_specs() -> list[dict]:
    """返回所有图床的元信息 + 字段模板，供配置页渲染。"""
    out = []
    for cls in REGISTER:
        out.append(
            {
                "name": cls.name,
                "display_name": cls.display_name,
                "fields": [f.to_dict() for f in cls.fields],
            }
        )
    return out


def provider_names() -> list[str]:
    return [c.name for c in REGISTER]
