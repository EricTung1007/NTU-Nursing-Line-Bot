"""Knowledge base: source documents -> embeddings -> FAISS index, managed from the GUI.

Staff drop in PDFs (or .txt/.md) and press one button; no scripts. Embedding is batched (the old
prep.py made one HTTP call per page) and the new index is swapped in atomically.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from .llm import LlmClient
from .settings import Settings

log = logging.getLogger("kb")
SOURCE_EXTS = (".pdf", ".txt", ".md")
BATCH = 16


class Build(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


def safe_name(name: str) -> str:
    """Keep Chinese filenames; drop any path component."""
    return Path(name.replace("\\", "/")).name.strip()


class KnowledgeBase:
    def __init__(self, kb_dir: Path, settings: Settings, llm: LlmClient):
        self.dir, self.s, self.llm = kb_dir, settings, llm
        self.index_path = kb_dir / "faiss_index.index"
        self.meta_path = kb_dir / "metadata.json"
        self.info_path = kb_dir / "kb_info.json"
        self._index = None
        self._meta: List[Dict[str, Any]] = []
        self._lock = threading.RLock()
        self.build = {"state": Build.IDLE.value, "done": 0, "total": 0, "message": ""}
        self._thread: Optional[threading.Thread] = None

    # ---- query -------------------------------------------------------------
    def _load(self) -> None:
        import faiss
        with self._lock:
            if self._index is None:
                self._index = faiss.read_index(str(self.index_path))
                self._meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
                log.info("loaded %d vectors", self._index.ntotal)

    def search(self, vector: List[float], k: int, max_distance: float) -> List[Dict[str, Any]]:
        self._load()
        with self._lock:
            index, meta = self._index, self._meta
        dist, ids = index.search(np.asarray([vector], dtype="float32"), k)
        return [meta[i] for d, i in zip(dist[0], ids[0]) if i >= 0 and d < max_distance]

    # ---- documents ---------------------------------------------------------
    def sources(self) -> List[Path]:
        return sorted(p for p in self.dir.iterdir() if p.suffix.lower() in SOURCE_EXTS and p.is_file())

    def add_file(self, filename: str, data: bytes) -> str:
        name = safe_name(filename)
        if Path(name).suffix.lower() not in SOURCE_EXTS:
            raise ValueError("只支援 PDF / TXT / MD 檔案")
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / name).write_bytes(data)
        return name

    def remove_file(self, filename: str) -> None:
        p = self.dir / safe_name(filename)
        if p.exists() and p.suffix.lower() in SOURCE_EXTS:
            p.unlink()

    def status(self) -> Dict[str, Any]:
        info = self._info()
        counts: Dict[str, int] = {}
        if self.meta_path.exists():
            try:
                for m in json.loads(self.meta_path.read_text(encoding="utf-8")):
                    counts[m.get("source", "")] = counts.get(m.get("source", ""), 0) + 1
            except (OSError, ValueError):
                pass
        docs = [{"name": p.name, "size": p.stat().st_size, "chunks": counts.get(p.stem, 0)} for p in self.sources()]
        cur = self.embed_id()
        built_with = info.get("embed_id")
        return {
            "ready": self.index_path.exists() and self.meta_path.exists(),
            "vectors": sum(counts.values()),
            "docs": docs,
            "empty": [n for n in info.get("empty", []) if (self.dir / n).exists()],
            "pending": [d["name"] for d in docs if d["chunks"] == 0 and d["name"] not in info.get("empty", [])],
            "embed_mismatch": bool(built_with and built_with != cur),
            "built_with": built_with or "未知（舊版索引）",
            "legacy": bool(self.index_path.exists() and not self.info_path.exists()),
            "build": dict(self.build),
        }

    def embed_id(self) -> str:
        if self.s.get("llm_mode") == "external":
            return self.s.get("embed_model_name")
        from .llm import resolve_model
        m = resolve_model(self.s, "embed")
        return Path(m).name if m else "unknown"

    def _info(self) -> Dict[str, Any]:
        try:
            return json.loads(self.info_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    # ---- rebuild -----------------------------------------------------------
    def start_rebuild(self) -> bool:
        with self._lock:
            if self.build["state"] == Build.RUNNING.value:
                return False
            self.build = {"state": Build.RUNNING.value, "done": 0, "total": 0, "message": "讀取文件中"}
        self._thread = threading.Thread(target=self._rebuild, daemon=True)
        self._thread.start()
        return True

    @staticmethod
    def _chunks_for(path: Path) -> List[Dict[str, Any]]:
        if path.suffix.lower() == ".pdf":
            import fitz  # PyMuPDF, imported lazily: only needed when ingesting
            out = []
            with fitz.open(str(path)) as doc:
                for n, page in enumerate(doc, start=1):
                    text = " ".join(l.strip() for l in page.get_text("text").split("\n") if l.strip())
                    if text:
                        out.append({"source": path.stem, "page": n, "text": text})
            return out
        raw = path.read_text(encoding="utf-8", errors="ignore")
        paras, buf, out = [p.strip() for p in raw.split("\n\n") if p.strip()], "", []
        for p in paras:
            if buf and len(buf) + len(p) > 500:
                out.append({"source": path.stem, "page": -1, "text": buf})
                buf = ""
            buf = f"{buf}\n{p}".strip()
        if buf:
            out.append({"source": path.stem, "page": -1, "text": buf})
        return out

    def _rebuild(self) -> None:
        import faiss
        try:
            chunks: List[Dict[str, Any]] = []
            empty: List[str] = []  # e.g. scanned PDFs with no text layer; they need OCR, not a rebuild
            for p in self.sources():
                got = self._chunks_for(p)
                chunks += got
                if not got:
                    empty.append(p.name)
            if not chunks:
                raise RuntimeError("沒有可用的文件")
            self.build.update(total=len(chunks), message="建立向量中")
            vecs: List[List[float]] = []
            for i in range(0, len(chunks), BATCH):
                vecs += self.llm.embed([c["text"] for c in chunks[i:i + BATCH]])
                self.build["done"] = min(i + BATCH, len(chunks))
            arr = np.asarray(vecs, dtype="float32")
            index = faiss.IndexFlatL2(arr.shape[1])
            index.add(arr)
            # write beside, then replace: the live index is never half-written
            tmp_idx, tmp_meta = self.index_path.with_suffix(".tmp"), self.meta_path.with_suffix(".tmp")
            faiss.write_index(index, str(tmp_idx))
            tmp_meta.write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp_idx, self.index_path)
            os.replace(tmp_meta, self.meta_path)
            self.info_path.write_text(json.dumps({"embed_id": self.embed_id(), "chunks": len(chunks), "empty": empty}), encoding="utf-8")
            with self._lock:
                self._index, self._meta = index, chunks
            self.llm.clear_cache()
            self.build.update(state=Build.DONE.value, message=f"完成：{len(chunks)} 段")
        except Exception as e:  # surfaced in the GUI
            log.exception("knowledge base rebuild failed")
            self.build.update(state=Build.FAILED.value, message=str(e))
