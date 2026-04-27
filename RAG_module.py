#rag module
import json
import requests
import faiss
import numpy as np
from typing import List, Dict, Tuple

from prompts import normal_system_prompt
from config import EMBEDDING_ENDPOINT, EMBEDDING_MODEL, INDEX_PATH, METADATA_PATH

# 輔助函式：送出 embedding 請求
def get_embedding(text: str) -> List[float]:
    response = requests.post(
        EMBEDDING_ENDPOINT,
        headers={"Content-Type": "application/json"},
        json={"input": text, "model": EMBEDDING_MODEL}
    )
    return response.json()["data"][0]["embedding"]


# 查詢相關段落
def query_with_context(user_message: str, top_k: int = 10) -> List[Dict]:
    query_vector = get_embedding(user_message)
    index = faiss.read_index(INDEX_PATH)

    with open(METADATA_PATH, "r", encoding="utf-8") as f:
        metadatas = json.load(f)

    D, I = index.search(np.array([query_vector]).astype("float32"), top_k)
    #print("FAISS distance:", D[0])
    #print("FAISS index:", I[0])

    results = []
    for dist, idx in zip(D[0], I[0]):
        if dist < 1.2:  # ⚠️ 放寬距離門檻
            results.append(metadatas[idx])

    if not results:
       # print("[⚠️ Fallback] No context found.")
        return []
 

    #print(f"[DEBUG] Retrieved {len(results)} context(s)")
    return results



# 🟢 組合提示詞（Prompt）
def build_augmented_prompt(
    contexts,
    user_question,
    modelname,
    system_message=None,
    history_text="",
    g_value=0,
    p_value=0,
    week_value=None,
    isdad = None,
    trimester = None
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
    
    
    # 🔗 拼接 context 文字與來源
    context_text, source_summary = summarize_context_with_pages(contexts, user_question)
    #print(f"[DEBUG] Final context length: {len(context_text)} 字")

    # 🟡 fallback：沒有資料
    if contexts is None or len(contexts) == 0 or not context_text.strip():

        #print("[⚠️ Fallback] No context found, using fallback message.")
        return None, None


    # 🟢 正常提示詞
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

    #print("[DEBUG]正常問答輸入 system_message: ", system_message)

    return {
        "model": modelname,
        "messages": [
            {"role": "user", "content": f"{system_message}\n\n使用者問題：\n{user_question}"}
        ],
        "temperature": 0.6,
        "max_tokens": 600,
        "stream": False
    }, source_summary


# 📝 摘要 context 並集中來源
def summarize_context_with_pages(contexts: List[Dict], user_question: str) -> Tuple[str, str]:
    # 合併所有文字內容
    combined_text = "\n\n".join([
        f"{c['text']}" for c in contexts
    ])

    # 將來源按書名分組
    from collections import defaultdict
    book_pages = defaultdict(set)
    for c in contexts:
        if c['page'] != -1:
            book_pages[c['source']].add(c['page'])
        else:
            book_pages[c['source']].add("無頁碼")

    # 合併頁碼並組成來源字串
    grouped_sources = []
    for book, pages in book_pages.items():
        page_list = sorted(pages, key=lambda x: (isinstance(x, int), x))
        page_str = ",".join(str(p) for p in page_list)
        grouped_sources.append(f"{book} 第{page_str}頁")
    
    source_summary = "; ".join(grouped_sources)
    return combined_text, source_summary
