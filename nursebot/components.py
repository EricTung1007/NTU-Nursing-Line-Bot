"""First-run component installer: the app fetches what it needs, so nurses never place files by hand.

Components: llama-server (llama.cpp release), cloudflared (Cloudflare release), a chat model and an
embedding model (Hugging Face GGUF). Downloads resume after an interruption, models are verified
against pinned SHA-256 hashes, and everything lands in bin/ and models/.
"""
from __future__ import annotations

import hashlib
import logging
import os
import platform
import shutil
import sys
import tarfile
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import requests

from . import paths

log = logging.getLogger("components")

# Verified against the live release/Hugging Face listings when this was written.
LLAMA_FALLBACK_TAG = "b12556"
CLOUDFLARED = "https://github.com/cloudflare/cloudflared/releases/latest/download/"
CHAT_MODEL = {
    "file": "Qwen3.5-4B-Q4_K_M.gguf",
    "url": "https://huggingface.co/unsloth/Qwen3.5-4B-GGUF/resolve/main/Qwen3.5-4B-Q4_K_M.gguf",
    "sha256": "00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4", "size": 2740937888,
}
EMBED_MODEL = {
    "file": "bge-small-zh-v1.5-f16.gguf",
    "url": "https://huggingface.co/CompendiumLabs/bge-small-zh-v1.5-gguf/resolve/main/bge-small-zh-v1.5-f16.gguf",
    "sha256": "ab9b81d9cd329c712eee379cf0068eabe6a5e2a01d0def61535eba9384085e2c", "size": 47886240,
}


@dataclass
class Component:
    id: str
    zh: str
    en: str
    approx_mb: int
    present: Callable[[], bool]


def _platform_key() -> str:
    m = platform.machine().lower()
    arm = m in ("arm64", "aarch64")
    if sys.platform == "win32":
        return "win-arm64" if arm else "win-x64"
    if sys.platform == "darwin":
        return "macos-arm64" if arm else "macos-x64"
    return "linux-x64"


def llama_asset(session: requests.Session) -> Tuple[str, str]:
    """(url, archive name) for this platform. Looks at recent releases, falls back to a pinned build."""
    key = _platform_key()
    want = {"win-x64": "bin-win-cpu-x64.zip", "win-arm64": "bin-win-cpu-arm64.zip", "macos-arm64": "bin-macos-arm64.tar.gz",
            "macos-x64": "bin-macos-x64.tar.gz", "linux-x64": "bin-ubuntu-x64.tar.gz"}[key]
    try:
        r = session.get("https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=5", timeout=15)
        r.raise_for_status()
        for rel in r.json():
            for a in rel.get("assets", []):
                if a["name"].endswith(want):
                    return a["browser_download_url"], a["name"]
    except (requests.RequestException, ValueError, KeyError) as e:
        log.warning("release lookup failed, using pinned build: %s", e)
    name = f"llama-{LLAMA_FALLBACK_TAG}-{want}"
    return f"https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_FALLBACK_TAG}/{name}", name


def cloudflared_asset() -> Tuple[str, str]:
    key = _platform_key()
    name = {"win-x64": "cloudflared-windows-amd64.exe", "win-arm64": "cloudflared-windows-amd64.exe",
            "macos-arm64": "cloudflared-darwin-arm64.tgz", "macos-x64": "cloudflared-darwin-amd64.tgz",
            "linux-x64": "cloudflared-linux-amd64"}[key]
    return CLOUDFLARED + name, name


class Installer:
    def __init__(self, present: Dict[str, Callable[[], bool]]):
        self.http = requests.Session()
        self.http.headers["User-Agent"] = "NTULineBot-installer"
        self.components: List[Component] = [
            Component("llama", "語言模型引擎 (llama.cpp)", "Model engine (llama.cpp)", 30, present["llama"]),
            Component("cloudflared", "LINE 連線工具 (cloudflared)", "LINE link tool (cloudflared)", 25, present["cloudflared"]),
            Component("embed", "檢索模型 (bge-small-zh)", "Embedding model (bge-small-zh)", 46, present["embed"]),
            Component("chat", "對話模型 (Qwen3.5-4B)", "Chat model (Qwen3.5-4B)", 2615, present["chat"]),
        ]
        self._job: Dict[str, object] = {"running": False, "done": True, "current": "", "bytes": 0, "total": 0,
                                        "error": "", "finished": []}
        self._lock = threading.Lock()

    # ---- status ------------------------------------------------------------
    def status(self) -> Dict[str, object]:
        items = [{"id": c.id, "zh": c.zh, "en": c.en, "mb": c.approx_mb, "present": c.present()} for c in self.components]
        missing = [i for i in items if not i["present"]]
        return {"items": items, "missing_mb": sum(i["mb"] for i in missing), "job": dict(self._job)}

    def missing(self) -> List[str]:
        return [c.id for c in self.components if not c.present()]

    # ---- job ---------------------------------------------------------------
    def start(self) -> bool:
        with self._lock:
            if self._job["running"]:
                return False
            self._job = {"running": True, "done": False, "current": "", "bytes": 0, "total": 0, "error": "", "finished": []}
        threading.Thread(target=self._run, daemon=True, name="installer").start()
        return True

    def _run(self) -> None:
        try:
            paths.ensure_dirs()
            for c in self.components:
                if c.present():
                    continue
                self._job.update(current=c.id, bytes=0, total=0)
                self._install(c.id)
                self._job["finished"].append(c.id)  # type: ignore[union-attr]
            self._job["current"] = ""
        except Exception as e:
            log.exception("install failed")
            self._job["error"] = str(e) or e.__class__.__name__
        finally:
            self._job.update(running=False, done=True)

    def _install(self, cid: str) -> None:
        if cid == "llama":
            url, name = llama_asset(self.http)
            self._fetch_archive(url, name, paths.BIN_DIR, {"llama-server", "llama-server.exe"})
        elif cid == "cloudflared":
            url, name = cloudflared_asset()
            if name.endswith(".tgz"):
                self._fetch_archive(url, name, paths.BIN_DIR, {"cloudflared"})
            else:
                dest = paths.BIN_DIR / ("cloudflared.exe" if name.endswith(".exe") else "cloudflared")
                self._download(url, dest)
                os.chmod(dest, 0o755)
        else:
            spec = CHAT_MODEL if cid == "chat" else EMBED_MODEL
            self._download(spec["url"], paths.MODELS_DIR / spec["file"], spec["sha256"])

    # ---- primitives --------------------------------------------------------
    def _download(self, url: str, dest: Path, sha256: Optional[str] = None) -> None:
        """Resumable download to dest.part, verified, then atomically renamed."""
        part = dest.with_suffix(dest.suffix + ".part")
        last: Optional[Exception] = None
        for attempt in range(4):
            try:
                have = part.stat().st_size if part.exists() else 0
                headers = {"Range": f"bytes={have}-"} if have else {}
                with self.http.get(url, headers=headers, stream=True, timeout=30, allow_redirects=True) as r:
                    if r.status_code == 416:  # already complete
                        break
                    r.raise_for_status()
                    if have and r.status_code != 206:  # server ignored Range: start over
                        have = 0
                    total = have + int(r.headers.get("Content-Length", 0))
                    self._job.update(bytes=have, total=total)
                    with open(part, "ab" if have else "wb") as f:
                        for chunk in r.iter_content(1 << 20):
                            f.write(chunk)
                            self._job["bytes"] = int(self._job["bytes"]) + len(chunk)  # type: ignore[arg-type]
                last = None
                break
            except (requests.RequestException, OSError) as e:
                last = e
                log.warning("download interrupted (%s), attempt %d", e, attempt + 1)
                time.sleep(2 + attempt * 3)
        if last:
            raise RuntimeError(f"下載中斷，請檢查網路後再按一次 / Download interrupted, check the network and retry: {last}")
        if sha256:
            h = hashlib.sha256()
            with open(part, "rb") as f:
                for block in iter(lambda: f.read(1 << 20), b""):
                    h.update(block)
            if h.hexdigest() != sha256:
                part.unlink(missing_ok=True)
                raise RuntimeError("檔案驗證失敗（下載損毀），請再試一次 / Checksum mismatch, please retry")
        os.replace(part, dest)

    def _fetch_archive(self, url: str, name: str, dest_dir: Path, must_have: set) -> None:
        tmp = dest_dir / (name + ".download")
        self._download(url, tmp)
        try:
            if name.endswith(".zip"):
                with zipfile.ZipFile(tmp) as z:
                    members = [(m, Path(m.filename).name) for m in z.infolist() if not m.is_dir()]
                    for m, base in members:  # flatten: llama-server wants its libraries beside it
                        with z.open(m) as src, open(dest_dir / base, "wb") as out:
                            shutil.copyfileobj(src, out)
            else:
                with tarfile.open(tmp) as t:
                    for m in t.getmembers():
                        if m.isfile():
                            with t.extractfile(m) as src, open(dest_dir / Path(m.name).name, "wb") as out:  # type: ignore[union-attr]
                                shutil.copyfileobj(src, out)
            for p in dest_dir.iterdir():
                if p.name in must_have or p.suffix in (".dylib", ".so"):
                    os.chmod(p, 0o755)
        finally:
            tmp.unlink(missing_ok=True)
        if not any((dest_dir / n).exists() for n in must_have):
            raise RuntimeError(f"壓縮檔內找不到 {'/'.join(sorted(must_have))} / not found in the archive")
