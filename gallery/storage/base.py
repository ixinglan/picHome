"""
存储后端抽象层（纯 Python，不依赖 Django）。

设计目标：
- 每个图床（七牛云 / 阿里云 OSS / 腾讯云 COS / GitHub 等）都是一个
  StorageProvider 子类，声明自己的「必填字段模板」与上传/删除/拼链接逻辑。
- 新增图床 = 新增一个子类 + 在 registry 注册，业务代码零改动（满足"扩展性强"）。
- 字段模板（FieldSpec）同时驱动「配置页自动渲染」与「启用前必填校验」，
  缺必填项时无法启用，交互上直接禁用按钮 + 行内报错。
"""
import os
import uuid
from abc import ABC, abstractmethod
from datetime import datetime


class FieldSpec:
    """描述一个图床配置字段（驱动 UI 渲染与校验）。"""

    def __init__(
        self,
        name,
        label,
        secret=False,
        placeholder="",
        help_text="",
        required=True,
        default="",
    ):
        self.name = name
        self.label = label
        self.secret = secret              # 密码类字段：前端用 password 框 + 默认不回显
        self.placeholder = placeholder
        self.help_text = help_text
        self.required = required
        self.default = default

    def to_dict(self):
        return {
            "name": self.name,
            "label": self.label,
            "secret": self.secret,
            "placeholder": self.placeholder,
            "help_text": self.help_text,
            "required": self.required,
        }


def _ts_key(original_name, prefix=""):
    """时间戳重命名：prefix + 年月日_时分秒_毫秒_随机4位.扩展名。"""
    ext = os.path.splitext(original_name)[1].lower()
    now = datetime.now()
    ts = now.strftime("%Y%m%d_%H%M%S") + f"_{int(now.microsecond / 1000):03d}"
    rand = uuid.uuid4().hex[:4]
    return f"{prefix}{ts}_{rand}{ext}"


class StorageProvider(ABC):
    """所有图床的基类。子类必须定义 name / display_name / fields，并实现核心方法。"""

    # 唯一标识（存库的 provider 字段、注册表 key 都用它）
    name: str = ""
    # 展示名（配置页、卡片徽标用）
    display_name: str = ""
    # 字段模板列表（驱动配置页渲染 + 校验）
    fields: list[FieldSpec] = []

    def __init__(self, config: dict | None = None):
        self.config = config or {}

    # ---------- 校验 ----------
    def validate(self) -> dict:
        """
        校验当前 config 是否可用于上传。
        返回 {字段名: 错误信息}；为空字典表示通过。
        子类可重写以追加格式校验。
        """
        errors: dict[str, str] = {}
        for f in self.fields:
            if not f.required:
                continue
            val = (self.config.get(f.name) or "").strip()
            if not val:
                errors[f.name] = f"必填项「{f.label}」不能为空"
        return errors

    def is_configured(self) -> bool:
        return len(self.validate()) == 0

    # ---------- 对象名（key）生成 ----------
    def build_key(self, original_name: str) -> str:
        """默认在文件名前加 img/ 前缀；子类可按需覆盖（如 GitHub 用配置目录）。"""
        return _ts_key(original_name, prefix="img/")

    # ---------- 核心操作（必须由子类实现） ----------
    @abstractmethod
    def upload(self, local_path: str, key: str, original_name: str = "") -> dict:
        """
        上传本地文件到本图床。
        成功返回 {"key": 最终对象名, "url": 可访问链接}；失败抛 StorageError。
        """
        raise NotImplementedError

    @abstractmethod
    def delete(self, key: str) -> str:
        """
        删除指定 key 的对象。
        返回 "deleted"（已删除）或 "missing"（云端本就不存在）；其他错误抛 StorageError。
        """
        raise NotImplementedError

    @abstractmethod
    def public_url(self, key: str) -> str:
        """把对象名拼成可公开访问的链接。"""

    # ---------- 缩略图（可选重写） ----------
    def thumb_url(self, url: str) -> str:
        """列表用的缩略图链接，默认返回原图（无样式处理的图床直接透传）。"""
        return url
