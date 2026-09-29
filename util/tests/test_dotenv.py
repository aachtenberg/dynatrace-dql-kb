"""The .env loader in dt_fetch.py, which every script shares.

    python -m unittest discover -s util/tests -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import dt_fetch  # noqa: E402


class DotenvTest(unittest.TestCase):
    def load(self, text: str) -> dict:
        with tempfile.TemporaryDirectory() as d:
            Path(d, ".env").write_text(text, encoding="utf-8")
            keys = [line.split("=", 1)[0].strip() for line in text.splitlines()
                    if "=" in line and not line.strip().startswith("#")]
            clean = {k: v for k, v in os.environ.items() if k not in keys}
            with mock.patch.object(dt_fetch, "REPO_ROOT", Path(d)), \
                 mock.patch.dict(os.environ, clean, clear=True):
                dt_fetch._load_dotenv()
                return {k: os.environ.get(k) for k in keys}

    def test_inline_comments_are_dropped(self):
        got = self.load("DQL_CHAT_HISTORY=0                  # keep chats in memory only\n"
                        "PRIVATE_API_KEY=          # only if that server requires a bearer token\n"
                        "OLLAMA_BASE_URL=http://192.168.0.10:11434\t# another machine\n")
        self.assertEqual(got, {"DQL_CHAT_HISTORY": "0", "PRIVATE_API_KEY": "",
                               "OLLAMA_BASE_URL": "http://192.168.0.10:11434"})

    def test_quotes_keep_what_is_inside(self):
        got = self.load('A="x # not a comment"  # but this is\nB=\'y\'\nC=dt0s16.AB#CD\n')
        self.assertEqual(got, {"A": "x # not a comment", "B": "y", "C": "dt0s16.AB#CD"})

    def test_the_real_environment_wins(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, ".env").write_text("DQL_TEST_WINS=file\n", encoding="utf-8")
            with mock.patch.object(dt_fetch, "REPO_ROOT", Path(d)), \
                 mock.patch.dict(os.environ, {"DQL_TEST_WINS": "env"}):
                dt_fetch._load_dotenv()
                self.assertEqual(os.environ["DQL_TEST_WINS"], "env")


if __name__ == "__main__":
    unittest.main()
