#glue.py
from pathlib import Path

folder = Path(".")  # 目前資料夾
output_file = folder / "combined.jsonl"

# 如果之前已經有合併檔，先刪除避免疊加
if output_file.exists():
    output_file.unlink()

with open(output_file, "w", encoding="utf-8") as fout:
    for file in folder.glob("*.jsonl"):
        if file.name == output_file.name:
            continue  # 跳過自己
        with open(file, "r", encoding="utf-8") as fin:
            for line in fin:
                fout.write(line.strip() + "\n")

print(f"✅ 合併完成：{output_file}")
