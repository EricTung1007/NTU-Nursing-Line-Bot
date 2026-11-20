import hashlib
import io
import zipfile

import pytest

from nursebot import components, paths
from nursebot.components import Installer


class Resp:
    def __init__(self, body, start=0, ranged=False):
        self.content, self.status_code = body[start:], 206 if ranged else 200
        self.headers = {"Content-Length": str(len(self.content))}

    def __enter__(self): return self
    def __exit__(self, *a): return False
    def raise_for_status(self): pass
    def iter_content(self, n): yield self.content


class FakeHttp:
    def __init__(self, body): self.body, self.calls = body, []
    def get(self, url, headers=None, **kw):
        self.calls.append(headers or {})
        start = int((headers or {}).get("Range", "bytes=0-")[6:-1] or 0)
        return Resp(self.body, start, ranged=bool(headers))


@pytest.fixture
def inst(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "BIN_DIR", tmp_path / "bin")
    monkeypatch.setattr(paths, "MODELS_DIR", tmp_path / "models")
    (tmp_path / "bin").mkdir(); (tmp_path / "models").mkdir()
    return Installer({k: (lambda: False) for k in ("llama", "cloudflared", "embed", "chat")})


def test_download_resumes_verifies_and_archives_flatten(inst, tmp_path):
    body = b"0123456789" * 1000
    good = hashlib.sha256(body).hexdigest()
    dest = tmp_path / "models" / "m.gguf"
    (tmp_path / "models" / "m.gguf.part").write_bytes(body[:3000])          # interrupted earlier
    inst.http = FakeHttp(body)
    inst._download("http://x/m.gguf", dest, good)
    assert dest.read_bytes() == body and inst.http.calls == [{"Range": "bytes=3000-"}]  # resumed, not restarted
    assert not (tmp_path / "models" / "m.gguf.part").exists()

    inst.http = FakeHttp(body)
    with pytest.raises(RuntimeError, match="驗證失敗"):                      # corrupt download is rejected and discarded
        inst._download("http://x/n.gguf", tmp_path / "models" / "n.gguf", "0" * 64)
    assert not (tmp_path / "models" / "n.gguf").exists()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:                                      # nested dir in the archive
        z.writestr("llama-b1/llama-server.exe", b"exe"); z.writestr("llama-b1/ggml.dll", b"dll")
    inst.http = FakeHttp(buf.getvalue())
    inst._fetch_archive("http://x/a.zip", "a.zip", paths.BIN_DIR, {"llama-server.exe"})
    assert (paths.BIN_DIR / "llama-server.exe").read_bytes() == b"exe" and (paths.BIN_DIR / "ggml.dll").exists()
    assert components.llama_asset.__name__ and components._platform_key()
