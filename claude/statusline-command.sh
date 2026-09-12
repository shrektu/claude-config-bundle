#!/usr/bin/env bash
CTX_WARN_PCT=50
input=$(cat)
ctx=$(printf '%s' "$input" | python3 -c '
import json, sys
warn = int(sys.argv[1])
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
cw = d.get("context_window") or {}
cu = cw.get("current_usage") or {}
used = sum(cu.get(k) or 0 for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
size = cw.get("context_window_size") or 0
pct = cw.get("used_percentage")
cost = (d.get("cost") or {}).get("total_cost_usd")
model = (d.get("model") or {}).get("display_name") or ""
parts = []
if used:
    label = f"ctx {used // 1000}k/{size // 1000}k" if size else f"ctx {used // 1000}k"
    if pct is not None:
        label += f" {pct:.0f}%"
    color = "31" if pct is not None and pct >= warn else "33"
    parts.append(f"\033[{color}m{label}\033[0m")
if cost is not None:
    parts.append(f"${cost:.2f}")
if model:
    parts.append(model)
print("  ".join(parts))
' "$CTX_WARN_PCT")
printf '\033[01;32m%s@%s\033[0m:\033[01;34m%s\033[0m' "$(whoami)" "$(hostname -s)" "$(pwd)"
[ -n "$ctx" ] && printf '  %s' "$ctx"
