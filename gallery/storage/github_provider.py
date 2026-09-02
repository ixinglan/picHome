"""
GitHub 仓库存储实现（把图片当作仓库文件提交）。

适合「图床 + 版本管理」场景：图片存到指定仓库的目录里，通过 raw 链接访问。
注意：GitHub 单文件建议 < 25MB，且每次上传是一次 git commit。
"""
import base64
from urllib.parse import quote

from .base import FieldSpec, StorageProvider, _ts_key
from .exceptions import StorageError


class GitHubProvider(StorageProvider):
    name = "github"
    display_name = "GitHub 仓库"
    fields = [
        FieldSpec("token", "Personal Access Token", secret=True,
                  help_text="需 repo 权限；建议用 fine-grained token 并只授权目标仓库。"),
        FieldSpec("repo", "仓库 owner/name", placeholder="octocat/imgs"),
        FieldSpec("branch", "分支", placeholder="main"),
        FieldSpec("path", "存放目录", placeholder="images/", default="images/"),
        FieldSpec(
            "raw_base",
            "Raw 基础地址（可选）",
            required=False,
            placeholder="https://raw.githubusercontent.com/octocat/imgs/main/",
            help_text="留空则自动拼：https://raw.githubusercontent.com/{repo}/{branch}/",
        ),
        FieldSpec("committer_name", "提交者名称", required=False, default="picHome"),
        FieldSpec("committer_email", "提交者邮箱", required=False, default="pichome@local"),
    ]

    def build_key(self, original_name):
        folder = (self.config.get("path") or "images/").strip()
        if folder and not folder.endswith("/"):
            folder += "/"
        return _ts_key(original_name, prefix=folder)

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.config['token']}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _api_base(self):
        repo = (self.config.get("repo") or "").strip()
        if "/" not in repo:
            raise StorageError("GitHub 仓库格式应为 owner/name")
        return f"https://api.github.com/repos/{repo}"

    def upload(self, local_path, key, original_name=""):
        import requests

        try:
            headers = self._headers()
            api = self._api_base()
        except KeyError as e:
            raise StorageError(f"GitHub 配置缺失：{e}")
        branch = (self.config.get("branch") or "main").strip()

        with open(local_path, "rb") as f:
            content = base64.b64encode(f.read()).decode("ascii")

        url = f"{api}/contents/{quote(key)}"
        payload = {
            "message": f"upload {original_name}",
            "content": content,
            "branch": branch,
            "committer": {
                "name": self.config.get("committer_name") or "picHome",
                "email": self.config.get("committer_email") or "pichome@local",
            },
        }
        resp = requests.put(url, json=payload, headers=headers, timeout=60)
        if resp.status_code in (200, 201):
            return {"key": key, "url": self.public_url(key)}
        # 已存在则先取 sha 再覆盖提交
        if resp.status_code == 422 and "sha" in resp.text:
            sha = requests.get(url, headers=headers, timeout=30).json().get("sha")
            if sha:
                payload["sha"] = sha
                r2 = requests.put(url, json=payload, headers=headers, timeout=60)
                if r2.status_code in (200, 201):
                    return {"key": key, "url": self.public_url(key)}
        raise StorageError(f"GitHub 上传失败（{resp.status_code}）：{resp.text[:300]}")

    def delete(self, key):
        import requests

        try:
            headers = self._headers()
            api = self._api_base()
        except KeyError as e:
            raise StorageError(f"GitHub 配置缺失：{e}")
        url = f"{api}/contents/{quote(key)}"
        sha_resp = requests.get(url, headers=headers, timeout=30)
        if sha_resp.status_code == 404:
            return "missing"
        sha = sha_resp.json().get("sha")
        if not sha:
            return "missing"
        resp = requests.delete(
            url,
            headers=headers,
            json={"message": f"delete {key}", "sha": sha, "branch": (self.config.get("branch") or "main").strip()},
            timeout=30,
        )
        if resp.status_code in (200, 204):
            return "deleted"
        raise StorageError(f"GitHub 删除失败（{resp.status_code}）：{resp.text[:300]}")

    def public_url(self, key):
        raw = (self.config.get("raw_base") or "").strip().rstrip("/")
        if not raw:
            repo = (self.config.get("repo") or "").strip()
            branch = (self.config.get("branch") or "main").strip()
            if "/" not in repo:
                raise StorageError("GitHub 仓库格式应为 owner/name")
            raw = f"https://raw.githubusercontent.com/{repo}/{branch}"
        return f"{raw}/{key}"
