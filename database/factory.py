#factory.py
import fitz  # PyMuPDF
import json
from pathlib import Path

target = "食在好孕"# change the target here

pdf_path = Path(f"{target}.pdf")
doc = fitz.open(str(pdf_path))  # 要轉成 str 才能給 fitz


data = []
for page_number, page in enumerate(doc, start=1):
    text = page.get_text("text")
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    paragraph = " ".join(lines)
    
    if paragraph:
        data.append({
            "source": f"{target}",
            "page": page_number,
            "text": paragraph
        })

output_path = Path(f"{target}.jsonl")
with open(output_path, "w", encoding="utf-8") as f:
    for entry in data:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
