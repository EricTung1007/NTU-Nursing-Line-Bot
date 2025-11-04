#rag module
import json
import requests
import faiss
import numpy as np
from typing import List, Dict, Tuple

from config import EMBEDDING_ENDPOINT, EMBEDDING_MODEL, INDEX_PATH, METADATA_PATH
'''
# 路徑 & 設定
INDEX_PATH = "faiss_index.index"
METADATA_PATH = "metadata.json"
LM_STUDIO_EMBEDDING_URL = "http://localhost:1234/v1/embeddings"
EMBEDDING_MODEL = "text-embedding-bge-small-zh-v1.5"
LMStudioIp = "http://127.0.0.1:1234"  # ⚠ 修改成你的 LM Studio API
'''
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
        if dist < 1.0:  # ⚠️ 放寬距離門檻
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
        fallback_system_message = (
            "你是一位產科與母嬰護理顧問。凡與孕期、產後或母嬰健康相關的症狀（例：頻尿、腰痠、胃脹氣、抽筋、睡眠、胎動、飲食、運動、產兆、哺乳）皆屬產科範圍。\n"
            "規則：\n"
            "1) 問候語→ 回：「您好，有什麼我可以協助的嗎？」\n"
            "2) 非孕產議題（程式、占卜等）→ 回覆不處理。\n"
            "3) 找不到資料→ 先給通用安全建議，再提醒就醫與可用諮詢管道。"
        )

        #print("[⚠️ Fallback] No context found, using fallback message.")
        return {
        "model": modelname,
        "messages": [
            {"role": "system", "content": fallback_system_message},
            {"role": "user", "content": f"{user_question}（⚠ 查無相關資料）"}
        ],
        "temperature": 0.4,
        "max_tokens": 10000,
        "stream": False
        }, None  # ⬅ 注意這個 None 是 source_summary 的佔位


    # 🟢 正常提示詞
    system_message = f"""
        你是一位專業【產科與母嬰照護顧問】，僅依據下方提供的參考資料解答懷孕相關問題。
        凡與孕期、產後或母嬰健康相關的常見症狀（如：頻尿、腰痠、抽筋、火燒心、便祕、失眠、胎動、飲食與運動）均視為產科範圍。

        🟩 回應規則：
        • 回答限150字內（最多200字），專業、簡潔。
        • 聚焦提問主題與可行建議，不複誦全部 context。
        • 不主動加結尾提問。
        • 非孕產議題不處理（心理諮商、程式、占卜等）。

        🟦 身分調整：
        • 準媽媽→ 以第一人稱對她建議。
        • 準爸爸→ 強調可協助與陪伴的具體作法。
        • 未知→ 使用中性表述。

        🟥 若資料不足：
        先給通用安全建議（警示症狀與就醫時機），再附就醫與諮詢管道。

        📖 參考資料：
        {context_text}

        🗂 使用者資料：
        • 懷孕次數 G：{g_value}
        • 生產次數 P：{p_value}
        • 使用者身份：{isdad_status}
        • 目前孕週：{week_value or '未提供'} 週，{trimester}
        """

    #print("[DEBUG]正常問答輸入 system_message: ", system_message)

    return {
        "model": modelname,
        "messages": [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_question}
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
