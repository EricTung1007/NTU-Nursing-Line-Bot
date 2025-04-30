import requests
import numpy as np
import json

# === 讀取知識庫 ===
with open("knowledge_base.json", "r", encoding="utf-8") as f:
    knowledge_base = json.load(f)

# === 計算文字的 embedding ===
def get_embedding(text, model_name):
    response = requests.post(
        "http://172.20.10.4:1234/v1/embeddings",
        headers={"Content-Type": "application/json"},
        json={
            "input": text,
            "model": model_name
        }
    )
    if response.status_code != 200:
        print(f"❌ Embedding API 呼叫失敗！status: {response.status_code}")
        print("回傳內容：", response.text)
        return None  # 傳回 None 表示失敗

    response_json = response.json()

    if "data" not in response_json:
        print("❌ 回傳內容沒有 'data' 欄位！")
        print("回傳內容：", response_json)
        return None

    embedding = response_json["data"][0]["embedding"]
    return embedding

# === 餘弦相似度公式 ===
def cosine_similarity(vec1, vec2):
    vec1 = np.array(vec1)
    vec2 = np.array(vec2)
    return np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))

# === 預先把知識庫每一條 answer 做 embedding
def prepare_knowledge_embeddings(model_name):
    embeddings = []
    for item in knowledge_base:
        embedding = get_embedding(item["answer"], model_name)
        if embedding:
            embeddings.append(embedding)
        else:
            print(f"⚠️ 無法取得知識 '{item['question']}' 的 embedding，跳過。")
    return embeddings


# === 找最相似的資料（給外部呼叫）
def find_best_context(user_question, model_name, knowledge_embeddings):
    user_embedding = get_embedding(user_question, model_name)
    similarities = [cosine_similarity(user_embedding, kb_emb) for kb_emb in knowledge_embeddings]
    best_idx = np.argmax(similarities)
    return knowledge_base[best_idx]["answer"]
