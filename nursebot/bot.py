"""Conversation pipeline. Transport-agnostic: `Bot.handle_text` is used by LINE and the GUI test chat.

    correction command -> emergency check -> onboarding (State.COLLECTING) -> RAG answer (State.ACTIVE)
"""
from __future__ import annotations

import logging
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from . import profile as pf
from .db import DB
from .kb import KnowledgeBase
from .line import LineClient
from .llm import LlmClient
from .prompts import (FIELD_DESCRIPTIONS, build_messages, fields_system_prompt, no_data_reply,
                      summarize_sources)
from .settings import Settings

log = logging.getLogger("bot")
ERROR_REPLY = "❌ 抱歉，目前無法取得回應，請稍後再試。"


class Bot:
    def __init__(self, db: DB, settings: Settings, llm: LlmClient, kb: KnowledgeBase, line: LineClient):
        self.db, self.s, self.llm, self.kb, self.line = db, settings, llm, kb, line

    # ---- steps -------------------------------------------------------------
    def _is_emergency(self, text: str) -> bool:
        return any(k in text for k in self.s.list("emergency_keywords"))

    def _extract(self, text: str) -> Dict[str, Any]:
        fields = pf.fields_from_form(text)
        if fields or len(text) > 300:  # a long message is not a profile answer; skip the LLM call
            return fields
        for max_tokens in (80, 200):
            try:
                out = self.llm.chat([{"role": "system", "content": fields_system_prompt},
                                     {"role": "user", "content": text}], max_tokens=max_tokens, temperature=0.0, timeout=30)
            except Exception as e:  # LLM down must not break onboarding
                log.warning("profile extraction failed: %s", e)
                continue
            fields = pf.fields_from_structured(out)
            if fields:
                return fields
        return {}

    def _apply(self, user_id: str, fields: Dict[str, Any], clear: Optional[set] = None) -> Dict[str, Any]:
        """Merge fields, then run the state machine. The only place a user's state changes."""
        changes = dict(fields)
        for k in clear or ():
            changes[k] = None
        if changes:
            self.db.update_user(user_id, **changes)
        u = self.db.get_user(user_id)
        new_state = pf.next_state(u["state"], not pf.missing_fields(u))
        if new_state.value != u["state"]:
            self.db.update_user(user_id, state=new_state.value)
            u["state"] = new_state.value
        return u

    def _summary(self, u: Dict[str, Any]) -> str:
        who = "準爸爸" if u["is_dad"] else "準媽媽"
        return (f"✅ 已儲存您的資料：您是{who}，產婦曾懷胎{u['g']}次，曾產{u['p']}胎，"
                f"目前懷胎{pf.current_weeks(u)}週，登記名字是{u['name']}。\n您可以開始提問囉～")

    def _ask_missing(self, u: Dict[str, Any]) -> str:
        return "\n您好，請提供以下資訊：\n" + "".join(f"🔸{FIELD_DESCRIPTIONS[f]}\n" for f in pf.missing_fields(u))

    def _answer(self, user_id: str, user: Dict[str, Any], text: str) -> Tuple[str, Optional[str]]:
        """Returns (reply, flag). flag marks questions staff may want to add knowledge for."""
        try:
            vec = self.llm.embed_one(text)
            ctx = self.kb.search(vec, self.s.int("top_k"), self.s.float("max_distance"))
            if not ctx:
                return no_data_reply, "no_data"
            weeks = pf.current_weeks(user)
            history = self.db.recent_messages(user_id, self.s.int("history_turns") * 2)
            msgs = build_messages(ctx, text, user, weeks, pf.trimester(weeks), history)
            reply = self.llm.chat(msgs)
            if not reply:
                return "❌ 模型未產生回應，請稍後再試。", "error"
            return reply + f"\n資料來源: {summarize_sources(ctx)}", None
        except Exception:
            log.exception("answer failed")
            return ERROR_REPLY, "error"

    # ---- public ------------------------------------------------------------
    def handle_text(self, user_id: str, text: str) -> str:
        self.db.ensure_user(user_id)

        corr = pf.parse_correction(text)
        if corr is not None:
            if not corr.fields and not corr.clear:
                return pf.CORRECTION_HELP
            self._apply(user_id, corr.fields, corr.clear)
            return f"✅ 已更正{corr.label}"

        msg_id = self.db.add_message(user_id, "user", text)
        reply, flag = self._route(user_id, text)
        if flag:
            self.db.set_flag(msg_id, flag)
        self.db.add_message(user_id, "bot", reply)
        return reply

    def _route(self, user_id: str, text: str) -> Tuple[str, Optional[str]]:
        if self._is_emergency(text):
            return self.s.get("emergency_reply"), None
        u = self.db.get_user(user_id)
        if u["state"] == pf.State.COLLECTING.value:
            u = self._apply(user_id, self._extract(text))
            if u["state"] == pf.State.COLLECTING.value:
                return self._ask_missing(u), None
            return self._summary(u), None
        return self._answer(user_id, u, text)

    def handle_event(self, event: Dict[str, Any]) -> None:
        if event.get("type") != "message" or event.get("message", {}).get("type") != "text":
            return
        user_id = event["source"]["userId"]
        reply = self.handle_text(user_id, event["message"]["text"])
        # Reply tokens expire; if the (slow) model made us miss it, fall back to push.
        if not self.line.reply(event["replyToken"], reply):
            self.line.push(user_id, reply)


class Dispatcher:
    """Run events off the webhook thread (LINE needs a fast 200) and keep each user's messages in order."""

    def __init__(self, bot: Bot, workers: int = 4):
        self.bot = bot
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="bot")
        self._locks: Dict[str, threading.Lock] = defaultdict(threading.Lock)
        self._guard = threading.Lock()

    def submit(self, event: Dict[str, Any]) -> None:
        uid = event.get("source", {}).get("userId", "")
        with self._guard:
            lock = self._locks[uid]
        self.pool.submit(self._run, event, lock)

    def _run(self, event: Dict[str, Any], lock: threading.Lock) -> None:
        with lock:
            try:
                self.bot.handle_event(event)
            except Exception:
                log.exception("event handling failed")

    def shutdown(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)
