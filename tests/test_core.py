import time
from datetime import date

import pytest

from nursebot import profile as pf
from nursebot.bot import Bot
from nursebot.db import DB
from nursebot.kb import KnowledgeBase
from nursebot.line import LineClient
from nursebot.migrate import migrate_memory
from nursebot.settings import Settings

TODAY = date(2026, 6, 1)


class FakeLlm:
    """Deterministic stand-in for llama-server: char-bucket embeddings, canned chat."""
    def embed(self, texts):
        out = []
        for t in texts:
            v = [0.0] * 32
            for ch in t:
                v[ord(ch) % 32] += 1.0
            n = sum(x * x for x in v) ** 0.5 or 1.0
            out.append([x / n for x in v])
        return out

    def embed_one(self, t):
        return self.embed([t])[0]

    def chat(self, messages, **kw):
        if "資料提取" in messages[0]["content"]:
            return ""
        return "建議多休息。"

    def clear_cache(self):
        pass


@pytest.fixture
def env(tmp_path):
    db = DB(tmp_path / "t.db")
    s = Settings(db)
    s.update({"max_distance": "100"})
    kbdir = tmp_path / "kb"
    kbdir.mkdir()
    (kbdir / "衛教.txt").write_text("孕期腰痠可以熱敷並適度休息。\n\n孕期便祕建議多喝水與攝取纖維。", encoding="utf-8")
    kb = KnowledgeBase(kbdir, s, FakeLlm())
    kb._rebuild()
    bot = Bot(db, s, FakeLlm(), kb, LineClient(s))
    return db, s, kb, bot


def test_state_machine_is_total():
    assert pf.next_state("collecting", False) is pf.State.COLLECTING
    assert pf.next_state("collecting", True) is pf.State.ACTIVE
    assert pf.next_state("active", False) is pf.State.COLLECTING  # a cleared field re-opens onboarding
    assert pf.next_state("garbage", True) is pf.State.ACTIVE


def test_parse_form_and_weeks():
    form = "1. 姓名：陳雅婷\n2. 性別：女\n3. 預產期：2026/10/15\n4. 懷孕次數：2\n5. 生產次數：1"
    f = pf.fields_from_form(form, TODAY)
    assert (f["name"], f["is_dad"], f["g"], f["p"], f["weeks"]) == ("陳雅婷", 0, 2, 1, 20)
    assert pf.fields_from_structured("G(2)P(1)W()IsDad(False)Name(x)") == {"g": 2, "p": 1, "is_dad": 0, "name": "x"}
    # snapshot weeks advance with elapsed time instead of freezing
    assert pf.current_weeks({"weeks": 10, "weeks_set_on": "2026-05-04"}, TODAY) == 14


def test_correction_commands():
    assert pf.parse_correction("你好") is None
    assert pf.parse_correction("更正 W(12)", TODAY).fields["weeks"] == 12
    assert pf.parse_correction("更正 亂寫").fields == {}  # malformed -> help text path
    full = pf.parse_correction("更正 G(2)P(1)W()IsDad(True)Name(阿明)", TODAY)
    assert full.fields["name"] == "阿明" and full.clear == {"weeks"}  # blank W clears it, like the old overwrite


def test_migrate_legacy_memory(tmp_path):
    mem = tmp_path / "memory_data"
    mem.mkdir()
    (mem / "U1.txt").write_text("G(3)P(0)W(33)IsDad(True)Name(華璽)\nUser: 你好\nBot: 第一行\n第二行\nUser: 謝謝\n", encoding="utf-8")
    (mem / "U2.txt").write_text("G()P()W()IsDad()Name()failed(False)\nUser: hi\n", encoding="utf-8")
    db = DB(tmp_path / "t.db")
    assert migrate_memory(db, mem) == 2
    assert migrate_memory(db, mem) == 0  # idempotent
    u1, u2 = db.get_user("U1"), db.get_user("U2")
    assert (u1["state"], u1["name"], u1["weeks"], u1["is_dad"]) == ("active", "華璽", 33, 1)
    assert u2["state"] == "collecting"
    assert [m["text"] for m in db.recent_messages("U1")] == ["你好", "第一行\n第二行", "謝謝"]


def test_onboarding_then_rag_answer(env):
    db, s, kb, bot = env
    r = bot.handle_text("U9", "哈囉")
    assert "請提供以下資訊" in r and db.get_user("U9")["state"] == "collecting"
    r = bot.handle_text("U9", "1. 姓名：小美\n2. 性別：女\n3. 預產期：2027/01/01\n4. 懷孕次數：1\n5. 生產次數：0")
    assert "已儲存您的資料" in r and db.get_user("U9")["state"] == "active"
    r = bot.handle_text("U9", "孕期腰痠怎麼辦")
    assert r.startswith("建議多休息。") and "資料來源: 衛教 第無頁碼頁" in r


def test_unanswered_is_flagged_for_staff(env):
    db, s, kb, bot = env
    db.ensure_user("U5")
    db.update_user("U5", g=1, p=0, weeks=10, weeks_set_on=TODAY.isoformat(), is_dad=0, name="A", state="active")
    s.update({"max_distance": "0.0000001"})
    assert "我沒有相關資料" in bot.handle_text("U5", "完全無關的問題")
    assert [x["flag"] for x in db.unanswered()] == ["no_data"]


def test_emergency_skips_everything_and_correction_reopens_onboarding(env):
    db, s, kb, bot = env
    assert "立刻聯絡醫院" in bot.handle_text("U6", "我破水了")
    db.update_user("U6", g=1, p=0, weeks=10, weeks_set_on=TODAY.isoformat(), is_dad=0, name="A", state="active")
    bot.handle_text("U6", "更正 G()P()W(10)IsDad(False)Name(A)")
    assert db.get_user("U6")["state"] == "collecting"


def test_kb_status_flags_pending_and_search(env):
    db, s, kb, bot = env
    st = kb.status()
    assert st["ready"] and st["vectors"] == 1 and st["pending"] == []
    kb.add_file("新文件.txt", "產後憂鬱的徵兆。".encode())
    assert kb.status()["pending"] == ["新文件.txt"]
    with pytest.raises(ValueError):
        kb.add_file("x.exe", b"")
    assert len(kb.search(FakeLlm().embed_one("便祕"), 5, 100)) == 1


def test_admin_rejects_bad_host_and_missing_token(tmp_path):
    from nursebot.runtime import Runtime
    from nursebot.web.admin import RingHandler, create_admin_app
    rt = Runtime(DB(tmp_path / "t.db"))
    app = create_admin_app(rt, RingHandler(), lambda: None)
    c = app.test_client()
    port = rt.settings.int("ui_port")
    ok = {"Host": f"127.0.0.1:{port}"}
    assert c.get("/api/users", headers={"Host": "evil.example"}).status_code == 403
    assert c.get("/api/users", headers=ok).status_code == 200
    assert c.post("/api/chat/reset", headers=ok).status_code == 403  # CSRF: no token
