#!/usr/bin/env python3
"""SessionStart(startup|clear) hook: records when this session began.

tdd-guard only accepts a red verify run that happened after this marker, so the marker must move
when a session really starts and never in the middle of one."""
import datetime
import json
import os
import re
import sys

LOG_DIR_ENV = "CLAUDE_VERIFY_LOG_DIR"
DEFAULT_LOG_DIR = os.path.join(os.path.expanduser("~"), ".cache", "claude-verify")
SESSIONS_DIR = "sessions"
MARKER_SUFFIX = ".json"
UNSAFE_ID = re.compile(r"[^A-Za-z0-9._-]")


def main():
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            return 0
        session_id = payload.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            return 0
        directory = os.path.join(os.environ.get(LOG_DIR_ENV) or DEFAULT_LOG_DIR, SESSIONS_DIR)
        os.makedirs(directory, exist_ok=True)
        marker = os.path.join(directory, UNSAFE_ID.sub("_", session_id) + MARKER_SUFFIX)
        started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with open(marker, "w", encoding="utf-8") as handle:
            json.dump({"session_id": session_id, "started_at": started_at}, handle)
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
