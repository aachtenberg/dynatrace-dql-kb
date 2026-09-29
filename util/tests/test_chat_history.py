"""The browser chat's server with history on, over real HTTP: a scripted
model stands in for the provider and a canned result for Grail, so this needs
no credentials and no tenant.

    python -m unittest discover -s util/tests -v
"""

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dqlagent import core, llm, store, web  # noqa: E402

EDGES = [{"source_id": "SERVICE-000000000000A001", "source_type": "SERVICE", "source_name": "frontend",
          "target_id": "SERVICE-000000000000A002", "target_type": "SERVICE", "target_name": "checkout"},
         {"source_id": "SERVICE-000000000000A002", "source_type": "SERVICE", "source_name": "checkout",
          "target_id": "SERVICE-000000000000A003", "target_type": "SERVICE", "target_name": "payments"}]
QUERY = "smartscapeEdges calls\n| limit 100"


class ScriptedModel(llm.ChatModel):
    """'draw ...' runs a query, then draws it. 'again ...' draws r1 without
    running anything, which only works if the conversation's results survived."""
    provider = "scripted"
    label = "Scripted"

    @classmethod
    def settings_fields(cls):
        return [{"key": "model", "label": "Model", "type": "text", "default": "script-1"}]

    def chat(self, system, messages, tools, max_tokens=None):
        last = messages[-1]["content"]
        done = [b for b in last if b.get("type") == "tool_result"]
        question = next(b["text"] for m in reversed(messages) if m["role"] == "user"
                        for b in m["content"] if b.get("type") == "text")
        graph = {"source_field": "source_id", "target_field": "target_id",
                 "source_label_field": "source_name", "target_label_field": "target_name",
                 "title": "Calls"}
        n = len(messages)
        if not done:
            if question.startswith("again"):
                return {"stop": "tool_use", "content": [{"type": "tool_call", "id": f"c{n}",
                        "name": "show_graph", "input": dict(graph, result_id="r1")}]}
            return {"stop": "tool_use", "content": [{"type": "tool_call", "id": f"c{n}",
                    "name": "run_dql", "input": {"query": QUERY}}]}
        r = done[-1]
        if r["name"] == "run_dql" and not r["is_error"]:
            rid = json.loads(r["text"])["result_id"]
            return {"stop": "tool_use", "content": [{"type": "tool_call", "id": f"c{n}",
                    "name": "show_graph", "input": dict(graph, result_id=rid)}]}
        return {"stop": "end_turn", "content": [{"type": "text", "text": "Summary. " + r["text"]}]}


def fake_grail(query):
    return {"records": EDGES, "metadata": {"grail": {"scannedBytes": 2048}}}, ""


class ChatHistoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patches = [mock.patch.dict(llm.PROVIDERS, {"scripted": ScriptedModel}),
                       mock.patch.dict(os.environ, {"LLM_PROVIDER": "scripted", "DQL_CHAT_AUDIT": "off"}),
                       mock.patch.object(core, "_query_grail", fake_grail),
                       mock.patch.object(web.Handler, "log_message", lambda *a: None)]
        for p in cls.patches:
            p.start()
        cls.index = core.DocIndex()        # load the docs once for every server

    @classmethod
    def tearDownClass(cls):
        for p in reversed(cls.patches):
            p.stop()

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.dir.name, "chats.db")
        self.start()

    def tearDown(self):
        self.stop()
        self.dir.cleanup()

    # -- a server we can restart on the same database ------------------------
    def start(self):
        self.history = store.Store(self.db)
        cfg = web.Config("127.0.0.1", 0, "proxy")
        with mock.patch.object(core, "DocIndex", lambda: self.index):
            self.server = web.ChatServer(cfg, self.history)
        self.server.can_run = True          # the canned Grail stands in for a tenant
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.history.close()

    def call(self, path, body=None, user="ann"):
        req = urllib.request.Request(self.base + path, method="POST" if body is not None else "GET",
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"x-amzn-oidc-identity": user, "X-DQL-Client": "1",
                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read().decode()
                status = r.status
        except urllib.error.HTTPError as e:
            raw, status = e.read().decode(), e.code
        if path == "/api/chat" and status == 200:
            events = []
            for chunk in raw.split("\n\n"):
                kind = data = None
                for line in chunk.splitlines():
                    if line.startswith("event:"):
                        kind = line[6:].strip()
                    elif line.startswith("data:"):
                        data = json.loads(line[5:])
                if kind:
                    events.append((kind, data))
            return status, events
        return status, json.loads(raw) if raw else {}

    def ask(self, sid, text, user="ann"):
        status, events = self.call("/api/chat", {"session": sid, "message": text, "auto": True}, user)
        self.assertEqual(status, 200, events)
        return events

    # -- tests -------------------------------------------------------------
    def test_a_chat_is_saved_and_reopens_as_it_looked(self):
        events = self.ask("conv-00001", "draw who calls checkout")
        kinds = [k for k, _ in events]
        self.assertEqual(kinds[0], "conversation")
        self.assertEqual(events[0][1]["title"], "draw who calls checkout")
        self.assertIn("visual", kinds)
        self.assertEqual(kinds[-1], "done")

        status, listing = self.call("/api/conversations")
        self.assertEqual(status, 200)
        self.assertTrue(listing["history"])
        self.assertEqual([(c["id"], c["turns"]) for c in listing["conversations"]], [("conv-00001", 1)])

        status, conv = self.call("/api/conversation?id=conv-00001")
        self.assertEqual(status, 200)
        saved = [e["kind"] for e in conv["events"]]
        self.assertEqual(saved[0], "user")
        for kind in ("query", "result", "visual", "answer"):
            self.assertIn(kind, saved)
        self.assertNotIn("thinking", saved)
        visual = next(e["data"] for e in conv["events"] if e["kind"] == "visual")
        self.assertEqual(len(visual["spec"]["nodes"]), 3)

    def test_the_model_carries_on_after_a_restart(self):
        self.ask("conv-00002", "draw the calls")
        self.stop()
        self.start()                        # a new process, the same database
        events = self.ask("conv-00002", "again, as a graph")
        kinds = [k for k, _ in events]
        self.assertNotIn("query", kinds)    # nothing re-ran: r1 came from the store
        self.assertIn("visual", kinds, events)
        agent = self.server.sessions["ann\x00conv-00002"].agent
        # Two questions, each with its tool calls and results, in the model's context.
        questions = [m for m in agent.messages if m["role"] == "user"
                     and any(b.get("type") == "text" for b in m["content"])]
        self.assertEqual(len(questions), 2)
        status, conv = self.call("/api/conversation?id=conv-00002")
        self.assertEqual(max(e["turn"] for e in conv["events"]), 2)

    def test_other_users_see_nothing(self):
        self.ask("conv-00003", "draw it")
        status, listing = self.call("/api/conversations", user="bob")
        self.assertEqual(listing["conversations"], [])
        status, _ = self.call("/api/conversation?id=conv-00003", user="bob")
        self.assertEqual(status, 404)
        status, _ = self.call("/api/conversation/delete", {"session": "bob-000001", "id": "conv-00003"}, user="bob")
        self.assertEqual(status, 404)
        status, _ = self.call("/api/conversation?id=conv-00003")
        self.assertEqual(status, 200)

    def test_rename_and_delete(self):
        self.ask("conv-00004", "draw it")
        status, _ = self.call("/api/conversation/rename", {"session": "conv-00004", "id": "conv-00004",
                                                           "title": "Checkout callers"})
        self.assertEqual(status, 200)
        self.assertEqual(self.call("/api/conversations")[1]["conversations"][0]["title"], "Checkout callers")
        status, _ = self.call("/api/conversation/delete", {"session": "conv-00005", "id": "conv-00004"})
        self.assertEqual(status, 200)
        self.assertEqual(self.call("/api/conversations")[1]["conversations"], [])
        self.assertEqual(self.call("/api/conversation?id=conv-00004")[0], 404)

    def test_delete_several_at_once_for_good(self):
        for sid in ("conv-00010", "conv-00011", "conv-00012"):
            self.ask(sid, f"draw it for {sid}")
        status, body = self.call("/api/conversation/delete", {"session": "conv-00013",
                                                             "ids": ["conv-00010", "conv-00011"]})
        self.assertEqual((status, body["deleted"]), (200, 2))
        self.assertEqual([c["id"] for c in self.call("/api/conversations")[1]["conversations"]], ["conv-00012"])
        # Gone from the file too: no trash, no leftover text in free pages.
        self.history.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        raw = open(self.db, "rb").read()
        self.assertNotIn(b"draw it for conv-00010", raw)
        self.assertIn(b"draw it for conv-00012", raw)
        # Another user's ids are simply not found.
        status, _ = self.call("/api/conversation/delete", {"session": "bob-000001", "ids": ["conv-00012"]}, user="bob")
        self.assertEqual(status, 404)
        status, _ = self.call("/api/conversation/delete", {"session": "conv-00013", "ids": []})
        self.assertEqual(status, 400)

    def test_settings_are_per_user_and_survive_a_restart(self):
        status, cfg = self.call("/api/settings", {"session": "conv-00006", "values": {"max_turns": 7}})
        self.assertEqual(status, 200, cfg)
        self.stop()
        self.start()
        turns = lambda user: next(f["value"] for f in self.call("/api/config?session=conv-00007", user=user)[1]["fields"]
                                  if f["key"] == "max_turns")
        self.assertEqual(turns("ann"), 7)
        self.assertEqual(turns("bob"), core.MAX_TURNS)

    def test_config_reports_history(self):
        status, cfg = self.call("/api/config?session=conv-00008")
        self.assertEqual(cfg["history"]["on"], True)
        self.assertEqual(cfg["history"]["days"], 90)


class NoHistoryTest(unittest.TestCase):
    def test_history_off_keeps_the_old_behaviour(self):
        with mock.patch.dict(llm.PROVIDERS, {"scripted": ScriptedModel}), \
             mock.patch.dict(os.environ, {"LLM_PROVIDER": "scripted", "DQL_CHAT_AUDIT": "off"}), \
             mock.patch.object(web.Handler, "log_message", lambda *a: None):
            server = web.ChatServer(web.Config("127.0.0.1", 0, "none"), None)
            base = f"http://127.0.0.1:{server.server_address[1]}"
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                with urllib.request.urlopen(base + "/api/conversations?session=conv-00009") as r:
                    self.assertEqual(json.loads(r.read()), {"history": False, "conversations": []})
                with urllib.request.urlopen(base + "/api/config?session=conv-00009") as r:
                    self.assertEqual(json.loads(r.read())["history"], {"on": False, "days": 0})
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
