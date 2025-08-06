import os
import json
import fitz  # PyMuPDF
import requests
import faiss
import numpy as np
import threading
import time
import sys
from pathlib import Path

# 設定檔（從 config.py 匯入）
from config import EMBEDDING_ENDPOINT, EMBEDDING_MODEL, INDEX_PATH, METADATA_PATH, JSONL_PATH

database_dir = Path(__file__).resolve().parent / "database"
if not database_dir.exists():
    database_dir.mkdir()

# === Spinner 動畫 ===
stop_spinner = False
def spinner():
    while not stop_spinner:
        for char in "|/-\\":
            sys.stdout.write(f"\r⏳ 嵌入中... {char}")
            sys.stdout.flush()
            time.sleep(0.1)

# === 呼叫 LM Studio 取得向量 ===
def get_embedding(text: str):
    response = requests.post(
        EMBEDDING_ENDPOINT,
        headers={"Content-Type": "application/json"},
        json={"input": text, "model": EMBEDDING_MODEL}
    )
    response.raise_for_status()
    return response.json()["data"][0]["embedding"]

# === 步驟 1：PDF ➜ JSONL ===
def pdf_to_jsonl(pdf_path: Path):
    print(f"\n📘 處理 PDF：{pdf_path.name}")
    doc = fitz.open(str(pdf_path))
    data = []
    for page_number, page in enumerate(doc, start=1):
        text = page.get_text("text")
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        paragraph = " ".join(lines)
        if paragraph:
            data.append({
                "source": pdf_path.stem,
                "page": page_number,
                "text": paragraph
            })
        print(f"  ✅ 第 {page_number} 頁")

    output_path = pdf_path.with_suffix(".jsonl")
    with open(output_path, "w", encoding="utf-8") as f:
        for entry in data:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"✅ 已轉為 JSONL：{output_path.name}")

# === 步驟 2：合併 JSONL ===
def merge_jsonl(folder: Path, output_file: Path):
    output_file = Path(output_file)  # ✅ 確保是 Path 物件
    print(f"\n📎 合併所有 JSONL 成 {output_file.name}")
    if output_file.exists():
        output_file.unlink()

    with open(output_file, "w", encoding="utf-8") as fout:
        for file in folder.glob("*.jsonl"):
            if file.name == output_file.name:
                continue
            print(f"  ➕ {file.name}")
            with open(file, "r", encoding="utf-8") as fin:
                for line in fin:
                    fout.write(line.strip() + "\n")
    print("✅ 合併完成")

# === 步驟 3：嵌入 ➜ FAISS index ===
def prepare_knowledge_embeddings(jsonl_path: Path):
    print(f"\n🧠 開始嵌入向量")
    global stop_spinner
    stop_spinner = False
    t = threading.Thread(target=spinner)
    t.start()

    try:
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
                print(f"\r  ✅ [{idx}/{total}] {source} p.{page}", end="")
            except Exception as e:
                print(f"\n  ❌ 第 {idx} 條失敗：{e}")

        dim = len(embeddings[0])
        index = faiss.IndexFlatL2(dim)
        index.add(np.array(embeddings).astype("float32"))
        faiss.write_index(index, str(INDEX_PATH))


        with open(METADATA_PATH, "w", encoding="utf-8") as f:
            json.dump(metadatas, f, ensure_ascii=False, indent=2)

    finally:
        stop_spinner = True
        t.join()

    print(f"\n✅ 嵌入完成！FAISS 儲存於：{INDEX_PATH}")
    print(f"🗂️ metadata 儲存於：{METADATA_PATH}")

# === 主流程 ===
if __name__ == "__main__":
    print("========== 📚 自動建構知識庫 ==========")

    # Step 1: 每個 PDF ➜ .jsonl
    pdf_files = list(database_dir.glob("*.pdf"))
    if not pdf_files:
        print("⚠️ 找不到 PDF")
        sys.exit(1)

    for pdf_file in pdf_files:
        pdf_to_jsonl(pdf_file)

    # Step 2: 合併所有 .jsonl
    merge_jsonl(database_dir, JSONL_PATH)

    # Step 3: 建立向量索引
    prepare_knowledge_embeddings(JSONL_PATH)

    print("\n🎉 所有步驟完成！")
