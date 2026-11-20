"""Cloudflare quick tunnel + LINE webhook registration, as an explicit non-blocking state machine.

    STOPPED -> STARTING -> UP            (tunnel URL known and LINE webhook set)
                       +-> FAILED       (cloudflared missing/exited, URL not found, LINE rejected)
    UP/FAILED -> STOPPED on stop()

The old code did this inline during startup (blocking up to 15s, then sleeping/retrying in the
main flow) and tracked "did a webhook ever arrive" in a global.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import sys
import threading
import time
from enum import Enum
from typing import Dict, Optional

from . import paths
from .line import LineClient

log = logging.getLogger("tunnel")
_URL = re.compile(r"https://[a-zA-Z0-9\-]+\.trycloudflare\.com")


class TState(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    UP = "up"
    FAILED = "failed"


def find_cloudflared() -> Optional[str]:
    for name in ("cloudflared.exe", "cloudflared", "cloudflared-windows-amd64.exe"):
        for base in (paths.BIN_DIR, paths.APP_DIR):
            p = base / name
            if p.is_file():
                return str(p)
    return shutil.which("cloudflared")


class Tunnel:
    def __init__(self, line: LineClient):
        self.line = line
        self.state = TState.STOPPED
        self.url = ""
        self.message = ""
        self.webhook_ok = False
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._gen = 0  # invalidates a stale starter thread after stop()

    def status(self) -> Dict[str, object]:
        return {"state": self.state.value, "url": self.url, "message": self.message, "webhook_ok": self.webhook_ok}

    def _set(self, gen: int, state: TState, message: str = "") -> None:
        with self._lock:
            if gen == self._gen:
                self.state, self.message = state, message

    def start(self, local_port: int) -> None:
        with self._lock:
            if self.state in (TState.STARTING, TState.UP):
                return
            self._gen += 1
            gen = self._gen
            self.state, self.message, self.url, self.webhook_ok = TState.STARTING, "啟動中", "", False
        threading.Thread(target=self._run, args=(gen, local_port), daemon=True).start()

    def _run(self, gen: int, port: int) -> None:
        exe = find_cloudflared()
        if not exe:
            return self._set(gen, TState.FAILED, "找不到 cloudflared，請放入 bin 資料夾")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        proc = subprocess.Popen([exe, "tunnel", "--url", f"http://127.0.0.1:{port}"], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, creationflags=flags)
        self._proc = proc
        found = threading.Event()

        def drain() -> None:  # keep reading so the pipe never fills and stalls cloudflared
            for line in proc.stdout:  # type: ignore[union-attr]
                m = _URL.search(line)
                if m and "api.trycloudflare.com" not in m.group(0) and not found.is_set():
                    self.url = m.group(0)
                    found.set()

        threading.Thread(target=drain, daemon=True).start()
        if not found.wait(30):
            return self._set(gen, TState.FAILED, "無法取得公開網址（請檢查網路）")
        endpoint = f"{self.url}/callback"
        for _ in range(6):
            if gen != self._gen:
                return
            time.sleep(3)
            if self.line.set_webhook(endpoint):
                self.webhook_ok = self.line.test_webhook(endpoint)
                return self._set(gen, TState.UP, "已連線" if self.webhook_ok else "已設定，但 LINE 驗證未通過")
        self._set(gen, TState.FAILED, "LINE 拒絕設定 Webhook，請檢查 Channel Access Token")

    def stop(self) -> None:
        with self._lock:
            self._gen += 1
            self.state, self.message, self.url = TState.STOPPED, "", ""
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None
