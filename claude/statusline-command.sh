#!/usr/bin/env bash
CTX_WARN_PCT=50
input=$(cat)
branch=$(git -C "$PWD" symbolic-ref --short -q HEAD 2>/dev/null || git -C "$PWD" rev-parse --short HEAD 2>/dev/null)
printf '%s' "$input" | python3 -c '
import json, os, sys

BLUE = "122;162;247"
PURPLE = "187;154;247"
YELLOW = "224;175;104"
RED = "247;118;142"
GREEN = "158;206;106"
CYAN = "125;207;255"
GREY = "86;95;137"


def paint(rgb: str, text: str, bold: bool = False) -> str:
    """Wrap text in a 24-bit foreground colour escape."""
    weight = "1;" if bold else ""
    return f"\033[{weight}38;2;{rgb}m{text}\033[0m"


warn = int(sys.argv[1])
branch = sys.argv[2]
try:
    d = json.load(sys.stdin)
except Exception:
    d = {}
cwd = os.getcwd()
home = os.path.expanduser("~")
shown_dir = "~" + cwd[len(home):] if cwd.startswith(home) else cwd
parts = [paint(BLUE, f" {shown_dir}", bold=True)]
if branch:
    parts.append(paint(PURPLE, f" {branch}"))
cw = d.get("context_window") or {}
cu = cw.get("current_usage") or {}
used = sum(cu.get(k) or 0 for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
size = cw.get("context_window_size") or 0
pct = cw.get("used_percentage")
if used:
    label = f"ctx {used // 1000}k/{size // 1000}k" if size else f"ctx {used // 1000}k"
    if pct is not None:
        label += f" {pct:.0f}%"
    parts.append(paint(RED if pct is not None and pct >= warn else YELLOW, label))
cost = (d.get("cost") or {}).get("total_cost_usd")
if cost is not None:
    parts.append(paint(GREEN, f"${cost:.2f}"))
model = (d.get("model") or {}).get("display_name") or ""
if model:
    parts.append(paint(CYAN, model))
print(paint(GREY, " │ ").join(parts), end="")
' "$CTX_WARN_PCT" "$branch"
