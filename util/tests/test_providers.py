"""Picking a provider in the browser chat: the server's list, switching and
remembering per provider, and which Ollama models the picker offers.

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


class One(llm.ChatModel):
    provider, label = "one", "Provider one"

    @classmethod
    def settings_fields(cls):
        return [{"key": "model", "label": "Model", "type": "text", "default": "one-a"}]

    def chat(self, system, messages, tools, max_tokens=None):
        return {"stop": "end_turn", "content": [{"type": "text", "text": f"{self.provider}:{self.settings['model']}"}]}


class Two(One):
    provider, label = "two", "Provider two"

    @classmethod
    def settings_fields(cls):
        return [{"key": "model", "label": "Model", "type": "text", "default": "two-a"},
                {"key": "num_ctx", "label": "Context", "type": "number", "default": 8192, "min": 4096, "max": 65536}]


class ChatProvidersTest(unittest.TestCase):
    def test_auto_adds_every_provider_set_up_in_env(self):
        env = {"LLM_PROVIDER": "bedrock", "DQL_CHAT_PROVIDERS": "auto",
               "AZURE_OPENAI_ENDPOINT": "https://x.openai.azure.com", "AZURE_OPENAI_API_KEY": "k"}
        with mock.patch.dict(os.environ, env), mock.patch.object(llm, "ollama_up", return_value=True):
            self.assertEqual(web.chat_providers(), ["bedrock", "azure_openai", "ollama"])

    def test_auto_adds_a_local_ollama_that_answers(self):
        with mock.patch.dict(os.environ, {"LLM_PROVIDER": "bedrock", "DQL_CHAT_PROVIDERS": "auto",
                                          "AZURE_OPENAI_API_KEY": "", "OPENAI_API_KEY": "",
                                          "ANTHROPIC_API_KEY": "", "VLLM_BASE_URL": "", "PRIVATE_BASE_URL": ""}):
            with mock.patch.object(llm, "ollama_up", return_value=True):
                self.assertEqual(web.chat_providers(), ["bedrock", "ollama"])
            with mock.patch.object(llm, "ollama_up", return_value=False):
                self.assertEqual(web.chat_providers(), ["bedrock"])

    def test_explicit_list_keeps_the_servers_own_first(self):
        with mock.patch.dict(os.environ, {"LLM_PROVIDER": "bedrock", "DQL_CHAT_PROVIDERS": "ollama, bedrock"}):
            self.assertEqual(web.chat_providers(), ["bedrock", "ollama"])

    def test_unknown_provider_stops_the_server(self):
        with mock.patch.dict(os.environ, {"LLM_PROVIDER": "bedrock", "DQL_CHAT_PROVIDERS": "ollama,skynet"}):
            with self.assertRaises(SystemExit):
                web.chat_providers()


class OllamaOptionsTest(unittest.TestCase):
    def test_only_tool_models_are_pickable_and_embeddings_are_hidden(self):
        tags = {"models": [{"name": n, "details": {"parameter_size": s}} for n, s in
                           [("llava:7b", "7B"), ("gpt-oss:20b", "20.9B"), ("nomic-embed-text:latest", "137M"),
                            ("gemma4:12b", "11.9B")]]}
        caps = {"llava:7b": ["completion", "vision"], "gpt-oss:20b": ["completion", "tools", "thinking"],
                "nomic-embed-text:latest": ["embedding"], "gemma4:12b": ["completion", "tools"]}

        def fake(url, body, headers, what, timeout=300, method=None):
            if url.endswith("/api/tags"):
                return tags
            return {"capabilities": caps[body["model"]],
                    "model_info": {"gptoss.context_length": 131072}}

        with mock.patch.object(llm, "_http_json", fake):
            opts = llm.OllamaModel({"model": "gpt-oss:20b"}).model_options()
        self.assertEqual([(o["value"], o.get("disabled", False)) for o in opts],
                         [("gemma4:12b", False), ("gpt-oss:20b", False), ("llava:7b", True)])
        self.assertEqual(opts[1]["detail"], "20.9B · 128k context")
        self.assertEqual(opts[2]["why"], "cannot call tools")

    def test_old_servers_without_capabilities_list_everything(self):
        def fake(url, body, headers, what, timeout=300, method=None):
            return {"models": [{"name": "qwen3:8b"}]} if url.endswith("/api/tags") else {}
        with mock.patch.object(llm, "_http_json", fake):
            opts = llm.OllamaModel({"model": "qwen3:8b"}).model_options()
        self.assertEqual([o["value"] for o in opts], ["qwen3:8b"])
        self.assertNotIn("disabled", opts[0])


class SwitchProviderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.patches = [mock.patch.dict(llm.PROVIDERS, {"one": One, "two": Two}),
                       mock.patch.dict(os.environ, {"LLM_PROVIDER": "one", "DQL_CHAT_AUDIT": "off"}),
                       mock.patch.object(web.Handler, "log_message", lambda *a: None)]
        for p in cls.patches:
            p.start()
        cls.index = core.DocIndex()

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

    def start(self):
        self.history = store.Store(self.db)
        with mock.patch.object(core, "DocIndex", lambda: self.index):
            self.server = web.ChatServer(web.Config("127.0.0.1", 0, "proxy"), self.history, ["one", "two"])
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.history.close()

    def call(self, path, body=None):
        req = urllib.request.Request(self.base + path, method="POST" if body is not None else "GET",
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"x-amzn-oidc-identity": "ann", "X-DQL-Client": "1",
                                              "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def config(self, sid="conv-000001"):
        status, raw = self.call(f"/api/config?session={sid}")
        self.assertEqual(status, 200, raw)
        cfg = json.loads(raw)
        cfg["model"] = next(f["value"] for f in cfg["fields"] if f["key"] == "model")
        return cfg

    def settings(self, values, sid="conv-000001"):
        status, raw = self.call("/api/settings", {"session": sid, "values": values})
        return status, json.loads(raw)

    def test_config_lists_the_servers_providers(self):
        cfg = self.config()
        self.assertEqual(cfg["provider"], "one")
        self.assertEqual([p["value"] for p in cfg["providers"]], ["one", "two"])
        self.assertEqual(cfg["provider_label"], "Provider one")

    def test_switch_remember_and_survive_a_restart(self):
        status, cfg = self.settings({"provider": "two"})
        self.assertEqual(status, 200, cfg)
        self.assertTrue(cfg["reset"])
        self.assertEqual(cfg["provider"], "two")
        self.assertIn("num_ctx", [f["key"] for f in cfg["fields"]])      # the new provider's fields
        self.assertEqual(self.settings({"model": "two-b"})[0], 200)
        self.assertEqual(self.settings({"provider": "one", "model": "one-b"})[0], 200)
        self.assertEqual(self.config()["model"], "one-b")
        # Back to two: its model is remembered.
        status, cfg = self.settings({"provider": "two"})
        self.assertEqual(next(f["value"] for f in cfg["fields"] if f["key"] == "model"), "two-b")
        self.stop()
        self.start()
        cfg = self.config("conv-000002")           # a new chat after a restart
        self.assertEqual((cfg["provider"], cfg["model"]), ("two", "two-b"))

    def test_the_chat_answers_with_the_picked_provider(self):
        self.settings({"provider": "two"})
        status, raw = self.call("/api/chat", {"session": "conv-000003", "message": "hi"})
        self.assertEqual(status, 200)
        self.assertIn('"two:two-a"', raw)

    def test_a_provider_the_server_does_not_offer_is_refused(self):
        status, body = self.settings({"provider": "ollama"})
        self.assertEqual(status, 400)
        self.assertIn("not offered", body["error"])
        self.assertEqual(self.call("/api/models?session=conv-000001&provider=ollama")[0], 400)
        self.assertEqual(self.call("/api/models?session=conv-000001&provider=two")[0], 200)


if __name__ == "__main__":
    unittest.main()


class ResponsesApiTest(unittest.TestCase):
    """openai and azure_openai use the Responses API; reasoning and item ids round-trip."""

    ENV = {"AZURE_OPENAI_ENDPOINT": "https://res.openai.azure.com/", "AZURE_OPENAI_API_KEY": "k",
           "AZURE_OPENAI_DEPLOYMENT": "gpt-5", "OPENAI_API": ""}
    REASONING = {"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "enc"}

    def test_a_tool_call_then_an_answer(self):
        replies = [
            {"status": "completed", "output": [
                self.REASONING,
                {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "dql_run",
                 "arguments": '{"query": "fetch logs"}'}]},
            {"status": "completed", "output": [
                {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Done."}]}]},
        ]
        sent = []

        def fake(url, body, headers, what, timeout=300, method=None):
            sent.append((url, body, headers))
            return replies[len(sent) - 1]

        tools = [{"name": "dql_run", "description": "Run DQL", "schema": {"type": "object"}}]
        with mock.patch.dict(os.environ, self.ENV), mock.patch.object(llm, "_http_json", fake):
            model = llm.make_model("azure_openai")
            messages = [{"role": "user", "content": [{"type": "text", "text": "errors?"}]}]
            first = model.chat("be brief", messages, tools)
            messages.append({"role": "assistant", "content": first["content"]})
            messages.append({"role": "user", "content": [
                {"type": "tool_result", "id": "call_1", "name": "dql_run", "text": "bad", "is_error": True}]})
            second = model.chat("be brief", messages, tools)

        self.assertEqual(first["stop"], "tool_use")
        self.assertEqual(first["content"][1]["input"], {"query": "fetch logs"})
        self.assertEqual(second, {"content": [{"type": "text", "text": "Done."}], "stop": "end"})
        url, body, headers = sent[1]
        self.assertEqual(url, "https://res.openai.azure.com/openai/v1/responses")
        self.assertEqual(headers, {"api-key": "k"})
        self.assertEqual(body["instructions"], "be brief")
        self.assertFalse(body["store"])
        self.assertEqual(body["tools"][0], {"type": "function", "name": "dql_run",
                                            "description": "Run DQL", "parameters": {"type": "object"}})
        self.assertEqual(body["input"], [
            {"role": "user", "content": "errors?"},
            self.REASONING,
            {"type": "function_call", "call_id": "call_1", "name": "dql_run",
             "arguments": '{"query": "fetch logs"}', "id": "fc_1"},
            {"type": "function_call_output", "call_id": "call_1", "output": "ERROR: bad"}])

    def test_reasoning_without_a_tool_call_is_not_sent_back(self):
        with mock.patch.dict(os.environ, self.ENV), \
                mock.patch.object(llm, "_http_json", return_value={"output": []}) as http:
            llm.make_model("azure_openai").chat("", [
                {"role": "user", "content": [{"type": "text", "text": "hi"}]},
                {"role": "assistant", "content": [{"type": "raw", "provider": "azure_openai", "data": self.REASONING},
                                                  {"type": "text", "text": "hello"}]},
                {"role": "user", "content": [{"type": "text", "text": "again"}]}], [])
        self.assertEqual(http.call_args.args[1]["input"], [
            {"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"},
            {"role": "user", "content": "again"}])

    def test_cut_off_and_refused(self):
        cases = [({"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}, "output": []},
                  "max_tokens"),
                 ({"output": [{"type": "message", "content": [{"type": "refusal", "refusal": "No."}]}]}, "refusal")]
        for reply, stop in cases:
            with mock.patch.dict(os.environ, self.ENV), mock.patch.object(llm, "_http_json", return_value=reply):
                self.assertEqual(llm.make_model("azure_openai").chat("", [], [])["stop"], stop)

    def test_the_picker_offers_the_azure_deployment(self):
        with mock.patch.dict(os.environ, self.ENV):
            self.assertEqual(llm.make_model("azure_openai").model_options(),
                             [{"value": "gpt-5", "label": "gpt-5", "detail": "deployment"}])

    def test_openai_api_chat_keeps_chat_completions(self):
        with mock.patch.dict(os.environ, {**self.ENV, "OPENAI_API": "chat",
                                          "AZURE_OPENAI_API_VERSION": "2024-10-21"}), \
                mock.patch.object(llm, "_http_json", return_value={"choices": [{"message": {"content": "hi"}}]}) as http:
            llm.make_model("azure_openai").chat("", [], [])
        self.assertEqual(http.call_args.args[0], "https://res.openai.azure.com/openai/deployments/gpt-5"
                                                 "/chat/completions?api-version=2024-10-21")
        with mock.patch.dict(os.environ, {"VLLM_BASE_URL": "http://gpu:8000", "OPENAI_API": ""}):
            self.assertEqual(llm.make_model("vllm").api, "chat")
