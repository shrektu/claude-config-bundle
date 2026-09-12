#!/usr/bin/env python3
"""Regression matrix for read-guard.py (the sibling file by default; pass another path as argv[1])."""
import json, os, subprocess, sys, tempfile

hook = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "read-guard.py")


def run(payload_dict):
    p = subprocess.run(["python3", hook], input=json.dumps(payload_dict), capture_output=True, text=True, timeout=10)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def run_raw(raw):
    p = subprocess.run(["python3", hook], input=raw, capture_output=True, text=True, timeout=10)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def payload(path, tool_name="Read", offset=None, limit=None):
    tool_input = {"file_path": path}
    if offset is not None:
        tool_input["offset"] = offset
    if limit is not None:
        tool_input["limit"] = limit
    return {"tool_name": tool_name, "tool_input": tool_input}


bad = 0


def check_allow(name, payload_dict):
    global bad
    rc, out, err = run(payload_dict)
    ok = rc == 0 and out == "" and not err
    bad += not ok
    if not ok:
        print(f"ALLOW FP [{name}] -> rc={rc} out={out[:160]!r} err={err[-160:]!r}")


def check_deny(name, payload_dict, must_contain):
    global bad
    rc, out, err = run(payload_dict)
    ok = rc == 0 and '"deny"' in out and not err
    reason = ""
    if ok:
        reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
    if not ok:
        print(f"DENY MISS [{name}] -> rc={rc} out={out[:200]!r} err={err[-160:]!r}")
    else:
        for needle in must_contain:
            if needle not in reason:
                ok = False
                print(f"DENY MISSING SUBSTR [{name}] needle={needle!r} reason={reason[:300]!r}")
    bad += not ok


with tempfile.TemporaryDirectory() as tmp:
    small_path = os.path.join(tmp, "small.py")
    with open(small_path, "w") as f:
        f.write("print('hello world')\n")

    py_defs_lines = []
    n = 0
    while sum(len(l) + 1 for l in py_defs_lines) < 40 * 1024:
        py_defs_lines.append(f"def func_{n}(x, y):")
        py_defs_lines.append(f"    return x + y + {n}")
        if n % 5 == 0:
            py_defs_lines.append("class Helper:")
            py_defs_lines.append(f"    def method_{n}(self):")
            py_defs_lines.append("        pass")
        n += 1
    py_defs_content = "\n".join(py_defs_lines) + "\n"
    py_defs_path = os.path.join(tmp, "big_with_defs.py")
    with open(py_defs_path, "w") as f:
        f.write(py_defs_content)
    py_defs_line_count = len(py_defs_content.splitlines())

    filler_lines = []
    while sum(len(l) + 1 for l in filler_lines) < 40 * 1024:
        filler_lines.append("lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod")
    no_defs_content = "\n".join(filler_lines) + "\n"
    no_defs_path = os.path.join(tmp, "big_no_defs.txt")
    with open(no_defs_path, "w") as f:
        f.write(no_defs_content)

    png_path = os.path.join(tmp, "image.png")
    with open(png_path, "wb") as f:
        f.write(b"\x00\x01\x02" * 10000)

    missing_path = os.path.join(tmp, "does_not_exist.py")
    dir_path = os.path.join(tmp, "a_directory")
    os.mkdir(dir_path)

    check_allow("small text file", payload(small_path))
    check_deny("40KB python file with defs", payload(py_defs_path),
               ["def ", f"{py_defs_line_count} lines"])
    check_allow("same file with limit=100", payload(py_defs_path, limit=100))
    check_allow("same file with offset=1", payload(py_defs_path, offset=1))
    check_allow(".png with NUL bytes", payload(png_path))
    check_allow("missing path", payload(missing_path))
    check_allow("directory", payload(dir_path))
    check_deny("40KB file with no definitions (fallback)", payload(no_defs_path),
               ["1: lorem ipsum"])

    md_lines = []
    section = 0
    while sum(len(l) + 1 for l in md_lines) < 40 * 1024:
        md_lines.append(f"  ## Section {section}")
        md_lines.append("  Some body text describing this section in detail.")
        section += 1
    md_content = "\n".join(md_lines) + "\n"
    md_path = os.path.join(tmp, "indented_headings.md")
    with open(md_path, "w") as f:
        f.write(md_content)
    check_deny("40KB markdown with indented headings", payload(md_path), ["## Section 0", "## Section 1", "## Section 2"])

    big_path = os.path.join(tmp, "huge.txt")
    with open(big_path, "w") as f:
        chunk = "some plain text line without any definitions here\n"
        written = 0
        target = 3 * 1024 * 1024
        while written < target:
            f.write(chunk)
            written += len(chunk)
    check_deny("3MB file capped scan", payload(big_path), ["≥"])

# garbage / silent cases
garbage = [
    "", "not json", '{"tool_input":{"file_path":"x"}}',
    '{"tool_name":"Bash","tool_input":{"file_path":"x"}}',
    '{"tool_name":"Read","tool_input":{"file_path":123}}',
    '{"tool_name":"Read","tool_input":null}',
]
for raw in garbage:
    rc, out, err = run_raw(raw)
    ok = rc == 0 and out == "" and not err
    bad += not ok
    if not ok:
        print(f"garbage {raw[:60]!r} -> rc={rc} out={out[:60]!r} err={err[-160:]!r}")

total = 10 + len(garbage)
if bad:
    print(f"FAIL {total - bad}/{total}")
else:
    print(f"PASS {total}/{total}")
sys.exit(1 if bad else 0)
