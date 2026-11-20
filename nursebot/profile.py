"""User profile: explicit onboarding state machine plus all text parsing.

The old bot never stored a user's state; it re-derived it on every message by regex-matching
the first line of a text file. Here the states and transitions are named and tested.

    COLLECTING --(profile complete)--> ACTIVE
    ACTIVE     --(a field cleared)---> COLLECTING
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set


class State(str, Enum):
    COLLECTING = "collecting"
    ACTIVE = "active"


# (current state, profile complete?) -> next state. Total over all inputs.
TRANSITIONS = {
    (State.COLLECTING, False): State.COLLECTING,
    (State.COLLECTING, True): State.ACTIVE,
    (State.ACTIVE, True): State.ACTIVE,
    (State.ACTIVE, False): State.COLLECTING,
}


def next_state(current: str, complete: bool) -> State:
    try:
        cur = State(current)
    except ValueError:
        cur = State.COLLECTING
    return TRANSITIONS[(cur, complete)]


def missing_fields(u: Dict[str, Any]) -> List[str]:
    out = []
    if u.get("g") is None or u.get("p") is None:
        out.append("G/P")
    if u.get("weeks") is None:
        out.append("W")
    if u.get("is_dad") is None:
        out.append("IsDad")
    if not (u.get("name") or "").strip():
        out.append("Name")
    return out


def current_weeks(u: Dict[str, Any], today: Optional[date] = None) -> Optional[int]:
    """Gestational weeks now. The stored value is a snapshot, so advance it by elapsed time
    (the old bot froze weeks forever)."""
    w = u.get("weeks")
    if w is None:
        return None
    today = today or date.today()
    try:
        set_on = date.fromisoformat(u["weeks_set_on"]) if u.get("weeks_set_on") else today
    except ValueError:
        set_on = today
    return min(42, w + max(0, (today - set_on).days) // 7)


def trimester(weeks: Optional[int]) -> str:
    if weeks is None:
        return "未提供"
    return "懷孕初期" if weeks <= 12 else "懷孕中期" if weeks <= 28 else "懷孕後期"


# ---------------------------------------------------------------------------
# Parsing. Everything returns a partial dict of DB fields so callers just merge it.
# ---------------------------------------------------------------------------
_STRUCT = re.compile(
    r"G\((?P<g>\d*)\)\s*P\((?P<p>\d*)\)\s*W\((?P<w>\d*)\)\s*IsDad\((?P<d>True|False|1|0)?\)\s*Name\((?P<n>[^)]*)\)"
)
_BAD_NAMES = {"unknown", "none", ""}


def fields_from_structured(text: str, today: Optional[date] = None) -> Dict[str, Any]:
    """Parse the LLM/legacy line `G(2)P(1)W()IsDad(False)Name(x)`; blanks are omitted."""
    m = _STRUCT.search(text or "")
    if not m:
        return {}
    return _fields(m.group("g"), m.group("p"), m.group("w"), m.group("d"), m.group("n"), today)


def _fields(g, p, w, d, name, today=None) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if g != "" and g is not None and p != "" and p is not None:
        out["g"], out["p"] = int(g), int(p)
    if w not in ("", None):
        out["weeks"] = int(w)
        out["weeks_set_on"] = (today or date.today()).isoformat()
    if d not in ("", None):
        out["is_dad"] = 1 if d in ("True", "1") else 0
    name = (name or "").strip()
    if name.lower() not in _BAD_NAMES:
        out["name"] = name
    return out


def _line_field(text: str, label: str) -> str:
    m = re.search(rf"(?im)^\s*(?:\d+\s*[.)、．]?\s*)?{label}\s*[:：]\s*(.+?)\s*$", text)
    return m.group(1).strip() if m else ""


def _first_number(s: str) -> str:
    m = re.search(r"\d+", s or "")
    return m.group(0) if m else ""


def _gender_to_isdad(g: str) -> str:
    v = (g or "").strip().lower()
    if any(t in v for t in ("父", "爸爸", "先生", "男", "male", "father", "dad")):
        return "True"
    if any(t in v for t in ("母", "媽媽", "媽咪", "孕婦", "產婦", "女", "female", "mother", "mom")):
        return "False"
    return ""


def weeks_from_due_date(text: str, today: Optional[date] = None) -> str:
    value = _line_field(text, "預產期")
    m = re.search(r"(\d{2,4})\s*[年/\-.]\s*(\d{1,2})\s*[月/\-.]\s*(\d{1,2})", value)
    if not m:
        return ""
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if 100 <= y < 200:
        y += 1911
    try:
        due = datetime(y, mo, d).date()
    except ValueError:
        return ""
    today = today or date.today()
    days = 280 - (due - today).days
    return "" if days < 0 or days > 315 else str(days // 7)


def fields_from_form(text: str, today: Optional[date] = None) -> Dict[str, Any]:
    """Parse the numbered form the bot asks users to fill in (姓名/性別/預產期/懷孕次數/生產次數)."""
    name = _line_field(text, "姓名")
    gender = _line_field(text, "性別")
    g = _first_number(_line_field(text, "懷孕次數"))
    p = _first_number(_line_field(text, "生產次數"))
    w = _first_number(_line_field(text, "懷孕週數") or _line_field(text, "週數")) or weeks_from_due_date(text, today)
    return _fields(g, p, w, _gender_to_isdad(gender), name, today)


# ---------------------------------------------------------------------------
# 更正 (correction) commands
# ---------------------------------------------------------------------------
@dataclass
class Correction:
    fields: Dict[str, Any] = field(default_factory=dict)
    clear: Set[str] = field(default_factory=set)
    label: str = ""


CORRECTION_HELP = (
    "❌ 格式錯誤。\n請使用以下格式：\nG(數字)P(數字)\nW(數字)\nIsDad(True|False)\nName(名字)\n"
    "或整行：G()P()W()IsDad()Name()"
)


def parse_correction(text: str, today: Optional[date] = None) -> Optional[Correction]:
    """Return None if `text` is not a 更正 command; a Correction with empty fields if malformed."""
    if not text.startswith("更正"):
        return None
    c = text.replace("更正", "", 1).strip()
    if re.fullmatch(r"G\(\d*\)P\(\d*\)W\(\d*\)IsDad\((True|False)?\)Name\((.*?)\)", c):
        m = _STRUCT.fullmatch(c)
        f = _fields(m.group("g"), m.group("p"), m.group("w"), m.group("d"), m.group("n"), today)
        # Blank slots in a full-line correction clear that field (matches the old whole-line overwrite).
        clear = {"g", "p"} if "g" not in f else set()
        clear |= {k for k in ("weeks", "is_dad", "name") if k not in f}
        return Correction(f, clear, f"整行資料為：\n{c}")
    if m := re.fullmatch(r"G\((\d+)\)P\((\d+)\)", c):
        return Correction({"g": int(m.group(1)), "p": int(m.group(2))}, label=f"G/P 為：{c}")
    if m := re.fullmatch(r"W\((\d+)\)", c):
        w = int(m.group(1))
        return Correction({"weeks": w, "weeks_set_on": (today or date.today()).isoformat()}, label=f"週數 W 為：{w}")
    if m := re.fullmatch(r"IsDad\((True|False)\)", c):
        return Correction({"is_dad": 1 if m.group(1) == "True" else 0}, label=f"IsDad 為：{m.group(1) == 'True'}")
    if m := re.fullmatch(r"Name\((.*?)\)", c):
        return Correction({"name": m.group(1).strip()}, label=f"名字 Name 為：{m.group(1)}")
    return Correction()
