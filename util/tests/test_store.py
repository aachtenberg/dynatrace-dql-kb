"""Chat history store (util/dqlagent/store.py). Standard library only:

    python -m unittest discover -s util/tests -v
"""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dqlagent import store  # noqa: E402


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.st = store.Store(os.path.join(self.dir.name, "sub", "chats.db"))

    def tearDown(self):
        self.st.close()
        self.dir.cleanup()

    def test_title_is_the_first_question_cut_at_a_word(self):
        self.assertEqual(store.title_from("  any  open\nproblems? "), "any open problems?")
        long = "word " * 40
        t = store.title_from(long)
        self.assertTrue(t.endswith("…"))
        self.assertLessEqual(len(t), store.TITLE_CHARS + 1)

    def test_turns_events_and_listing(self):
        self.assertEqual(self.st.begin_turn("ann", "c1", "Any open problems?"), 1)
        self.st.add_event("ann", "c1", 1, "thinking", {})            # a moment, not kept
        self.st.add_event("ann", "c1", 1, "query", {"query": "fetch dt.davis.problems"})
        self.st.add_event("ann", "c1", 1, "answer", {"text": "None."})
        self.assertEqual(self.st.begin_turn("ann", "c1", "And yesterday?"), 2)

        convs = self.st.conversations("ann")
        self.assertEqual([(c["id"], c["title"], c["turns"]) for c in convs],
                         [("c1", "Any open problems?", 2)])
        kinds = [(e["turn"], e["kind"]) for e in self.st.events("ann", "c1")]
        self.assertEqual(kinds, [(1, "user"), (1, "query"), (1, "answer"), (2, "user")])
        self.assertEqual(self.st.events("ann", "c1")[0]["data"], {"text": "Any open problems?"})

    def test_newest_first(self):
        self.st.begin_turn("ann", "old", "first")
        time.sleep(0.01)
        self.st.begin_turn("ann", "new", "second")
        self.assertEqual([c["id"] for c in self.st.conversations("ann")], ["new", "old"])

    def test_state_round_trip_writes_each_result_once(self):
        self.st.begin_turn("ann", "c1", "q")
        r1 = ("r1", {"query": "fetch logs", "records": [{"a": 1}]})
        r2 = ("r2", {"query": "fetch spans", "records": [{"b": 2}]})
        msgs = [{"role": "user", "content": [{"type": "text", "text": "q"}]}]
        self.st.save_state("ann", "c1", {"messages": msgs, "results": [r1], "result_seq": 1})
        # r1 changed in memory must not be rewritten: results are immutable once stored
        self.st.save_state("ann", "c1", {"messages": msgs, "results": [
            ("r1", {"query": "changed", "records": []}), r2], "result_seq": 2})
        state = self.st.load_state("ann", "c1")
        self.assertEqual(state["messages"], msgs)
        self.assertEqual(state["result_seq"], 2)
        self.assertEqual(state["results"], [r1, r2])
        # A result the agent dropped is dropped from disk too.
        self.st.save_state("ann", "c1", {"messages": msgs, "results": [r2], "result_seq": 2})
        self.assertEqual([rid for rid, _ in self.st.load_state("ann", "c1")["results"]], ["r2"])

    def test_results_keep_numeric_order(self):
        self.st.begin_turn("ann", "c1", "q")
        results = [(f"r{i}", {"query": str(i), "records": []}) for i in (9, 10, 11)]
        self.st.save_state("ann", "c1", {"messages": [], "results": results, "result_seq": 11})
        self.assertEqual([rid for rid, _ in self.st.load_state("ann", "c1")["results"]],
                         ["r9", "r10", "r11"])

    def test_users_cannot_see_each_other(self):
        self.st.begin_turn("ann", "c1", "mine")
        self.assertEqual(self.st.conversations("bob"), [])
        self.assertIsNone(self.st.get("bob", "c1"))
        self.assertEqual(self.st.events("bob", "c1"), [])
        self.assertIsNone(self.st.load_state("bob", "c1"))
        self.assertFalse(self.st.rename("bob", "c1", "stolen"))
        self.assertFalse(self.st.delete("bob", "c1"))
        self.assertEqual(self.st.get("ann", "c1")["title"], "mine")
        # The same id under another user is another conversation.
        self.st.begin_turn("bob", "c1", "his")
        self.assertEqual(self.st.get("ann", "c1")["title"], "mine")
        self.assertEqual(self.st.get("bob", "c1")["title"], "his")

    def test_rename_and_delete(self):
        self.st.begin_turn("ann", "c1", "q")
        self.st.save_state("ann", "c1", {"messages": [], "results": [("r1", {"query": "x", "records": []})]})
        self.assertFalse(self.st.rename("ann", "c1", "   "))
        self.assertTrue(self.st.rename("ann", "c1", "  CPU   check "))
        self.assertEqual(self.st.get("ann", "c1")["title"], "CPU check")
        self.assertTrue(self.st.delete("ann", "c1"))
        self.assertIsNone(self.st.get("ann", "c1"))
        self.assertEqual(self.st.events("ann", "c1"), [])
        self.assertEqual(self.st.db.execute("SELECT COUNT(*) FROM results").fetchone()[0], 0)

    def test_prefs(self):
        self.assertEqual(self.st.prefs("ann"), {})
        self.st.save_prefs("ann", {"provider": "bedrock", "max_turns": 12})
        self.st.save_prefs("ann", {"provider": "bedrock", "max_turns": 14})
        self.assertEqual(self.st.prefs("ann"), {"provider": "bedrock", "max_turns": 14})
        self.assertEqual(self.st.prefs("bob"), {})

    def test_retention_prunes_old_conversations(self):
        self.st.begin_turn("ann", "old", "q")
        self.st.begin_turn("ann", "new", "q")
        self.st.db.execute("UPDATE conversations SET updated = ? WHERE id = 'old'",
                           (time.time() - 91 * 86400,))
        self.st.db.commit()
        self.st._pruned = 0
        self.st.prune()
        self.assertEqual([c["id"] for c in self.st.conversations("ann")], ["new"])
        self.assertEqual(self.st.events("ann", "old"), [])

    def test_survives_reopen(self):
        self.st.begin_turn("ann", "c1", "q")
        path = self.st.path
        self.st.close()
        self.st = store.Store(path)
        self.assertEqual(self.st.conversations("ann")[0]["id"], "c1")


class OpenFromEnvTest(unittest.TestCase):
    def test_off(self):
        with mock.patch.dict(os.environ, {"DQL_CHAT_HISTORY": "0"}):
            self.assertIsNone(store.open_from_env())

    def test_path_and_retention(self):
        with tempfile.TemporaryDirectory() as d:
            env = {"DQL_CHAT_HISTORY": "1", "DQL_CHAT_DB": os.path.join(d, "x.db"),
                   "DQL_CHAT_RETENTION_DAYS": "7"}
            with mock.patch.dict(os.environ, env):
                st = store.open_from_env()
            self.assertEqual((st.path, st.retention_days), (env["DQL_CHAT_DB"], 7))
            st.close()

    def test_unwritable_path_turns_history_off(self):
        with tempfile.NamedTemporaryFile() as f:          # a file where a directory is needed
            with mock.patch.dict(os.environ, {"DQL_CHAT_DB": os.path.join(f.name, "x.db")}), \
                 mock.patch("sys.stderr"):
                self.assertIsNone(store.open_from_env())


if __name__ == "__main__":
    unittest.main()
