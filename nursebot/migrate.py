"""One-time import of the legacy memory_data/*.txt files into SQLite."""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import List, Tuple

from . import profile as pf
from .db import DB

log = logging.getLogger("migrate")
_FLAG = "migrated_memory_v1"


def _parse_log(lines: List[str]) -> List[Tuple[str, str]]:
    """Legacy log lines: 'User: ...' / 'Bot: ...', where a Bot reply may span several lines."""
    out: List[Tuple[str, str]] = []
    for line in lines:
        m = re.match(r"^(User|Bot):\s?(.*)$", line)
        if m:
            out.append(("user" if m.group(1) == "User" else "bot", m.group(2)))
        elif out:
            role, text = out[-1]
            out[-1] = (role, text + "\n" + line)
    return [(r, t.strip()) for r, t in out if t.strip()]


def migrate_memory(db: DB, folder: Path) -> int:
    if db.load_settings().get(_FLAG) or not folder.is_dir():
        return 0
    n = 0
    for f in sorted(folder.glob("*.txt")):
        user_id = f.stem
        if user_id == "CLI":
            continue
        lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
        if not lines:
            continue
        fields = pf.fields_from_structured(lines[0])
        db.ensure_user(user_id)
        if fields:
            db.update_user(user_id, **fields)
        u = db.get_user(user_id)
        db.update_user(user_id, state=pf.next_state(u["state"], not pf.missing_fields(u)).value)
        base = time.time() - 1000
        for i, (role, text) in enumerate(_parse_log(lines[1:])):
            c = db.conn()
            with c:
                c.execute("INSERT INTO messages(user_id, role, text, ts) VALUES(?,?,?,?)",
                          (user_id, role, text, base + i))
        n += 1
    db.save_settings({_FLAG: "1"})
    log.info("migrated %d legacy users", n)
    return n
