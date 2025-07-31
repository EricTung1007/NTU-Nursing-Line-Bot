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

sys.path.append(str(Path(__file__).resolve().parent.parent))
from config import EMBEDDING_ENDPOINT, EMBEDDING_MODEL



# === Spinner ===
stop_spinner = False
def spinner():
    while not stop_spinner:
        for char in "|/-\\":
            sys.stdout.write(f"\r⏳ 嵌入中... {char}")
            sys.stdout.flush()
            time.sleep(0.1)

# === 嵌入向量 ===
def get_embedding(text: str):
    response = requests.post(
        LM_STUDIO_EMBEDDING_URL,
        headers={"Content-Type": "application/json"},
        json={"input": text, "model": EMBEDDING_MODEL}
    )
    response.raise_for_status()
    return response.json()["data"][0]["embedding"]

# === 步驟 1：PDF → JSONL ===
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
        print(f"  ✅ 轉換第 {page_number} 頁")

    output_path = pdf_path.with_suffix(".jsonl")
    with open(output_path, "w", encoding="utf-8") as f:
        for entry in data:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    print(f"✅ 完成轉換：{output_path.name}")

# === 步驟 2：合併 JSONL ===
def merge_jsonl(folder: Path, output_file: Path):
    print(f"\n📎 合併所有 .jsonl 成 {output_file.name}")
    if output_file.exists():
        output_file.unlink()

    with open(output_file, "w", encoding="utf-8") as fout:
        for file in folder.glob("*.jsonl"):
            if file.name == output_file.name:
                continue
            print(f"  ➕ 合併：{file.name}")
            with open(file, "r", encoding="utf-8") as fin:
                for line in fin:
                    fout.write(line.strip() + "\n")
    print(f"✅ 合併完成：共處理 {len(list(folder.glob('*.jsonl')))-1} 個檔案")

# === 步驟 3：建構嵌入索引 ===
def prepare_knowledge_embeddings(jsonl_path: str):
    print(f"\n🧠 開始嵌入與索引：{jsonl_path}")
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
                print(f"\r  ✅ [{idx}/{total}] 嵌入：{source} p.{page}", end="")
            except Exception as e:
                print(f"\n  ❌ 第 {idx} 條資料錯誤：{e}")

        dim = len(embeddings[0])
        index = faiss.IndexFlatL2(dim)
        index.add(np.array(embeddings).astype("float32"))
        faiss.write_index(index, INDEX_PATH)

        with open(METADATA_PATH, "w", encoding="utf-8") as f:
            json.dump(metadatas, f, ensure_ascii=False, indent=2)

    finally:
        stop_spinner = True
        t.join()

    print(f"\n✅ 嵌入完成！索引儲存至：{INDEX_PATH}")
    print(f"🗃️  metadata 儲存至：{METADATA_PATH}")

# === 主流程 ===
if __name__ == "__main__":
    folder = Path(".")

    print("========== 🔁 開始全流程 ==========")
    
    # Step 1
    pdf_files = list(folder.glob("*.pdf"))
    if not pdf_files:
        print("⚠️ 找不到 PDF 檔案")
        sys.exit(1)

    for pdf_file in pdf_files:
        pdf_to_jsonl(pdf_file)

    # Step 2
    merge_jsonl(folder, Path(JSONL_PATH))

    # Step 3
    prepare_knowledge_embeddings(JSONL_PATH)

    print("\n🎉 全部流程完成！")
