# PyInstaller spec: a windowed app (no console) with the GUI assets and education booklets inside.
# Build from the repo root:  pyinstaller --clean --noconfirm packaging/NTULineBot.spec
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).parent
datas = [(str(root / "nursebot" / "web" / "static"), "nursebot/web/static")]
# Ship the booklets and the prebuilt index (not the derived .jsonl copies); seeded to the user's data dir on first run.
for f in sorted((root / "database").iterdir()):
    if f.suffix.lower() in (".pdf", ".index") or f.name == "metadata.json":
        datas.append((str(f), "database"))
binaries, hidden = [], ["fitz"]
for pkg in ("faiss", "webview"):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hidden += h
    except Exception as e:  # webview is optional; the app falls back to the browser
        print("collect_all skipped", pkg, e)

a = Analysis([str(root / "app.py")], pathex=[str(root)], datas=datas, binaries=binaries, hiddenimports=hidden,
             excludes=["tkinter", "pytest"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="NTULineBot", console=False)
coll = COLLECT(exe, a.binaries, a.datas, name="NTULineBot")
if sys.platform == "darwin":
    app = BUNDLE(coll, name="NTULineBot.app", bundle_identifier="tw.edu.ntu.nursing.linebot",
                 info_plist={"NSHighResolutionCapable": True})
