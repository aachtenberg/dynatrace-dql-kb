"""Stop: the page gets its answer at once, even while a model call is still
out, and nothing from the stopped answer leaks into the chat afterwards.
Ollama calls stream, so Stop also closes the connection (the GPU stops).

    python -m unittest discover -s util/tests -v
"""

import http.client
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dqlagent import core, llm, store, web  # noqa: E402


class SlowModel(llm.ChatModel):
    """'slow ...' holds the call until the test opens the gate."""
    provider, label = "slow", "Slow"
    gate = threading.Event()
    entered = threading.Event()

    @classmethod
    def settings_fields(cls):
        return [{"key": "model", "label": "Model", "type": "text", "default": "slow-1"}]

    def chat(self, system, messages, tools, max_tokens=None):
        q = next(b["text"] for m in reversed(messages) if m["role"] == "user"
                 for b in m["content"] if b.get("type") == "text")
        if q.startswith("slow"):
            SlowModel.entered.set()
            SlowModel.gate.wait(20)
            return {"stop": "end_turn", "content": [{"type": "text", "text": "late answer"}]}
        return {"stop": "end_turn", "content": [{"type": "text", "text": f"fast answer to {q}"}]}


class StopTest(unittest.TestCase):
    def setUp(self):
        SlowModel.gate.clear()
        SlowModel.entered.clear()
        self.patches = [mock.patch.dict(llm.PROVIDERS, {"slow": SlowModel}),
                        mock.patch.dict(os.environ, {"LLM_PROVIDER": "slow", "DQL_CHAT_AUDIT": "off"}),
                        mock.patch.object(web.Handler, "log_message", lambda *a: None)]
        for p in self.patches:
            p.start()
        self.dir = tempfile.TemporaryDirectory()
        self.history = store.Store(os.path.join(self.dir.name, "chats.db"))
        self.server = web.ChatServer(web.Config("127.0.0.1", 0, "proxy"), self.history, ["slow"])
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        SlowModel.gate.set()
        self.server.shutdown()
        self.server.server_close()
        self.history.close()
        self.dir.cleanup()
        for p in reversed(self.patches):
            p.stop()

    def post(self, path, body):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.request("POST", path, json.dumps(body), {"x-amzn-oidc-identity": "ann", "X-DQL-Client": "1",
                                                      "Content-Type": "application/json"})
        return conn.getresponse()

    def chat(self, sid, text, into: list):
        resp = self.post("/api/chat", {"session": sid, "message": text})
        into.append(("status", resp.status))
        for chunk in resp.read().decode().split("\n\n"):
            kind = [line[6:].strip() for line in chunk.splitlines() if line.startswith("event:")]
            data = [json.loads(line[5:]) for line in chunk.splitlines() if line.startswith("data:")]
            if kind:
                into.append((kind[0], data[0] if data else None, time.time()))

    def test_stop_answers_at_once_and_the_late_reply_is_dropped(self):
        sid, first = "conv-stop-1", []
        t = threading.Thread(target=self.chat, args=(sid, "slow question", first))
        t.start()
        self.assertTrue(SlowModel.entered.wait(10), "the model call never started")
        stopped_at = time.time()
        self.assertEqual(self.post("/api/cancel", {"session": sid}).status, 200)
        t.join(5)
        self.assertFalse(t.is_alive(), "the stream did not end after Stop")
        kinds = [e[0] for e in first]
        self.assertEqual(kinds[-1], "cancelled", kinds)
        self.assertLess(first[-1][2] - stopped_at, 1.5, "Stop took too long")

        # The chat is free at once, and carries on from before the stopped question.
        second = []
        self.chat(sid, "fast question", second)
        self.assertEqual(second[0], ("status", 200))
        answer = next(e[1]["text"] for e in second if e[0] == "answer")
        self.assertEqual(answer, "fast answer to fast question")

        # The held call now returns; nothing of it may reach the chat.
        SlowModel.gate.set()
        time.sleep(0.6)
        sess = self.server.sessions[f"ann\x00{sid}"]
        texts = [b.get("text") for m in sess.agent.messages for b in m["content"] if b.get("type") == "text"]
        self.assertEqual(texts, ["fast question", "fast answer to fast question"])
        events = [(e["turn"], e["kind"], (e["data"] or {}).get("text")) for e in self.history.events("ann", sid)]
        self.assertEqual(events, [(1, "user", "slow question"), (1, "cancelled", None),
                                  (2, "user", "fast question"),
                                  (2, "answer", "fast answer to fast question")])
        self.assertEqual(self.history.load_state("ann", sid)["messages"], sess.agent.messages)


# -- Ollama streaming ----------------------------------------------------------

class FakeOllama(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        srv = self.server
        srv.bodies.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        try:
            for c in srv.script:
                self.wfile.write((json.dumps(c) + "\n").encode())
                self.wfile.flush()
                time.sleep(srv.delay)
            srv.completed = True
        except (BrokenPipeError, ConnectionResetError):
            srv.aborted = True


class OllamaStreamTest(unittest.TestCase):
    def serve(self, script, delay=0.0):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeOllama)
        srv.script, srv.delay, srv.bodies, srv.completed, srv.aborted = script, delay, [], False, False
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        p = mock.patch.dict(os.environ, {"OLLAMA_BASE_URL": f"http://127.0.0.1:{srv.server_address[1]}"})
        p.start()
        self.addCleanup(p.stop)
        return srv, llm.OllamaModel({"model": "m", "num_ctx": 4096})

    def test_a_streamed_reply_is_put_back_together(self):
        srv, model = self.serve([
            {"message": {"content": "Hel"}}, {"message": {"content": "lo"}},
            {"message": {"content": "", "tool_calls": [{"function": {"name": "run_dql",
                                                                      "arguments": {"query": "fetch logs"}}}]}},
            {"done": True, "done_reason": "stop"}])
        msgs = [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
        reply = model.chat("sys", msgs, [], cancel=threading.Event())
        self.assertTrue(srv.bodies[0]["stream"])
        self.assertEqual(reply["stop"], "tool_use")
        self.assertEqual(reply["content"][0], {"type": "text", "text": "Hello"})
        self.assertEqual(reply["content"][1]["name"], "run_dql")
        self.assertEqual(reply["content"][1]["input"], {"query": "fetch logs"})

    def test_cancel_stops_reading_and_closes_the_connection(self):
        srv, model = self.serve([{"message": {"content": "x"}}] * 400 + [{"done": True}], delay=0.02)
        cancel = threading.Event()
        threading.Timer(0.3, cancel.set).start()
        msgs = [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
        t0 = time.time()
        with self.assertRaises(llm.Interrupted):
            model.chat("sys", msgs, [], cancel=cancel)
        self.assertLess(time.time() - t0, 1.0)
        deadline = time.time() + 3
        while not srv.aborted and time.time() < deadline:
            time.sleep(0.05)
        self.assertTrue(srv.aborted, "the server kept writing: the connection was not closed")
        self.assertFalse(srv.completed)

    def test_the_agent_passes_its_stop_flag_only_to_models_that_take_it(self):
        seen = {}

        class Plain(llm.ChatModel):
            def chat(self, system, messages, tools, max_tokens=None):
                seen["plain"] = True
                return {"stop": "end_turn", "content": [{"type": "text", "text": "ok"}]}
        agent = core.Agent(Plain(), can_run=False, on_event=lambda kind, data: None)
        agent.cancel = threading.Event()
        self.assertEqual(agent.ask("q"), "ok")
        self.assertTrue(seen["plain"])


if __name__ == "__main__":
    unittest.main()
