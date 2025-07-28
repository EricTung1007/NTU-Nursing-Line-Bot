#rag module
import json
import requests
import faiss
import numpy as np
from typing import List, Dict

# 路徑 & 設定
INDEX_PATH = "faiss_index.index"
METADATA_PATH = "metadata.json"
LM_STUDIO_EMBEDDING_URL = "http://localhost:1234/v1/embeddings"
EMBEDDING_MODEL = "text-embedding-bge-small-zh-v1.5"
LMStudioIp = "http://127.0.0.1:1234"  # ⚠ 修改成你的 LM Studio API

# 輔助函式：送出 embedding 請求
def get_embedding(text: str) -> List[float]:
    response = requests.post(
        LM_STUDIO_EMBEDDING_URL,
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
    print("FAISS distance:", D[0])
    print("FAISS index:", I[0])

    results = []
    for dist, idx in zip(D[0], I[0]):
        if dist < 0.8:  # ⚠️ 放寬距離門檻
            results.append(metadatas[idx])

    if not results:
        print("[⚠️ Fallback] No context found.")
        return []
 

    print(f"[DEBUG] Retrieved {len(results)} context(s)")
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
    "懷孕初期" if int(week_value) < 12
    else "懷孕中期" if 13 < int(week_value) < 28
    else "懷孕後期" 
    )
    
    
    # 🔗 拼接 context 文字與來源
    context_text, source_summary = summarize_context_with_pages(contexts, user_question)
    print(f"[DEBUG] Final context length: {len(context_text)} 字")

    # 🟡 fallback：沒有資料
    if contexts is None or len(contexts) == 0 or not context_text.strip():
        fallback_system_message = (
            "⚠️ 你是一位產科與母嬰護理顧問，請先判斷使用者訊息：\n"
            "1. 如果使用者只是打招呼（如：您好、哈囉、Hi），請回：「您好 👋 有什麼我可以協助的嗎？」\n"
            "2. 如果使用者問了非孕產問題，請回：「此問題不屬於產科範圍，因此無法回答。」\n"
            "3. 如果資料不足，請回：「資料不足，建議洽詢專業醫護人員。」"
        )
        print("[⚠️ Fallback] No context found, using fallback message.")
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
    system_message = (
        "⚠️ 你是一位產科與母嬰護理顧問，請根據參考資料回答問題：\n"
        "✅ **回答僅保留與問題最相關的重點，不要列出全部 context。**\n"
        "✅ 回答長度應在150中文字左右，至多200中文字，需簡短、專業、去除非必要的贅字，且避免冗長分析與贅述。\n"
        #"✅ 正文中禁止插入資料來源，所有資料來源統一集中列在回答末尾。\n"
        "✅ 結尾不要多餘提問。\n"
        "⚠️ 如果資料不足，請說明：「資料中無相關內容，建議洽詢專業人員」。並提供以下所有電話聯絡資訊:\n"
        "• 台大醫院總機：(02) 2312-3456\n"
        "• 衛教專線：轉 266546\n"
        "• 診後說明處：轉 266549\n"
        "• 9F 產房護理站：轉 270908 或 270909\n"
        "• 衛福部孕產婦關懷諮詢專線：0800-870-870\n"
        "⚠️ 禁止回答與產科無關的問題（如程式撰寫、心理諮詢、占卜等）。\n"
        "如果使用者沒有問問題只有打招呼（如：您好、哈囉、Hi），請回：「您好 👋 有什麼我可以協助的嗎？」，不要提供其他建議，也不須嘗試回答問題\n"
        f"📖 參考資料：\n{context_text}\n\n"
        #f"🗂 過往對話紀錄:\n{history_text}\n\n"
        f"👩‍🍼 使用者資料: 懷過 {g_value} 胎，生過 {p_value} 胎，{isdad_status}。\n"
        f"📆 目前週數: {week_value if week_value else '未提供'} 週，處於{trimester}。\n"
    )
    print("正常問答輸入 system_message: ", system_message)

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
def summarize_context_with_pages(contexts: List[Dict], user_question: str) -> (str, str):
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
