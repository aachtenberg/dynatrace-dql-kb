"""Chat history for the browser chat, in SQLite (standard library).

A conversation keeps two things:
  - what the page drew, event by event (the question, each query and its
    result, charts, the answer), so it reopens exactly as it looked;
  - the agent's state (the model's messages and the query results visuals
    draw from), so the model carries on where it left off.
Every row belongs to one user; nobody can list or open another user's chats.
Per-user settings (model, turns, output tokens) live here too.

    DQL_CHAT_HISTORY          1 (default), or 0 to keep nothing on disk
    DQL_CHAT_DB               database file (default ~/.local/share/dql-chat/chats.db)
    DQL_CHAT_RETENTION_DAYS   delete conversations untouched this long (default 90; 0 keeps them)
"""

import json
import os
import re
import sqlite3
import sys
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    user    TEXT NOT NULL,
    id      TEXT NOT NULL,
    title   TEXT NOT NULL DEFAULT '',
    created REAL NOT NULL,
    updated REAL NOT NULL,
    turns   INTEGER NOT NULL DEFAULT 0,
    state   TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (user, id)
);
CREATE INDEX IF NOT EXISTS conversations_recent ON conversations (user, updated DESC);
CREATE TABLE IF NOT EXISTS events (
    user TEXT NOT NULL,
    conv TEXT NOT NULL,
    seq  INTEGER NOT NULL,
    turn INTEGER NOT NULL,
    kind TEXT NOT NULL,
    data TEXT NOT NULL,
    ts   REAL NOT NULL,
    PRIMARY KEY (user, conv, seq)
);
CREATE TABLE IF NOT EXISTS results (
    user    TEXT NOT NULL,
    conv    TEXT NOT NULL,
    rid     TEXT NOT NULL,
    pos     INTEGER NOT NULL,
    query   TEXT NOT NULL,
    records TEXT NOT NULL,
    PRIMARY KEY (user, conv, rid)
);
CREATE TABLE IF NOT EXISTS prefs (
    user    TEXT PRIMARY KEY,
    data    TEXT NOT NULL,
    updated REAL NOT NULL
);
"""

# Events the page redraws on reopen. "thinking", "approval" and "done" are
# moments, not content.
KEPT_EVENTS = {"user", "tool", "query", "lint", "skipped", "result", "query_error",
               "visual", "visual_error", "answer", "error", "cancelled"}
TITLE_CHARS = 80


def title_from(question: str) -> str:
    text = re.sub(r"\s+", " ", question).strip()
    if len(text) <= TITLE_CHARS:
        return text
    cut = text[:TITLE_CHARS].rsplit(" ", 1)[0]
    return (cut or text[:TITLE_CHARS]) + "…"


def _dumps(obj) -> str:
    return json.dumps(obj, default=str, ensure_ascii=False, separators=(",", ":"))


class Store:
    def __init__(self, path: str, retention_days: int = 90):
        self.path = path
        self.retention_days = retention_days
        self.lock = threading.Lock()
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self.db.row_factory = sqlite3.Row
        if path != ":memory:":
            self.db.execute("PRAGMA journal_mode=WAL")
            try:
                os.chmod(path, 0o600)     # query results are tenant data
            except OSError:
                pass
        self.db.executescript(SCHEMA)
        self._pruned = 0.0
        self.prune()

    def close(self):
        with self.lock:
            self.db.close()

    # -- conversations -----------------------------------------------------
    def conversations(self, user: str, limit: int = 200) -> list[dict]:
        self.prune()
        rows = self.db.execute(
            "SELECT id, title, created, updated, turns FROM conversations "
            "WHERE user = ? AND turns > 0 ORDER BY updated DESC LIMIT ?", (user, limit))
        return [dict(r) for r in rows]

    def get(self, user: str, conv: str) -> dict | None:
        row = self.db.execute("SELECT id, title, created, updated, turns FROM conversations "
                              "WHERE user = ? AND id = ?", (user, conv)).fetchone()
        return dict(row) if row else None

    def events(self, user: str, conv: str) -> list[dict]:
        rows = self.db.execute("SELECT turn, kind, data FROM events WHERE user = ? AND conv = ? "
                               "ORDER BY seq", (user, conv))
        return [{"turn": r["turn"], "kind": r["kind"], "data": json.loads(r["data"])} for r in rows]

    def begin_turn(self, user: str, conv: str, question: str) -> int:
        """Record a question; creates the conversation on its first one."""
        now = time.time()
        with self.lock, self.db:
            row = self.db.execute("SELECT turns FROM conversations WHERE user = ? AND id = ?",
                                  (user, conv)).fetchone()
            if row is None:
                self.db.execute("INSERT INTO conversations (user, id, title, created, updated, turns) "
                                "VALUES (?, ?, ?, ?, ?, 1)", (user, conv, title_from(question), now, now))
                turn = 1
            else:
                turn = row["turns"] + 1
                self.db.execute("UPDATE conversations SET turns = ?, updated = ?, "
                                "title = CASE WHEN title = '' THEN ? ELSE title END "
                                "WHERE user = ? AND id = ?",
                                (turn, now, title_from(question), user, conv))
            self._add(user, conv, turn, "user", {"text": question}, now)
        return turn

    def add_event(self, user: str, conv: str, turn: int, kind: str, data: dict):
        if kind not in KEPT_EVENTS:
            return
        with self.lock, self.db:
            self._add(user, conv, turn, kind, data, time.time())

    def _add(self, user, conv, turn, kind, data, now):
        seq = self.db.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM events WHERE user = ? AND conv = ?",
                              (user, conv)).fetchone()[0]
        self.db.execute("INSERT INTO events (user, conv, seq, turn, kind, data, ts) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (user, conv, seq, turn, kind, _dumps(data), now))

    def rename(self, user: str, conv: str, title: str) -> bool:
        title = re.sub(r"\s+", " ", title).strip()[:200]
        if not title:
            return False
        with self.lock, self.db:
            cur = self.db.execute("UPDATE conversations SET title = ? WHERE user = ? AND id = ?",
                                  (title, user, conv))
        return cur.rowcount > 0

    def delete(self, user: str, conv: str) -> bool:
        with self.lock, self.db:
            for table, col in (("events", "conv"), ("results", "conv"), ("conversations", "id")):
                cur = self.db.execute(f"DELETE FROM {table} WHERE user = ? AND {col} = ?", (user, conv))
        return cur.rowcount > 0

    # -- agent state -------------------------------------------------------
    def save_state(self, user: str, conv: str, state: dict):
        """Messages are rewritten; each query result is written once."""
        results = state.get("results") or []
        keep = [rid for rid, _ in results]
        with self.lock, self.db:
            self.db.execute("UPDATE conversations SET state = ?, updated = ? WHERE user = ? AND id = ?",
                            (_dumps({"messages": state.get("messages") or [],
                                     "result_seq": state.get("result_seq", 0)}),
                             time.time(), user, conv))
            have = {r[0] for r in self.db.execute(
                "SELECT rid FROM results WHERE user = ? AND conv = ?", (user, conv))}
            for rid, r in results:
                if rid not in have:
                    pos = int(rid[1:]) if rid[1:].isdigit() else 0     # r1, r2, ... in order
                    self.db.execute("INSERT INTO results (user, conv, rid, pos, query, records) "
                                    "VALUES (?, ?, ?, ?, ?, ?)",
                                    (user, conv, rid, pos, r.get("query", ""),
                                     _dumps(r.get("records") or [])))
            for rid in have - set(keep):
                self.db.execute("DELETE FROM results WHERE user = ? AND conv = ? AND rid = ?",
                                (user, conv, rid))

    def load_state(self, user: str, conv: str) -> dict | None:
        row = self.db.execute("SELECT state FROM conversations WHERE user = ? AND id = ?",
                              (user, conv)).fetchone()
        if row is None:
            return None
        state = json.loads(row["state"] or "{}")
        state["results"] = [(r["rid"], {"query": r["query"], "records": json.loads(r["records"])})
                            for r in self.db.execute(
                                "SELECT rid, query, records FROM results WHERE user = ? AND conv = ? "
                                "ORDER BY pos", (user, conv))]
        return state

    # -- per-user settings -------------------------------------------------
    def prefs(self, user: str) -> dict:
        row = self.db.execute("SELECT data FROM prefs WHERE user = ?", (user,)).fetchone()
        return json.loads(row["data"]) if row else {}

    def save_prefs(self, user: str, data: dict):
        with self.lock, self.db:
            self.db.execute("INSERT INTO prefs (user, data, updated) VALUES (?, ?, ?) "
                            "ON CONFLICT(user) DO UPDATE SET data = excluded.data, updated = excluded.updated",
                            (user, _dumps(data), time.time()))

    # -- retention ---------------------------------------------------------
    def prune(self):
        """Delete conversations untouched for retention_days; at most once an hour."""
        if self.retention_days <= 0 or time.time() - self._pruned < 3600:
            return
        self._pruned = time.time()
        cutoff = time.time() - self.retention_days * 86400
        with self.lock, self.db:
            old = self.db.execute("SELECT user, id FROM conversations WHERE updated < ?", (cutoff,)).fetchall()
            for r in old:
                for table, col in (("events", "conv"), ("results", "conv"), ("conversations", "id")):
                    self.db.execute(f"DELETE FROM {table} WHERE user = ? AND {col} = ?", (r["user"], r["id"]))


def default_path() -> str:
    base = os.getenv("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return str(Path(base) / "dql-chat" / "chats.db")


def open_from_env() -> Store | None:
    """The configured store, or None when history is off or cannot be opened
    (the chat then works as before, in memory only)."""
    if os.getenv("DQL_CHAT_HISTORY", "1").strip().lower() in ("0", "false", "no", "off"):
        return None
    path = os.getenv("DQL_CHAT_DB") or default_path()
    try:
        return Store(path, int(os.getenv("DQL_CHAT_RETENTION_DAYS", "90")))
    except (OSError, sqlite3.Error, ValueError) as e:
        print(f"Chat history is off: cannot open {path}: {e}", file=sys.stderr)
        return None
