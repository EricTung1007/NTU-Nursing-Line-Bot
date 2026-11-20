from pathlib import Path

import pytest

from nursebot import paths
from nursebot.db import DB
from nursebot.doctor import explain_llama_log
from nursebot.runtime import Runtime
from nursebot.settings import Settings


@pytest.fixture
def rt(tmp_path, monkeypatch):
    for name, sub in (("DATA_DIR", "data"), ("KB_DIR", "database"), ("MODELS_DIR", "models"), ("BIN_DIR", "bin")):
        monkeypatch.setattr(paths, name, tmp_path / sub)
    monkeypatch.setattr(paths, "APP_DIR", tmp_path)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    paths.ensure_dirs()
    return Runtime(DB(paths.DATA_DIR / "t.db"))


def test_settings_validation_reset_and_last_good(tmp_path):
    s = Settings(DB(tmp_path / "t.db"))
    errs = s.validate({"top_k": "abc", "temperature": "9", "chat_port": "5001", "system_prompt": ""})
    assert set(errs) >= {"top_k", "temperature", "chat_port", "system_prompt"}  # chat_port clashes with webhook_port
    s.update({"line_channel_access_token": "tok", "top_k": "8"})
    s.snapshot_good()
    s.update({"top_k": "3", "max_tokens": "100"})
    assert sorted(s.differs_from_good()) == ["max_tokens", "top_k"]
    s.restore_good()
    assert (s.int("top_k"), s.int("max_tokens")) == (8, 500)
    s.reset()  # "reset all" must never wipe LINE credentials
    assert s.get("line_channel_access_token") == "tok" and s.int("top_k") == 5


def test_doctor_explains_and_fixes_common_operator_mistakes(rt, tmp_path):
    assert explain_llama_log(["ggml_backend_alloc: cudaMalloc failed: out of memory"])[1] == "degrade_llm"
    assert explain_llama_log(["error: couldn't bind HTTP server socket"])[1] == "free_ports"
    assert explain_llama_log(["all fine"]) is None

    ids = {c.id: c for c in rt.doctor.run()}
    assert ids["llama_server"].level == "bad" and ids["llama_server"].fix == "locate_files"
    assert ids["line_cfg"].steps and ids["line_cfg"].level == "bad"  # plain-language steps, not just a red light

    # operator typed a model path that does not exist, and a non-number port
    rt.settings.update({"chat_model_path": "models/gone.gguf", "top_k": "x"})
    ids = {c.id: c for c in rt.doctor.run()}
    assert ids["model_paths"].fix == "clear_bad_paths" and ids["settings"].fix == "reset_invalid"
    rt.doctor.fix("clear_bad_paths"); rt.doctor.fix("reset_invalid")
    assert rt.settings.get("chat_model_path") == "" and rt.settings.int("top_k") == 5

    # files dropped in Downloads are found and wired up without copying multi-GB models
    dl = tmp_path / "home" / "Downloads"
    dl.mkdir(parents=True)
    (dl / "qwen-chat-q4.gguf").write_bytes(b"x" * 100)
    (dl / "bge-small-zh.gguf").write_bytes(b"x" * 10)
    (dl / "llama-server").write_bytes(b"x")
    ok, zh, _ = rt.doctor.fix("locate_files")
    assert ok
    assert rt.settings.get("chat_model_path").endswith("qwen-chat-q4.gguf")
    assert rt.settings.get("embed_model_path").endswith("bge-small-zh.gguf")
    assert {c.id: c for c in rt.doctor.run()}["llama_server"].level == "ok"


def test_ports_and_repair_rate_limit(rt):
    from nursebot.doctor import port_busy
    import socket
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
    except OSError:
        pytest.skip("sandbox forbids binding")
    s.listen(1)
    busy = s.getsockname()[1]
    rt.settings.update({"webhook_port": str(busy)})
    try:
        assert port_busy(busy)
        assert {c.id: c for c in rt.doctor.run()}["ports"].fix == "free_ports"
        rt.doctor.fix("free_ports")
        assert rt.settings.int("webhook_port") != busy
    finally:
        s.close()
    # a permanently broken component is reported, not restarted forever
    assert [rt._may_repair("x", 3, 600) for _ in range(5)] == [True, True, True, False, False]
