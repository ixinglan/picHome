"""
Django 侧与存储抽象层的桥接。

只在这里接触数据库（StorageConfig）。存储核心 gallery.storage 本身不依赖 Django，
因此 CLI / 未来桌面端都能复用同一套 provider 逻辑。
"""
from .models import StorageConfig
from .storage import ConfigError, StorageError, create_provider


def get_active_config() -> StorageConfig | None:
    """返回当前 is_active=True 的图床配置（没有则返回 None）。"""
    return StorageConfig.objects.filter(is_active=True).first()


def get_active_provider():
    """
    返回当前生效的图床 provider 实例（已注入配置且校验通过）。
    无生效配置、或配置不完整时返回 None。
    """
    cfg = get_active_config()
    if not cfg:
        return None
    try:
        provider = create_provider(cfg.provider, cfg.config)
    except (ConfigError, StorageError):
        return None
    if not provider.is_configured():
        return None
    return provider


def get_provider_by_config(cfg: StorageConfig):
    """按某条 StorageConfig 造一个 provider 实例（用于测试/校验该配置本身）。"""
    return create_provider(cfg.provider, cfg.config)
