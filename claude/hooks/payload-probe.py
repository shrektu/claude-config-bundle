#!/usr/bin/env python3
"""Diagnostic hook: records which session-identifying fields a hook payload actually carries.

Register it temporarily next to a guard you are debugging, run the case, read the log, unregister it.
It never writes to stdout, so it can never allow or deny a tool call; `tool_input` is deliberately not
recorded, so the log holds no command lines or file contents."""
import json
import os
import sys
from datetime import datetime

LOG = os.environ.get("PROBE_LOG", os.path.expanduser("~/.cache/claude-probe/payload.log"))
RECORDED = ("hook_event_name", "tool_name", "agent_type", "subagent_type", "agent_id", "session_id",
            "caller_session_id", "transcript_path", "agent_transcript_path", "cwd", "permission_mode",
            "served_call", "effort")


def main():
    try:
        payload = json.load(sys.stdin)
        if not isinstance(payload, dict):
            payload = {"__not_an_object__": type(payload).__name__}
        record = {"at": datetime.now().isoformat(timespec="seconds"),
                  "keys": sorted(k for k in payload if k != "tool_input")}
        for key in RECORDED:
            if key in payload:
                record[key] = payload[key]
        os.makedirs(os.path.dirname(LOG) or ".", exist_ok=True)
        with open(LOG, "a") as fh:
            fh.write(json.dumps(record, default=str) + "\n")
    except Exception:
        return


if __name__ == "__main__":
    main()
