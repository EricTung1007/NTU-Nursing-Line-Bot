# RAG module
import json
import logging
import requests
import faiss
import numpy as np
from typing import List, Dict, Tuple
from collections import defaultdict

from prompts import normal_system_prompt
from config import EMBEDDING_ENDPOINT, EMBEDDING_MODEL, INDEX_PATH, METADATA_PATH

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cached FAISS index & metadata (loaded once, reused across queries)
# ---------------------------------------------------------------------------
_index = None
_metadatas = None


def _load_index():
    """Load FAISS index and metadata from disk (cached after first call)."""
    global _index, _metadatas
    if _index is None:
        logger.info("Loading FAISS index from %s ...", INDEX_PATH)
        _index = faiss.read_index(INDEX_PATH)
        with open(METADATA_PATH, "r", encoding="utf-8") as f:
            _metadatas = json.load(f)
        logger.info("Loaded %d vectors, %d metadata entries", _index.ntotal, len(_metadatas))
    return _index, _metadatas


# ---------------------------------------------------------------------------
# Embedding helper
# ---------------------------------------------------------------------------
def get_embedding(text: str) -> List[float]:
    response = requests.post(
        EMBEDDING_ENDPOINT,
        headers={"Content-Type": "application/json"},
        json={"input": text, "model": EMBEDDING_MODEL},
        timeout=15
    )
    return response.json()["data"][0]["embedding"]


# ---------------------------------------------------------------------------
# Query relevant passages
# ---------------------------------------------------------------------------
def query_with_context(user_message: str, top_k: int = 10) -> List[Dict]:
    query_vector = get_embedding(user_message)
    index, metadatas = _load_index()

    D, I = index.search(np.array([query_vector]).astype("float32"), top_k)
    logger.debug("FAISS distances: %s", D[0])

    results = []
    for dist, idx in zip(D[0], I[0]):
        if dist < 1.2:
            results.append(metadatas[idx])

    if not results:
        logger.debug("No context found (all distances >= 1.2)")
        return []

    logger.debug("Retrieved %d context(s)", len(results))
    return results


# ---------------------------------------------------------------------------
# Build augmented prompt
# ---------------------------------------------------------------------------
def build_augmented_prompt(
    contexts,
    user_question,
    modelname,
    system_message=None,
    history_text="",
    g_value=0,
    p_value=0,
    week_value=None,
    isdad=None,
    trimester=None
):
    isdad_status = (
        "是準爸爸" if isdad is True
        else "不是準爸爸" if isdad is False
        else "是否為準爸爸：未知"
    )

    trimester = (
        "懷孕初期" if int(week_value) <= 12
        else "懷孕中期" if 13 <= int(week_value) <= 28
        else "懷孕後期"
    )

    # Combine context text and sources
    context_text, source_summary = summarize_context_with_pages(contexts, user_question)

    # Fallback: no usable context
    if contexts is None or len(contexts) == 0 or not context_text.strip():
        return None, None

    # Build system message
    system_message = f"""
        {normal_system_prompt}\n
        📖 參考資料：
        {context_text}\n
        🗂 使用者資料：
        • 懷孕次數 G：{g_value}
        • 生產次數 P：{p_value}
        • 使用者身份：{isdad_status}
        • 目前孕週：{week_value or '未提供'} 週，{trimester}
        • 歷史對話紀錄：{history_text}
        """

    return {
        "model": modelname,
        "messages": [
            {"role": "user", "content": f"{system_message}\n\n使用者問題：\n{user_question}"}
        ],
        "temperature": 0.6,
        "max_tokens": 1200,  # Reasoning models need headroom for thinking + answer
        "stream": False
    }, source_summary


# ---------------------------------------------------------------------------
# Summarize context with grouped page sources
# ---------------------------------------------------------------------------
def summarize_context_with_pages(contexts: List[Dict], user_question: str) -> Tuple[str, str]:
    combined_text = "\n\n".join([f"{c['text']}" for c in contexts])

    book_pages = defaultdict(set)
    for c in contexts:
        if c["page"] != -1:
            book_pages[c["source"]].add(c["page"])
        else:
            book_pages[c["source"]].add("無頁碼")

    grouped_sources = []
    for book, pages in book_pages.items():
        page_list = sorted(pages, key=lambda x: (isinstance(x, int), x))
        page_str = ",".join(str(p) for p in page_list)
        grouped_sources.append(f"{book} 第{page_str}頁")

    source_summary = "; ".join(grouped_sources)
    return combined_text, source_summary
