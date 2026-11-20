"""Local inference: llama.cpp `llama-server` supervised by the app, plus an OpenAI-compatible client.

No LM Studio. The app launches two llama-server processes (chat + embeddings) from models in
./models and a binary in ./bin (or on PATH). `llm_mode=external` points the same client at any
OpenAI-compatible URL instead, which also keeps old LM Studio setups working.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import sys
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Optional

import requests

from . import paths
from .settings import Settings

log = logging.getLogger("llm")
_EMBED_HINTS = ("embed", "bge", "e5", "gte", "minilm")


def _abs(cfg: str) -> Path:
    p = Path(cfg)
    return p if p.is_absolute() else paths.APP_DIR / p


def find_llama_server(settings: Settings) -> Optional[str]:
    cfg = settings.get("llama_server_path").strip()
    if cfg and _abs(cfg).exists():
        return str(_abs(cfg))
    for name in ("llama-server.exe", "llama-server"):
        p = paths.BIN_DIR / name
        if p.exists():
            return str(p)
    return shutil.which("llama-server")


def list_models() -> List[Path]:
    return sorted(paths.MODELS_DIR.glob("*.gguf"))


def _is_embed(p: Path) -> bool:
    return any(h in p.name.lower() for h in _EMBED_HINTS)


def resolve_model(settings: Settings, kind: str) -> Optional[str]:
    cfg = settings.get(f"{kind}_model_path").strip()
    if cfg:
        return str(_abs(cfg)) if _abs(cfg).exists() else None
    cands = [m for m in list_models() if _is_embed(m) == (kind == "embed")]
    return str(cands[0]) if cands else None


def clean_model_reply(text: str) -> str:
    """Strip reasoning traces some local models leak into content (behaviour kept from the old bot)."""
    if not text:
        return ""
    text = re.sub(r"(?is)<think>.*?</think>", "", text).strip()
    m = re.search(r"(?is)\*+\s*Draft\s+\d+\s*:\*+\s*(.*?)(?=\n\s*\*+\s*(?:Count|Critique|Wait)\b|\Z)", text)
    if m:
        text = m.group(1).strip()
    text = re.sub(
        r"(?is)^Thinking Process:\s*.*?(?=\n\s*(?:答案|回答|建議|您|你|太太|老婆|胎位|可以|如果|請|目前|一般|資料來源|[-•*]?\s*\*\*)|\Z)",
        "", text).strip()
    for marker in ("Final Answer:", "Final answer:", "Answer:", "回答：", "答案：", "建議："):
        if marker in text:
            text = text.split(marker, 1)[1].strip()
    if re.match(r"(?is)^[-* ]*(Role|Constraint|Content Focus|User Data|Conflict Resolution|Safety Check|Extract|"
                r"Drafting|Refining|Analyze|Analysis|Need to|We need|The reference|Data Insufficient)\b", text):
        return ""
    return text


class LlamaServers:
    """Starts/stops llama-server child processes. Readiness is reported by health checks."""

    def __init__(self, settings: Settings):
        self.s = settings
        self.procs: Dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()

    def _cmd(self, kind: str, exe: str, model: str) -> List[str]:
        port = self.s.int("chat_port" if kind == "chat" else "embed_port")
        cmd = [exe, "-m", model, "--host", "127.0.0.1", "--port", str(port),
               "-c", str(self.s.int("llm_ctx")), "-ngl", str(self.s.int("llm_gpu_layers"))]
        if kind == "embed":
            cmd += ["--embeddings"]
            if self.s.get("embed_pooling"):
                cmd += ["--pooling", self.s.get("embed_pooling")]
        return cmd

    def start(self) -> Dict[str, str]:
        """Returns {kind: problem} for anything that could not be started (empty = all good)."""
        problems: Dict[str, str] = {}
        exe = find_llama_server(self.s)
        if not exe:
            return {"llama-server": "找不到 llama-server，請放入 bin 資料夾"}
        with self._lock:
            for kind in ("chat", "embed"):
                if kind in self.procs and self.procs[kind].poll() is None:
                    continue
                model = resolve_model(self.s, kind)
                if not model:
                    problems[kind] = "找不到模型檔 (.gguf)，請放入 models 資料夾"
                    continue
                paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
                logf = open(paths.DATA_DIR / f"llama-{kind}.log", "ab")
                flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
                cmd = self._cmd(kind, exe, model)
                log.info("starting llama-server (%s): %s", kind, " ".join(cmd))
                self.procs[kind] = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT, creationflags=flags)
        return problems

    def stop(self) -> None:
        with self._lock:
            for p in self.procs.values():
                if p.poll() is None:
                    p.terminate()
            for p in self.procs.values():
                try:
                    p.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    p.kill()
            self.procs.clear()

    def running(self, kind: str) -> bool:
        p = self.procs.get(kind)
        return bool(p and p.poll() is None)


class LlmClient:
    def __init__(self, settings: Settings):
        self.s = settings
        self.http = requests.Session()  # keep-alive: no TCP handshake per message
        self._cache: "OrderedDict[str, List[float]]" = OrderedDict()
        self._cache_lock = threading.Lock()

    def _base(self, kind: str) -> str:
        if self.s.get("llm_mode") == "external":
            return self.s.get(f"external_{kind}_url").rstrip("/")
        return f"http://127.0.0.1:{self.s.int('chat_port' if kind == 'chat' else 'embed_port')}"

    def _model_name(self, kind: str) -> str:
        return self.s.get(f"{kind}_model_name") if self.s.get("llm_mode") == "external" else "local"

    def health(self) -> Dict[str, bool]:
        out = {}
        for kind in ("chat", "embed"):
            try:
                r = self.http.get(self._base(kind) + "/health" if self.s.get("llm_mode") != "external"
                                  else self._base(kind) + "/v1/models", timeout=2)
                out[kind] = r.status_code == 200
            except requests.RequestException:
                out[kind] = False
        return out

    def chat(self, messages: List[Dict[str, str]], *, max_tokens: Optional[int] = None,
             temperature: Optional[float] = None, timeout: int = 120) -> str:
        payload = {
            "model": self._model_name("chat"),
            "messages": messages,
            "temperature": self.s.float("temperature") if temperature is None else temperature,
            "max_tokens": max_tokens or self.s.int("max_tokens"),
            "stream": False,
            # Qwen3-style models: skip the thinking phase (replaces the old hand-built <think></think> prompt).
            "chat_template_kwargs": {"enable_thinking": False},
        }
        r = self.http.post(self._base("chat") + "/v1/chat/completions", json=payload, timeout=timeout)
        r.raise_for_status()
        msg = r.json()["choices"][0]["message"]
        return clean_model_reply((msg.get("content") or "").strip()) or \
            clean_model_reply((msg.get("reasoning_content") or "").strip())

    def embed(self, texts: List[str], timeout: int = 60) -> List[List[float]]:
        r = self.http.post(self._base("embed") + "/v1/embeddings",
                           json={"input": texts, "model": self._model_name("embed")}, timeout=timeout)
        r.raise_for_status()
        data = sorted(r.json()["data"], key=lambda d: d.get("index", 0))
        return [d["embedding"] for d in data]

    def embed_one(self, text: str) -> List[float]:
        """Cached single embedding: repeated questions (very common in patient education) skip the model."""
        with self._cache_lock:
            if text in self._cache:
                self._cache.move_to_end(text)
                return self._cache[text]
        vec = self.embed([text], timeout=15)[0]
        with self._cache_lock:
            self._cache[text] = vec
            if len(self._cache) > 256:
                self._cache.popitem(last=False)
        return vec

    def clear_cache(self) -> None:
        with self._cache_lock:
            self._cache.clear()
