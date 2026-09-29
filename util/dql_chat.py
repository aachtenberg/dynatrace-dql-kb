"""
dql_chat.py — The DQL agent as a chat in your browser, with charts and graphs
drawn from the queries it runs.

Standard library only; the page's graph library is vendored. Runs on your
machine by default, or in a container (util/dql_chat.Dockerfile).

Usage:
    ./util/dql_chat.sh                  # opens http://127.0.0.1:8750/?t=<token>
    ./util/dql_chat.sh --port 9000 --no-browser
    ./util/dql_chat.sh --no-history     # chats in memory only
    ./util/dql_chat.sh --help

Setup, settings, security and AWS deployment: util/dql_chat.md
"""

import argparse
import os
import sys

import dqlagent  # noqa: F401  (puts the repo root on sys.path)
from dqlagent import web


def main() -> int:
    ap = argparse.ArgumentParser(description="DQL agent as a browser chat.")
    ap.add_argument("--host", help="address to listen on (DQL_CHAT_HOST, default 127.0.0.1)")
    ap.add_argument("--port", type=int, help="port (DQL_CHAT_PORT, default 8750)")
    ap.add_argument("--auth", choices=["token", "proxy", "none"],
                    help="access check (DQL_CHAT_AUTH, default token)")
    ap.add_argument("--no-browser", action="store_true", help="do not open a browser")
    hist = ap.add_mutually_exclusive_group()
    hist.add_argument("--no-history", action="store_true",
                      help="keep chats in memory only (DQL_CHAT_HISTORY=0)")
    hist.add_argument("--history-db", metavar="PATH",
                      help="SQLite file for chat history (DQL_CHAT_DB, "
                           "default ~/.local/share/dql-chat/chats.db)")
    args = ap.parse_args()
    if args.no_history:
        os.environ["DQL_CHAT_HISTORY"] = "0"
    elif args.history_db:
        os.environ["DQL_CHAT_HISTORY"] = "1"
        os.environ["DQL_CHAT_DB"] = args.history_db
    return web.serve(args.host, args.port, args.auth, open_browser=not args.no_browser)


if __name__ == "__main__":
    sys.exit(main())
