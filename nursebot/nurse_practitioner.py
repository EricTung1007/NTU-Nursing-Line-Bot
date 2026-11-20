"""The in-app nurse practitioner (NP): self-diagnosis and self-repair, i.e. the app does its own rounds.

Every check returns a plain-language finding (Chinese + English), numbered steps a nurse can follow,
and, when the app can fix it itself, a fix id behind an "Auto-fix" button. `fix_all` loops
check -> fix until nothing more can be fixed automatically.

Checks that touch the network (LINE credentials, internet, embedding dimension) only run in `deep` mode
so the always-on overview stays instant.
"""
from __future__ import annotations

import errno
import logging
import os
import shutil
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Tuple

from . import paths
from .llm import LlamaServers, find_llama_server, list_models, resolve_model
from .settings import SCHEMA

if TYPE_CHECKING:
    from .runtime import Runtime

log = logging.getLogger("np")
T = Tuple[str, str]  # (中文, English)
LLAMA_RELEASES = "https://github.com/ggml-org/llama.cpp/releases"


@dataclass
class Check:
    id: str
    level: str                      # ok | warn | bad
    title: T
    detail: T = ("", "")
    steps: List[T] = field(default_factory=list)
    fix: Optional[str] = None
    fix_label: T = ("自動修復", "Auto-fix")

    def to_dict(self) -> dict:
        return {"id": self.id, "level": self.level, "title": list(self.title), "detail": list(self.detail),
                "steps": [list(s) for s in self.steps], "fix": self.fix, "fix_label": list(self.fix_label)}


def port_busy(port: int) -> bool:
    """True only if something else really holds the port (a blocked bind is 'unknown', not 'busy')."""
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
        return False
    except OSError as e:
        return e.errno in (errno.EADDRINUSE, 10048)
    finally:
        s.close()


def free_port(start: int, avoid: set) -> int:
    p = start
    while p < 65535:
        if p not in avoid and not port_busy(p):
            return p
        p += 1
    return start


def explain_llama_log(lines: List[str]) -> Optional[Tuple[T, Optional[str]]]:
    """Map the tail of a llama-server log to (plain explanation, fix id)."""
    t = "\n".join(lines).lower()
    rules = [
        (("out of memory", "failed to allocate", "cudamalloc failed", "unable to allocate", "bad_alloc", "insufficient memory"),
         ("電腦記憶體不足，模型載入失敗", "Not enough memory to load the model"), "degrade_llm"),
        (("address already in use", "couldn't bind", "failed to bind", "bind failed"),
         ("連接埠被其他程式占用", "The network port is used by another program"), "free_ports"),
        (("unknown model architecture", "unsupported model", "unknown architecture"),
         ("llama-server 版本太舊，不支援這個模型", "llama-server is too old for this model"), None),
        (("invalid magic", "not a gguf", "gguf_init_from_file", "failed to read magic", "file is too small", "truncated"),
         ("模型檔案損毀或下載不完整", "The model file is corrupt or incompletely downloaded"), None),
        (("no such file", "cannot open", "failed to open"),
         ("找不到模型檔案（可能被移動或刪除）", "Model file not found (moved or deleted?)"), "clear_bad_paths"),
        (("does not support embeddings", "embedding is not supported", "pooling type"),
         ("這個模型不是檢索（向量）模型", "This is not an embedding model"), None),
    ]
    for keys, msg, fix in rules:
        if any(k in t for k in keys):
            return msg, fix
    return None


class NursePractitioner:
    def __init__(self, rt: "Runtime"):
        self.rt = rt
        self.s = rt.settings
        self._job = {"running": False, "log": [], "done": True, "progress": ""}
        self._job_lock = threading.Lock()

    # ====================================================================== checks
    def run(self, deep: bool = False) -> List[Check]:
        out: List[Check] = []
        for fn in (self._dirs, self._settings, self._ports, self._line_cfg, self._binaries, self._models,
                   self._processes, self._llm_ready, self._kb, self._tunnel, self._errors, self._no_webhook):
            try:
                r = fn()
            except Exception as e:  # a broken check must never hide the others
                log.exception("check %s failed", fn.__name__)
                r = [Check(fn.__name__, "warn", (f"檢查項目發生錯誤：{fn.__name__}", f"Check crashed: {fn.__name__}"), (str(e), str(e)))]
            out += r
        if deep:
            for fn in (self._internet, self._line_credentials, self._embed_dim):
                try:
                    out += fn()
                except Exception as e:
                    log.exception("deep check %s failed", fn.__name__)
                    out.append(Check(fn.__name__, "warn", (f"檢查項目發生錯誤：{fn.__name__}", f"Check crashed: {fn.__name__}"), (str(e), str(e))))
        out += self._bot_state(out)
        out += self._last_good(out)
        return out

    def summary(self, checks: List[Check]) -> Dict[str, int]:
        return {"bad": sum(c.level == "bad" for c in checks), "warn": sum(c.level == "warn" for c in checks),
                "fixable": sum(c.level != "ok" and bool(c.fix) for c in checks)}

    def _dirs(self) -> List[Check]:
        missing = [d for d in (paths.DATA_DIR, paths.KB_DIR, paths.MODELS_DIR, paths.BIN_DIR) if not d.exists()]
        if missing:
            return [Check("dirs", "bad", ("缺少必要資料夾", "Required folders are missing"),
                          ("、".join(d.name for d in missing), ", ".join(d.name for d in missing)), fix="make_dirs")]
        try:
            probe = paths.DATA_DIR / ".write_test"
            probe.write_text("x")
            probe.unlink()
        except OSError as e:
            return [Check("dirs", "bad", ("程式資料夾無法寫入", "Program folder is not writable"), (str(e), str(e)),
                          [("請把整個程式資料夾移到「文件」或桌面，不要放在受保護的位置（例如 Program Files）。",
                            "Move the whole program folder to Documents or Desktop, not a protected place such as Program Files.")])]
        free_gb = shutil.disk_usage(paths.APP_DIR).free / 1e9
        if free_gb < 2:
            return [Check("disk", "warn", (f"硬碟剩餘空間不足（{free_gb:.1f} GB）", f"Low disk space ({free_gb:.1f} GB)"),
                          steps=[("請刪除不需要的檔案，至少保留 2 GB。", "Free up at least 2 GB.")])]
        return [Check("dirs", "ok", ("資料夾與硬碟正常", "Folders and disk OK"))]

    def _settings(self) -> List[Check]:
        errs = self.s.validate(self.s.values())
        if errs:
            lines = [e for e in errs.values()]
            return [Check("settings", "bad", ("設定值有誤", "Some settings are invalid"),
                          ("；".join(z for z, _ in lines), "; ".join(e for _, e in lines)),
                          [("按「自動修復」會把有問題的項目改回預設值。", "Auto-fix resets the invalid items to defaults.")], fix="reset_invalid")]
        return [Check("settings", "ok", ("設定值正常", "Settings valid"))]

    def _ports(self) -> List[Check]:
        if self.rt.life.value != "stopped":
            return []
        busy = [k for k in ("webhook_port", "chat_port", "embed_port") if port_busy(self.s.int(k))
                and not (k != "webhook_port" and self.s.get("llm_mode") == "external")]
        if busy:
            names = [SCHEMA[k] for k in busy]
            return [Check("ports", "bad", ("連接埠被占用", "A network port is already in use"),
                          ("、".join(f"{n.zh} {self.s.get(k)}" for n, k in zip(names, busy)),
                           ", ".join(f"{n.en} {self.s.get(k)}" for n, k in zip(names, busy))),
                          [("通常是程式被開了兩次。請先關閉另一個視窗，或按「自動修復」換一個埠號。",
                            "Usually the app is open twice. Close the other window, or Auto-fix to pick another port.")], fix="free_ports")]
        return [Check("ports", "ok", ("連接埠可用", "Ports available"))]

    def _line_cfg(self) -> List[Check]:
        if not self.s.line_ready():
            return [Check("line_cfg", "bad", ("尚未設定 LINE 金鑰", "LINE credentials not set"),
                          steps=[("到 LINE Developers 網站，開啟您的 Messaging API 頻道。", "Open your Messaging API channel at LINE Developers."),
                                 ("複製「Channel secret」（Basic settings 頁）與「Channel access token」（Messaging API 頁，需先按 Issue）。",
                                  "Copy the Channel secret (Basic settings) and Channel access token (Messaging API tab; press Issue)."),
                                 ("貼到本程式「設定」頁的 LINE 區塊並儲存。", "Paste them into the LINE section of Settings and Save.")])]
        return [Check("line_cfg", "ok", ("LINE 金鑰已填寫", "LINE credentials entered"))]

    def _binaries(self) -> List[Check]:
        out = []
        if self.s.get("llm_mode") == "managed":
            if find_llama_server(self.s):
                out.append(Check("llama_server", "ok", ("llama-server 已就緒", "llama-server found")))
            else:
                out.append(Check("llama_server", "bad", ("找不到 llama-server（語言模型引擎）", "llama-server (the model engine) not found"),
                                 steps=[("按「自動準備檔案」，程式會先在「下載」「桌面」「文件」找，找不到就自己上網下載（需要網路）。", "Press Set up files: it searches Downloads, Desktop and Documents, then downloads what is missing (needs internet)."),
                                        (f"還是找不到：到 {LLAMA_RELEASES} 下載（Windows 選檔名含 win 與 cpu 的 zip；Mac 選含 macos-arm64 的 zip，實際檔名會隨版本不同）。",
                                         f"Otherwise download from {LLAMA_RELEASES} (Windows: zip with win and cpu in the name; Mac: macos-arm64)."),
                                        ("解壓縮後，把裡面「所有檔案」放進本程式的 bin 資料夾。", "Unzip and put ALL the files into this program's bin folder.")],
                                 fix="locate_files", fix_label=("自動準備檔案", "Set up files")))
        from .tunnel import find_cloudflared
        if self.s.bool("tunnel_enabled") and not find_cloudflared():
            out.append(Check("cloudflared", "bad", ("找不到 cloudflared（讓 LINE 連到本機的工具）", "cloudflared (links LINE to this computer) not found"),
                             steps=[("按「自動準備檔案」，程式會自己下載。", "Press Set up files; the program downloads it itself.")],
                             fix="locate_files", fix_label=("自動準備檔案", "Set up files")))
        return out

    def _models(self) -> List[Check]:
        if self.s.get("llm_mode") != "managed":
            return []
        bad_paths = [k for k in ("chat_model_path", "embed_model_path") if self.s.get(k).strip() and not resolve_model(self.s, k.split("_")[0])]
        if bad_paths:
            return [Check("model_paths", "bad", ("設定的模型檔不存在", "Configured model file does not exist"),
                          ("檔案可能被移動或刪除", "The file may have been moved or deleted"),
                          [("按「自動修復」改回自動選擇。", "Auto-fix switches back to automatic selection.")], fix="clear_bad_paths")]
        out = []
        for kind, zh, en in (("chat", "對話模型", "chat model"), ("embed", "檢索模型", "embedding model")):
            if resolve_model(self.s, kind):
                out.append(Check(f"model_{kind}", "ok", (f"{zh}已就緒", f"{en.capitalize()} found")))
            else:
                hint = ("檔名需含 embed 或 bge（例如 bge-small-zh-v1.5-f16.gguf）。", "File name must contain embed or bge.") if kind == "embed" \
                    else ("放入任何不含 embed／bge 字樣的 .gguf 檔。", "Any .gguf file without embed/bge in its name.")
                out.append(Check(f"model_{kind}", "bad", (f"找不到{zh}", f"No {en} found"),
                                 steps=[("按「自動準備檔案」，程式會自己下載模型（約 2.7 GB，需要網路）。", "Press Set up files; the program downloads the model (about 2.7 GB, needs internet).")],
                                 fix="locate_files", fix_label=("自動準備檔案", "Set up files")))
        return out

    def _processes(self) -> List[Check]:
        rt = self.rt
        if rt.life.value != "running" or self.s.get("llm_mode") != "managed":
            return []
        dead = rt.servers.dead()
        if not dead:
            return []
        out = []
        for kind in dead:
            exp = explain_llama_log(LlamaServers.tail(kind))
            msg, fix = exp if exp else (("模型程式意外結束", "The model process exited unexpectedly"), "restart_llm")
            out.append(Check(f"proc_{kind}", "bad", (f"{'對話' if kind == 'chat' else '檢索'}模型已停止：{msg[0]}", f"{kind} model stopped: {msg[1]}"),
                             steps=[("按「自動修復」重新啟動；若重複發生，請看「除錯」頁的模型記錄。", "Auto-fix restarts it. If it repeats, read the model log on the Debug page.")],
                             fix=fix or "restart_llm"))
        return out

    def _llm_ready(self) -> List[Check]:
        rt = self.rt
        if rt.life.value != "running":
            return []
        h = rt.llm.health()
        waited = time.time() - (rt.started_at or time.time())
        out = []
        for kind, zh in (("chat", "對話模型"), ("embed", "檢索模型")):
            if h[kind]:
                out.append(Check(f"ready_{kind}", "ok", (f"{zh}運作中", f"{kind} model ready")))
            elif self.s.get("llm_mode") == "managed" and kind in rt.servers.dead():
                continue  # already reported by _processes
            elif waited < 240:
                out.append(Check(f"ready_{kind}", "warn", (f"{zh}載入中（已 {int(waited)} 秒）", f"{kind} model loading ({int(waited)}s)"),
                                 steps=[("大型模型第一次載入可能要幾分鐘，請稍候。", "Large models can take a few minutes to load. Please wait.")]))
            else:
                out.append(Check(f"ready_{kind}", "bad", (f"{zh}沒有回應", f"{kind} model not responding"),
                                 steps=[("按「自動修復」重新啟動模型。", "Auto-fix restarts the model.")], fix="restart_llm"))
        return out

    def _kb(self) -> List[Check]:
        k = self.rt.kb.status()
        out = []
        if not k["ready"]:
            out.append(Check("kb", "bad", ("知識庫尚未建立", "Knowledge base not built yet"),
                             steps=[("確認 database 資料夾有衛教 PDF。", "Make sure the database folder has the education PDFs."),
                                    ("按「自動修復」建立（需要檢索模型已運作）。", "Auto-fix builds it (the embedding model must be running).")], fix="rebuild_kb"))
        elif k["embed_mismatch"]:
            out.append(Check("kb", "bad", ("檢索模型已更換，知識庫需重建", "Embedding model changed; the knowledge base must be rebuilt"),
                             (f"索引是用 {k['built_with']} 建的", f"Index was built with {k['built_with']}"), fix="rebuild_kb"))
        elif k["legacy"]:
            out.append(Check("kb", "warn", ("知識庫是舊版索引，建議用目前的檢索模型重建", "Knowledge base is a legacy index; rebuild it with the current embedding model"),
                             fix="rebuild_kb", fix_label=("重建知識庫", "Rebuild")))
        elif k["pending"]:
            out.append(Check("kb", "warn", (f"有 {len(k['pending'])} 份新文件尚未納入知識庫", f"{len(k['pending'])} new document(s) not yet indexed"),
                             ("、".join(k["pending"]), ", ".join(k["pending"])), fix="rebuild_kb", fix_label=("重建知識庫", "Rebuild")))
        else:
            out.append(Check("kb", "ok", (f"知識庫正常（{k['vectors']} 段）", f"Knowledge base OK ({k['vectors']} passages)")))
        if k["empty"]:
            out.append(Check("kb_empty", "warn", ("有文件讀不到文字（可能是掃描檔）", "Some documents have no readable text (scanned?)"),
                             ("、".join(k["empty"]), ", ".join(k["empty"])),
                             [("請改用可以選取、複製文字的 PDF，或先用 OCR 轉成文字版。", "Use a PDF whose text can be selected, or run OCR on it first.")]))
        if k["build"]["state"] == "failed":
            out.append(Check("kb_build", "bad", ("上次重建知識庫失敗", "Last knowledge-base rebuild failed"), (k["build"]["message"], k["build"]["message"]),
                             [("確認檢索模型已運作後，再按「重建」。", "Make sure the embedding model is running, then rebuild.")], fix="rebuild_kb"))
        return out

    def _tunnel(self) -> List[Check]:
        rt = self.rt
        if rt.life.value != "running" or not self.s.bool("tunnel_enabled") or not self.s.line_ready():
            return []
        t = rt.tunnel.status()
        if t["state"] == "up" and t["webhook_ok"]:
            return [Check("tunnel", "ok", ("LINE 連線正常", "LINE connection OK"), (str(t["url"]), str(t["url"])))]
        if t["state"] == "starting":
            return [Check("tunnel", "warn", ("正在建立 LINE 連線…", "Connecting to LINE…"))]
        if t["state"] == "up":
            return [Check("tunnel", "warn", ("通道已建立，但 LINE 驗證未通過", "Tunnel is up but LINE verification failed"),
                          steps=[("多半是 Channel Access Token 填錯，請到設定頁重貼後按「測試 LINE 連線」。", "Usually a wrong Channel Access Token. Re-paste it in Settings and press Test LINE connection.")],
                          fix="restart_tunnel", fix_label=("重新連線", "Reconnect"))]
        return [Check("tunnel", "bad", ("LINE 連線失敗", "LINE connection failed"), (str(t["message"]), str(t["message"])),
                      [("確認電腦可以上網。", "Check the computer is online."), ("按「重新連線」。", "Press Reconnect.")],
                      fix="restart_tunnel", fix_label=("重新連線", "Reconnect"))]

    def _errors(self) -> List[Check]:
        recent = list(self.rt.bot.metrics)[-10:]
        if len(recent) >= 3 and sum(m["flag"] == "error" for m in recent) >= 3:
            return [Check("errors", "bad", ("最近多則回覆發生錯誤", "Several recent replies failed"),
                          steps=[("通常是模型當機。按「自動修復」重新啟動模型。", "Usually the model has hung. Auto-fix restarts it.")], fix="restart_llm")]
        return []

    def _no_webhook(self) -> List[Check]:
        rt = self.rt
        t = rt.tunnel.status()
        if (rt.life.value == "running" and t["state"] == "up" and t["webhook_ok"] and rt.last_webhook_at is None
                and time.time() - (rt.started_at or time.time()) > 300):
            return [Check("no_webhook", "warn", ("通道正常，但還沒收到任何 LINE 訊息", "Tunnel OK, but no LINE message has arrived"),
                          steps=[("用手機掃 QR code，確定加的是同一個官方帳號好友。", "Make sure you added the same official account as a friend."),
                                 ("LINE Developers → Messaging API → 開啟「Use webhook」。", "LINE Developers → Messaging API → turn Use webhook ON."),
                                 ("LINE Official Account Manager → 回應設定 → 關閉「自動回應訊息」。", "LINE Official Account Manager → Response settings → turn Auto-response OFF."),
                                 ("傳一則訊息給機器人試試。", "Send the bot a message.")])]
        return []

    def _bot_state(self, others: List[Check]) -> List[Check]:
        if self.rt.life.value == "running":
            return []
        blocking = [c for c in others if c.level == "bad" and c.fix != "rebuild_kb" and not c.id.startswith("model") and c.id != "llama_server"]
        if blocking:
            return []
        return [Check("bot_state", "warn", ("機器人目前沒有在運作", "The bot is not running"),
                      steps=[("按「啟動機器人」，或「自動修復」。", "Press Start bot, or Auto-fix.")], fix="start_bot", fix_label=("啟動機器人", "Start bot"))]

    def _last_good(self, others: List[Check]) -> List[Check]:
        diff = self.s.differs_from_good()
        if diff and any(c.level == "bad" for c in others):
            names = [SCHEMA[k].zh for k in diff if k in SCHEMA]
            return [Check("last_good", "warn", ("有問題，而且設定和上次成功運作時不同", "Problems found, and settings differ from the last working run"),
                          ("被改過的項目：" + "、".join(names), "Changed: " + ", ".join(SCHEMA[k].en for k in diff if k in SCHEMA)),
                          [("如果是剛改過設定才出問題，按這個按鈕即可還原。", "If trouble started after a settings change, this undoes it.")],
                          fix="restore_good", fix_label=("還原到上次正常的設定", "Restore last working settings"))]
        return []

    # ---- deep checks (network) ---------------------------------------------
    def _internet(self) -> List[Check]:
        try:
            socket.create_connection(("api.line.me", 443), 4).close()
            return [Check("internet", "ok", ("可以連到 LINE", "Can reach LINE"))]
        except OSError:
            return [Check("internet", "bad", ("連不到 LINE（沒有網路？）", "Cannot reach LINE (offline?)"),
                          steps=[("檢查電腦網路、Wi-Fi、醫院防火牆是否擋住 api.line.me。", "Check network/Wi-Fi and that the hospital firewall allows api.line.me."),
                                 ("在瀏覽器開 https://api.line.me 看看是否能開啟。", "Try opening https://api.line.me in a browser.")])]

    def _line_credentials(self) -> List[Check]:
        if not self.s.line_ready():
            return []
        name = self.rt.line.bot_name()
        if name:
            return [Check("line_cred", "ok", (f"LINE 金鑰有效（官方帳號：{name}）", f"LINE credentials valid (account: {name})"))]
        return [Check("line_cred", "bad", ("LINE Channel Access Token 無效或無法驗證", "LINE Channel Access Token invalid or unverifiable"),
                      steps=[("重新到 LINE Developers → Messaging API，按 Issue 產生新的 token。", "In LINE Developers → Messaging API press Issue for a new token."),
                             ("整串複製（很長，不要有空格），貼到設定頁後儲存。", "Copy the whole string with no spaces, paste it in Settings and Save."),
                             ("若確定沒錯，可能是網路問題，請看上方「可以連到 LINE」。", "If it is right, it may be a network problem; see the internet check.")])]

    def _embed_dim(self) -> List[Check]:
        rt = self.rt
        if not (rt.kb.status()["ready"] and rt.llm.health()["embed"]):
            return []
        try:
            n = len(rt.llm.embed(["測試"])[0])
            rt.kb._load()
            d = rt.kb._index.d
        except Exception as e:
            return [Check("embed_dim", "warn", ("無法測試檢索模型", "Could not test the embedding model"), (str(e), str(e)))]
        if n != d:
            return [Check("embed_dim", "bad", ("檢索模型與知識庫不相容（向量維度不同）", "Embedding model does not match the knowledge base (dimension differs)"),
                          (f"模型 {n} 維，索引 {d} 維", f"model {n}-dim, index {d}-dim"),
                          [("按「重建知識庫」。", "Rebuild the knowledge base.")], fix="rebuild_kb", fix_label=("重建知識庫", "Rebuild"))]
        return [Check("embed_dim", "ok", ("檢索模型與知識庫相容", "Embedding model matches the knowledge base"))]

    # ====================================================================== fixes
    def fix(self, fix_id: str) -> Tuple[bool, str, str]:
        fn = getattr(self, f"_fix_{fix_id}", None)
        if not fn:
            return False, "不明的修復項目", "Unknown fix"
        try:
            ok, zh, en = fn()
        except Exception as e:
            log.exception("fix %s failed", fix_id)
            return False, f"修復失敗：{e}", f"Fix failed: {e}"
        log.info("auto-fix %s -> %s", fix_id, zh)
        self.rt.incident("info" if ok else "warn", f"自動修復：{zh}", f"Auto-fix: {en}")
        return ok, zh, en

    def _fix_make_dirs(self):
        paths.ensure_dirs()
        return True, "已建立資料夾", "Folders created"

    def _fix_reset_invalid(self):
        bad = list(self.s.validate(self.s.values()))
        self.s.reset([k for k in bad if k in SCHEMA])
        # port clashes: reset all ports to defaults
        if self.s.validate(self.s.values()):
            self.s.reset(["webhook_port", "chat_port", "embed_port", "ui_port"])
        return True, f"已把 {len(bad)} 項設定改回預設值", f"Reset {len(bad)} setting(s) to defaults"

    def _fix_clear_bad_paths(self):
        cleared = []
        for k, kind in (("chat_model_path", "chat"), ("embed_model_path", "embed")):
            if self.s.get(k).strip() and not resolve_model(self.s, kind):
                cleared.append(k)
        if self.s.get("llama_server_path").strip() and not find_llama_server(self.s):
            cleared.append("llama_server_path")
        self.s.reset(cleared)
        return True, "已改回自動選擇", "Switched back to automatic selection"

    def _fix_free_ports(self):
        if self.rt.life.value != "stopped":
            return False, "請先停止機器人再換連接埠", "Stop the bot first"
        used = {self.s.int("ui_port")}
        changes = {}
        for k in ("webhook_port", "chat_port", "embed_port"):
            p = self.s.int(k)
            if p in used or port_busy(p):
                p = free_port(p + 1, used)
                changes[k] = str(p)
            used.add(p)
        if changes:
            self.s.update(changes)
            self.rt.llm.clear_cache()
        return True, "已更換連接埠：" + "、".join(f"{SCHEMA[k].zh}→{v}" for k, v in changes.items()), \
            "Ports changed: " + ", ".join(f"{SCHEMA[k].en}→{v}" for k, v in changes.items())

    def _fix_locate_files(self):
        found = self._scan_for_files()
        done_zh, done_en = [], []
        if found["llama"] and not find_llama_server(self.s):
            self.s.update({"llama_server_path": str(found["llama"][0])})
            done_zh.append("llama-server"); done_en.append("llama-server")
        if found["cloudflared"]:
            from .tunnel import find_cloudflared
            if not find_cloudflared():
                src = found["cloudflared"][0]
                dst = paths.BIN_DIR / src.name
                shutil.copy2(src, dst)
                os.chmod(dst, 0o755)
                done_zh.append("cloudflared"); done_en.append("cloudflared")
        have = {m.name for m in list_models()}
        cand = [p for p in found["gguf"] if p.name not in have]
        for kind in ("chat", "embed"):
            if not resolve_model(self.s, kind) and cand:
                pick = [p for p in cand if any(h in p.name.lower() for h in ("embed", "bge", "e5", "gte", "minilm")) == (kind == "embed")]
                if pick:
                    best = (min if kind == "embed" else max)(pick, key=lambda p: p.stat().st_size)
                    self.s.update({f"{kind}_model_path": str(best)})
                    done_zh.append(best.name); done_en.append(best.name)
        if not done_zh:
            return self._fix_download_components()  # nothing lying around: fetch it ourselves
        return True, "已設定：" + "、".join(done_zh), "Set up: " + ", ".join(done_en)

    @staticmethod
    def _scan_for_files() -> Dict[str, List[Path]]:
        roots = [paths.APP_DIR.parent, Path.home() / "Downloads", Path.home() / "Desktop", Path.home() / "Documents"]
        skip = {"node_modules", "Library", "AppData", "__pycache__", "venv", ".venv", "site-packages"}
        found: Dict[str, List[Path]] = {"llama": [], "cloudflared": [], "gguf": []}
        budget, seen = 30000, set()
        for root in roots:
            if not root.is_dir() or root in seen:
                continue
            seen.add(root)
            for dp, dns, fns in os.walk(root):
                if len(Path(dp).relative_to(root).parts) >= 3:
                    dns[:] = []
                dns[:] = [d for d in dns if not d.startswith(".") and d not in skip]
                budget -= len(fns)
                if budget < 0:
                    return found
                for f in fns:
                    fl = f.lower()
                    p = Path(dp) / f
                    if fl in ("llama-server", "llama-server.exe"):
                        found["llama"].append(p)
                    elif fl in ("cloudflared", "cloudflared.exe") or fl.startswith("cloudflared-windows"):
                        found["cloudflared"].append(p)
                    elif fl.endswith(".gguf"):
                        found["gguf"].append(p)
        return found

    def _fix_download_components(self):
        if not self.rt.installer.missing():
            return True, "所需檔案都已就緒", "All required files are already in place"
        started = self.rt.installer.start()
        mb = self.rt.installer.status()["missing_mb"]
        return True, ("開始下載所需檔案（約 %.1f GB），請保持網路連線" % (mb / 1000) if started else "已經在下載中"), \
            ("Downloading required files (about %.1f GB); keep the network connected" % (mb / 1000) if started else "Download already running")

    def _fix_degrade_llm(self):
        """Out of memory: smaller context, CPU only, then restart."""
        self.s.update({"llm_ctx": "2048", "llm_gpu_layers": "0"})
        return self._fix_restart_llm(prefix=("已降低記憶體用量（上下文 2048、僅 CPU）。", "Lowered memory use (context 2048, CPU only). "))

    def _fix_restart_llm(self, prefix: T = ("", "")):
        if self.s.get("llm_mode") != "managed":
            return False, "目前使用外部模型服務，請到該服務重新啟動", "Using an external server; restart it there"
        problems = self.rt.servers.restart()
        if problems:
            msg = "；".join(problems.values())
            return False, prefix[0] + msg, prefix[1] + msg
        return True, prefix[0] + "已重新啟動模型", prefix[1] + "Models restarted"

    def _fix_restart_tunnel(self):
        self.rt.tunnel.stop()
        self.rt.tunnel.start(self.s.int("webhook_port"))
        return True, "正在重新連線 LINE", "Reconnecting to LINE"

    def _fix_rebuild_kb(self):
        if not self.rt.llm.health()["embed"]:
            return False, "檢索模型還沒運作，請先啟動機器人並等待載入", "Embedding model is not running; start the bot and wait for it to load"
        started = self.rt.kb.start_rebuild()
        return True, "開始重建知識庫" if started else "知識庫正在重建中", "Rebuild started" if started else "Rebuild already running"

    def _fix_restore_good(self):
        changed = self.s.restore_good()
        return True, f"已還原 {len(changed)} 項設定", f"Restored {len(changed)} setting(s)"

    def _fix_start_bot(self):
        problems = self.rt.start()
        if problems:
            return False, "；".join(problems.values()), "; ".join(problems.values())
        return True, "機器人已啟動", "Bot started"

    def preflight(self) -> None:
        """Silent safe fixes run before every start, so common operator mistakes never reach the nurse."""
        safe = ("make_dirs", "reset_invalid", "clear_bad_paths", "locate_files", "free_ports")
        wanted = {c.fix for c in self.run() if c.level == "bad" and c.fix in safe}
        for f in safe:
            if f in wanted:
                self.fix(f)

    # ---- one-click: loop until nothing more can be fixed --------------------
    ORDER = ["make_dirs", "reset_invalid", "clear_bad_paths", "locate_files", "free_ports", "start_bot",
             "degrade_llm", "restart_llm", "restart_tunnel", "rebuild_kb"]

    def fix_all_async(self) -> bool:
        with self._job_lock:
            if self._job["running"]:
                return False
            self._job = {"running": True, "log": [], "done": False, "progress": ""}
        threading.Thread(target=self._fix_all, daemon=True, name="fix-all").start()
        return True

    def job(self) -> dict:
        return dict(self._job, log=list(self._job["log"]))

    def _wait_download(self) -> None:
        while self.rt.installer.status()["job"]["running"]:
            j = self.rt.installer.status()["job"]
            pct = int(100 * j["bytes"] / j["total"]) if j["total"] else 0
            self._job["progress"] = f"下載中 {j['current']} {pct}% / Downloading {j['current']} {pct}%"
            time.sleep(2)
        self._job["progress"] = ""
        err = self.rt.installer.status()["job"]["error"]
        self._say(err if err else "檔案下載完成", err if err else "Downloads finished", not err)

    def _say(self, zh: str, en: str, ok: bool = True) -> None:
        self._job["log"].append({"zh": zh, "en": en, "ok": ok})

    def _fix_all(self) -> None:
        tried: set = set()
        try:
            for _ in range(5):
                wanted = {c.fix for c in self.run() if c.level != "ok" and c.fix and c.fix != "restore_good"}
                todo = [f for f in self.ORDER if f in wanted and f not in tried]
                if not todo:
                    break
                for f in todo:
                    tried.add(f)
                    if f == "rebuild_kb":  # models load in the background; wait for the embedder
                        for _w in range(60):
                            if self.rt.llm.health()["embed"] or self.rt.life.value != "running":
                                break
                            time.sleep(2)
                    ok, zh, en = self.fix(f)
                    self._say(zh, en, ok)
                    if f == "locate_files" and self.rt.installer.status()["job"]["running"]:
                        self._wait_download()
            left = [c for c in self.run() if c.level == "bad"]
            if left:
                self._say(f"還有 {len(left)} 個問題需要您處理，請看下方步驟。", f"{len(left)} problem(s) need your action; see the steps below.", False)
            else:
                self._say("全部正常。", "Everything looks good.")
        except Exception as e:
            log.exception("fix_all crashed")
            self._say(f"自動修復發生錯誤：{e}", f"Auto-fix crashed: {e}", False)
        finally:
            self._job["running"] = False
            self._job["done"] = True
