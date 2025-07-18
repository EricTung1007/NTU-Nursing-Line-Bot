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

# 建立 FAISS 索引與 metadata
def prepare_knowledge_embeddings(jsonl_path: str):
    embeddings = []
    metadatas = []

    with open(jsonl_path, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f):
            entry = json.loads(line)
            text = entry.get("text", "")
            source = entry.get("source", "")
            page = entry.get("page", -1)
            metadata = {"text": text, "source": source, "page": page}
            try:
                vec = get_embedding(text)
                embeddings.append(vec)
                metadatas.append(metadata)
            except Exception as e:
                print(f"[ERROR] on {idx}: {e}")

    # 儲存 FAISS index + metadata
    dim = len(embeddings[0])
    index = faiss.IndexFlatL2(dim)
    index.add(np.array(embeddings).astype("float32"))
    faiss.write_index(index, INDEX_PATH)

    with open(METADATA_PATH, "w", encoding="utf-8") as f:
        json.dump(metadatas, f, ensure_ascii=False, indent=2)

# 查詢相關段落
def query_with_context(user_message: str, top_k: int = 3) -> List[Dict]:
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
    print(f"[DEBUG] Retrieved {len(results)} context(s)")
    return results

# 組合提示詞（Prompt）
def build_augmented_prompt(
    contexts,
    user_question,
    modelname,
    system_message=None,
    history_text="",
    g_value=0,
    p_value=0
):
    # 🔗 拼接 context 文字
    context_text, source_summary = summarize_context_with_pages(contexts, user_question)
    print(f"[DEBUG] Final context length: {len(context_text)} 字")

    # 🟡 fallback：沒有資料
    if contexts is None or len(contexts) == 0 or not context_text.strip():
        fallback_system_message = (
        "⚠️ 你是一位產科與母嬰護理顧問，請先判斷使用者訊息：\n"
        "1. 如果使用者只是打招呼（如：您好、哈囉、Hi），請回：「您好 👋 有什麼我可以協助的嗎？」\n"
        "2. 如果使用者問了與產科及母嬰護理無關的問題（如程式撰寫、心理諮詢、占卜等），不須附上參考資料及電話，請只回應：「❌ 此問題與產科及母嬰護理無關，無法協助。」\n"
        "3. 如果使用者問了屬於產科的相關問題，但缺乏資料，請只回答：\n\n"
        "資料不足，其餘婦產科護理問題建議洽詢專業醫護人員：\n"
        "• 台大醫院總機： (02) 2312-3456\n"
        "• 衛教專線： 轉 266546\n"
        "• 診後說明處： 轉 266549\n"
        "• 9F 產房護理站： 轉 270908 或 270909\n"
        "• 衛福部孕產婦關懷專線： 0800-870-870\n\n"
        "⚠️ 不要編造答案，也不要列出其他問句。"
)

    

        print("[⚠️ Fallback] No context found, using fallback message.")
        return {
            "model": modelname,
            "messages": [
                {"role": "system", "content": fallback_system_message},
                {"role": "user", "content": f"{user_question}（⚠ 查無相關資料）"}
            ],
            "temperature": 0.4,
            "max_tokens": 5000,
            "stream": False
        }

    # 🟢 正常 system_message
    system_message = (
    "⚠️ 你是一位產科與母嬰護理顧問，請根據參考資料回答問題：\n"
    "✅ **只回覆與問題最相關的重點，不要將所有資料全部列出**。\n"
    "✅ 回答要簡短、專業、避免冗長分析與贅述。\n"
    "✅ 正文中的資料來源，統一由程式在回答末尾附上。\n"
    "✅ 結尾不要多餘提問（如「請問您還有其他問題嗎？」）。\n"
    "⚠️ 如果資料不足請說明：「資料中無相關內容，建議洽詢專業人員」。\n"
    "⚠️ 禁止回答與產科無關的問題（如程式撰寫、心理諮詢、占卜等）。\n\n"
    f"📖 參考資料：\n{context_text}\n\n"
    f"🗂 過往對話紀錄:\n{history_text}\n\n"
    f"👩‍🍼 使用者孕產史: 懷過 {g_value} 胎，生過 {p_value} 胎。\n"
)

    return {
        "model": modelname,
        "messages": [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_question}
        ],
        "temperature": 0.6,
        "max_tokens": 5000,
        "stream": False
    }

# 摘要 context 並附來源清單
def summarize_context_with_pages(contexts: List[Dict], user_question: str) -> (str, str):
    combined_text = "\n\n".join([
        f"【{c['source']} 第{c['page']}頁】\n{c['text']}"
        for c in contexts
    ])
    
    sources = []
    for c in contexts:
        page_info = f"{c['source']} 第{c['page']}頁" if c['page'] != -1 else c['source']
        if page_info not in sources:
            sources.append(page_info)

    source_summary = "；".join(sources)



    if len(combined_text) < 800:
        return combined_text, source_summary  # 不摘要也傳回來源清單

    summary_prompt = {
        "model": "gemma-3-4b-it",
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是一位產科與母嬰護理顧問，請將以下資料整理為完整答案，不要刻意濃縮或刪減重點，保持足夠長度並保留來源頁碼（書名 第X頁）。"
                    "✅ 正文中如有來源頁碼（【書名 第X頁】），不要穿插在回答中間。\n"
                    "✅ 回答最後集中列出資料來源清單（含頁碼），資料來源不能在中間出現，只能集中列出資料來源頁碼清單，不要使用括弧如【】，使用格式應為[引用資料:書名，頁碼]。"
                    "不要編造新的內容。"
                )
            },
            {"role": "user", "content": f"使用者問題: {user_question}\n\n資料:\n{combined_text}"}
        ],
        "temperature": 0,
        "max_tokens": 5000,
        "stream": False
    }

    try:
        resp = requests.post(f"{LMStudioIp}/v1/chat/completions",
                             headers={"Content-Type": "application/json"},
                             json=summary_prompt)
        result = resp.json()
        summary_text = result["choices"][0]["message"]["content"].strip()
        if not summary_text:
            print("[⚠️ Warning] LLM 摘要是空的，直接用原始 context")
            return combined_text, source_summary
        print(f"[✅ 摘要完成] {len(summary_text)} 字")
        return summary_text, source_summary
    except Exception as e:
        print(f"[❌ LLM 摘要失敗] {e}")
        return combined_text, source_summary  # fallback: 用原始資料
