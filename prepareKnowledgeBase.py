import json
import requests
import faiss
import numpy as np
import threading
import time
import sys

# === 配置區 ===
JSONL_PATH = "combined.jsonl"
INDEX_PATH = "faiss_index.index"
METADATA_PATH = "metadata.json"
LM_STUDIO_EMBEDDING_URL = "http://localhost:1234/v1/embeddings"
EMBEDDING_MODEL = "text-embedding-bge-small-zh-v1.5"

# === spinner function ===
stop_spinner = False  # 控制 spinner 結束
def spinner():
    while not stop_spinner:
        for char in "|/-\\":
            sys.stdout.write(f"\r處理中 {char}")  # 旋轉動畫
            sys.stdout.flush()
            time.sleep(0.1)

def get_embedding(text: str):
    """呼叫 LM Studio API 取得嵌入向量"""
    response = requests.post(
        LM_STUDIO_EMBEDDING_URL,
        headers={"Content-Type": "application/json"},
        json={"input": text, "model": EMBEDDING_MODEL}
    )
    response.raise_for_status()
    return response.json()["data"][0]["embedding"]

def prepare_knowledge_embeddings(jsonl_path: str):
    global stop_spinner

    # 啟動 spinner 執行緒
    stop_spinner = False
    t = threading.Thread(target=spinner)
    t.start()

    try:
        # 計算總行數
        with open(jsonl_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        total = len(lines)

        embeddings = []
        metadatas = []

        for idx, line in enumerate(lines, start=1):
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
                print(f"\n[ERROR] 第 {idx} 條資料處理失敗：{e}")

            # 顯示進度數字
            sys.stdout.write(f"嵌入進度：({idx}/{total})")
            sys.stdout.flush()

        # FAISS 建立索引
        dim = len(embeddings[0])
        index = faiss.IndexFlatL2(dim)
        index.add(np.array(embeddings).astype("float32"))
        faiss.write_index(index, INDEX_PATH)

        # metadata 儲存
        with open(METADATA_PATH, "w", encoding="utf-8") as f:
            json.dump(metadatas, f, ensure_ascii=False, indent=2)

    finally:
        # 停止 spinner
        stop_spinner = True
        t.join()  # 等待 spinner 執行緒結束

    print("\n✅ 全部完成！索引與 metadata 已儲存")

if __name__ == "__main__":
    prepare_knowledge_embeddings(JSONL_PATH)
