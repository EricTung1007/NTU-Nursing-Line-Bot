"""Update check and one-click update from GitHub Releases.

Windows: downloads the new installer, verifies its SHA-256 (published by GitHub), runs it silently and
relaunches. macOS: downloads the .dmg and opens it so the user can drag the app over the old one.
Only an installed (frozen) app updates itself; a source checkout just reports the newer version.
"""
from __future__ import annotations

import logging
import re
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from . import paths
from .components import Downloader
from .settings import Settings
from .version import VERSION

log = logging.getLogger("updater")
REPO = "EricTung1007/NTU-Nursing-Line-Bot"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
CHECK_EVERY = 12 * 3600


def parse_version(v: str) -> Tuple[int, ...]:
    nums = re.findall(r"\d+", (v or "").lstrip("vV").split("-")[0])
    return tuple(int(x) for x in nums[:3]) or (0,)


def pick_asset(assets: List[Dict[str, Any]], platform: str = sys.platform) -> Optional[Dict[str, Any]]:
    want = ".exe" if platform == "win32" else ".dmg" if platform == "darwin" else None
    return next((a for a in assets if want and a["name"].endswith(want)), None)


class Updater(Downloader):
    def __init__(self, settings: Settings):
        super().__init__()
        self.s = settings
        self.on_quit: Callable[[], None] = lambda: None
        self.state: Dict[str, Any] = {"current": VERSION, "latest": "", "available": False, "asset": "", "size": 0,
                                      "url": "", "checked_at": None, "error": "", "installable": paths.FROZEN}
        self._asset: Optional[Dict[str, Any]] = None
        self._lock = threading.Lock()

    def check(self) -> Dict[str, Any]:
        """Ask GitHub for the newest release. Network errors are reported, never raised."""
        try:
            r = self.http.get(API, timeout=15, headers={"Accept": "application/vnd.github+json"})
            r.raise_for_status()
            rel = r.json()
            asset = pick_asset(rel.get("assets", []))
            newer = parse_version(rel["tag_name"]) > parse_version(VERSION) and not VERSION.endswith("-dev")
            self._asset = asset
            self.state.update(latest=rel["tag_name"].lstrip("vV"), available=bool(newer and asset), url=rel.get("html_url", ""),
                              asset=asset["name"] if asset else "", size=asset["size"] if asset else 0, error="",
                              checked_at=time.time())
        except (requests.RequestException, ValueError, KeyError) as e:
            self.state.update(error="無法連到 GitHub，請檢查網路 / Cannot reach GitHub; check the network", checked_at=time.time())
            log.warning("update check failed: %s", e)
        return self.public()

    def public(self) -> Dict[str, Any]:
        return dict(self.state, job=dict(self._job))

    def start_background(self) -> None:
        def loop() -> None:
            time.sleep(20)  # let the app settle first
            while True:
                if self.s.bool("update_check"):
                    self.check()
                time.sleep(CHECK_EVERY)
        threading.Thread(target=loop, daemon=True, name="update-check").start()

    def install(self) -> bool:
        if not paths.FROZEN:
            self.state["error"] = "原始碼版本不能自動更新 / A source checkout cannot self-update"
            return False
        with self._lock:
            if self._job["running"] or not (self.state["available"] and self._asset):
                return False
            self._job.update(running=True, done=False, error="", bytes=0, total=0, current="update")
        threading.Thread(target=self._run, daemon=True, name="updater").start()
        return True

    def _run(self) -> None:
        try:
            a = self._asset or {}
            dest_dir = paths.DATA_DIR / "updates"
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / a["name"]
            digest = (a.get("digest") or "").replace("sha256:", "") or None  # GitHub publishes it; verify when present
            self._download(a["browser_download_url"], dest, digest)
            log.info("update downloaded: %s", dest)
            if sys.platform == "win32":
                # Detached so it outlives us; Inno closes the old app, installs over it and relaunches it (silent mode).
                subprocess.Popen([str(dest), "/SILENT", "/SP-", "/CLOSEAPPLICATIONS"], close_fds=True,
                                 creationflags=0x00000008 | 0x00000200)
                self.on_quit()
            else:
                subprocess.Popen(["open", str(dest)])  # shows the dmg: drag the app over the old one
        except Exception as e:
            log.exception("update failed")
            self._job["error"] = str(e) or e.__class__.__name__
        finally:
            self._job.update(running=False, done=True)
