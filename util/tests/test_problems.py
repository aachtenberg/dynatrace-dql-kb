"""The chat's open-problems hint: the fixed query's summary and the endpoint.

    python -m unittest discover -s util/tests -v
"""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dqlagent import core, web  # noqa: E402

RECORDS = [
    {"event.start": "2026-09-28T13:49:22.845000000Z", "display_id": "P-2609158",
     "event.name": "Host or monitoring unavailable", "event.category": "AVAILABILITY",
     "affected_entity_ids": ["HOST-D28B622F0D748DCC"]},
    {"event.start": "2026-09-29T00:28:00.000000000Z", "display_id": "P-2609173",
     "event.name": "Backoff event", "event.category": "ERROR",
     "affected_entity_ids": ["CLOUD_APPLICATION-E5476E922805A03C", "K8S_POD-0123456789ABCDEF"]},
    {"event.start": "2026-09-29T00:28:00.000000000Z", "display_id": "P-2609173",   # an update of the same problem
     "event.name": "Backoff event", "event.category": "ERROR", "affected_entity_ids": []},
    {"event.start": "2026-09-24T18:39:00.000000000Z", "display_id": "P-26094",
     "event.name": "No pod ready", "event.category": "ERROR", "affected_entity_ids": None},
]


def grail(records):
    return lambda q: ({"records": records, "metadata": {"grail": {"scannedBytes": 19088384}}}, "")


class OpenProblemsTest(unittest.TestCase):
    def test_summary_newest_first_one_per_problem(self):
        with mock.patch.object(core, "_query_grail", grail(RECORDS)):
            d = core.open_problems(top=2)
        self.assertEqual(d["open"], 3)
        self.assertEqual(d["by_category"], {"AVAILABILITY": 1, "ERROR": 2})
        self.assertEqual([p["id"] for p in d["items"]], ["P-2609173", "P-2609158"])
        self.assertEqual(d["items"][0]["affected"], 2)
        self.assertAlmostEqual(d["items"][0]["start"], 1790641680.0, places=0)
        self.assertEqual(d["scanned"], "18.2 MB")
        self.assertIn('event.status == "ACTIVE"', d["query"])

    def test_none_open(self):
        with mock.patch.object(core, "_query_grail", grail([])):
            self.assertEqual(core.open_problems()["open"], 0)

    def test_grail_error_is_summarised(self):
        with mock.patch.object(core, "_query_grail", lambda q: (None, "PARSE_ERROR: bad")):
            self.assertIn("error", core.open_problems())

    def test_the_query_passes_the_agents_own_checks(self):
        self.assertEqual(core.lint_dql(core.OPEN_PROBLEMS_DQL, set()), [])


class ProblemsEndpointTest(unittest.TestCase):
    def server(self, can_run=True, env=None):
        with mock.patch.dict(os.environ, {"DQL_CHAT_AUDIT": "off", **(env or {})}), \
             mock.patch.object(core, "DocIndex", lambda: None):
            srv = web.ChatServer(web.Config("127.0.0.1", 0, "none"), None, ["bedrock"])
        srv.server_close()                 # only the method is under test
        srv.can_run = can_run
        return srv

    def test_cached_for_a_minute(self):
        srv, calls = self.server(), []

        def count(q):
            calls.append(q)
            return grail(RECORDS)(q)
        with mock.patch.object(core, "_query_grail", count):
            first = srv.open_problems("ann")
            second = srv.open_problems("bob")
        self.assertEqual((first["enabled"], first["open"], second["open"]), (True, 3, 3))
        self.assertEqual(len(calls), 1)
        self.assertEqual(first["checked"], second["checked"])

    def test_errors_are_not_cached(self):
        srv, calls = self.server(), []

        def fail(q):
            calls.append(q)
            return None, "Grail is down"
        with mock.patch.object(core, "_query_grail", fail):
            srv.open_problems("ann")
            d = srv.open_problems("ann")
        self.assertEqual(len(calls), 2)
        self.assertIn("error", d)

    def test_off_without_a_tenant_or_when_disabled(self):
        self.assertEqual(self.server(can_run=False).open_problems("ann"), {"enabled": False})
        self.assertEqual(self.server(env={"DQL_CHAT_PROBLEMS": "0"}).open_problems("ann"), {"enabled": False})


if __name__ == "__main__":
    unittest.main()
