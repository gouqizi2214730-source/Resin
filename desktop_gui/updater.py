"""应用内自动更新模块 (检查 Fork 仓库与上游仓库 Releases 并支持 Windows Setup.exe 与 Android APK 一键更新)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from . import __repo_name__, __repo_owner__, __upstream_name__, __upstream_owner__, __version__


USER_AGENT = "Mozilla/5.0 (compatible; Google-Agent; +https://developers.google.com/crawling/docs/crawlers-fetchers/google-agent)"


class AutoUpdater:
    """检查 GitHub Releases 中的最新 Setup.exe 与 APK 安装包并支持一键下载安装."""

    def __init__(
        self,
        current_version: str = __version__,
        fork_owner: str = __repo_owner__,
        fork_repo: str = __repo_name__,
        upstream_owner: str = __upstream_owner__,
        upstream_repo: str = __upstream_name__,
    ) -> None:
        self.current_version = current_version.lstrip("v")
        self.fork_owner = fork_owner
        self.fork_repo = fork_repo
        self.upstream_owner = upstream_owner
        self.upstream_repo = upstream_repo

    @staticmethod
    def _parse_version(ver: str) -> tuple:
        clean = ver.lstrip("v").split("-")[0]
        parts = []
        for p in clean.split("."):
            try:
                parts.append(int(p))
            except ValueError:
                parts.append(0)
        return tuple(parts)

    def _fetch_latest_release(self, owner: str, repo: str) -> Optional[Dict[str, Any]]:
        url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
        }
        try:
            req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except Exception:
            return None

    def check_for_updates(self) -> Dict[str, Any]:
        fork_rel = self._fetch_latest_release(self.fork_owner, self.fork_repo)
        upstream_rel = self._fetch_latest_release(self.upstream_owner, self.upstream_repo)

        target_rel = fork_rel or upstream_rel
        if not target_rel:
            return {
                "ok": False,
                "has_update": False,
                "current_version": self.current_version,
                "latest_version": self.current_version,
                "message": "暂时无法连接 GitHub Releases，请检查网络或稍后重试。",
            }

        tag = target_rel.get("tag_name", f"v{self.current_version}")
        latest_ver = tag.lstrip("v")
        assets = target_rel.get("assets", [])

        setup_exe_url = ""
        apk_url = ""
        for a in assets:
            name = a.get("name", "")
            dl = a.get("browser_download_url", "")
            if name.endswith("-Setup-win64.exe") or name.endswith(".exe"):
                setup_exe_url = dl
            elif name.endswith(".apk"):
                apk_url = dl

        has_update = self._parse_version(latest_ver) > self._parse_version(self.current_version)
        return {
            "ok": True,
            "has_update": has_update,
            "current_version": self.current_version,
            "latest_version": latest_ver,
            "tag_name": tag,
            "html_url": target_rel.get("html_url", f"https://github.com/{self.fork_owner}/{self.fork_repo}/releases"),
            "setup_exe_url": setup_exe_url,
            "apk_url": apk_url,
            "body": target_rel.get("body", ""),
            "upstream_tag": upstream_rel.get("tag_name", "") if upstream_rel else "",
            "message": (
                f"发现新版本 {tag}！" if has_update else f"当前已是最新版本 (v{self.current_version} / 最新 Release: {tag})"
            ),
        }

    def download_and_install_windows_setup(
        self,
        download_url: str,
        progress_cb: Optional[Callable[[int], None]] = None,
    ) -> Dict[str, Any]:
        if not download_url:
            return {"ok": False, "message": "未找到 Windows Setup.exe 下载链接"}
        try:
            tmp_dir = Path(tempfile.gettempdir()) / "ResinUpdate"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            target_file = tmp_dir / "Resin-Setup-win64.exe"

            req = urllib.request.Request(download_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=120) as resp:
                total = int(resp.headers.get("Content-Length", "0"))
                downloaded = 0
                with open(target_file, "wb") as f:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0 and progress_cb:
                            progress_cb(int(downloaded * 100 / total))

            if sys.platform == "win32":
                subprocess.Popen([str(target_file)], close_fds=True)
                return {"ok": True, "path": str(target_file), "message": f"已下载并启动安装程序: {target_file}"}
            return {"ok": True, "path": str(target_file), "message": f"安装包已下载至: {target_file}"}
        except Exception as exc:
            return {"ok": False, "message": f"下载更新失败: {exc}"}
