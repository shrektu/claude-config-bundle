#!/usr/bin/env python3
"""Regression matrix for bash-write-guard.py (the sibling file by default; pass another path as argv[1])."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HOOK = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parent / "bash-write-guard.py")
REASON_MARK = "write code with Edit/Write"
PYTHON_HEREDOC = "python3 - <<'EOF'\nfrom pathlib import Path\nPath(\"src/a.py\").write_text(\"x\")\nEOF"
DIRECTORY_SCAN_CAP = 2000
NO_COMMAND = json.dumps({"tool_name": "Bash", "tool_input": {}})
state = {"bad": 0, "checks": 0}


def run(payload, raw=None):
    done = subprocess.run([sys.executable, HOOK], input=raw if raw is not None else json.dumps(payload),
                          capture_output=True, text=True, timeout=10, check=False)
    return done.returncode, done.stdout.strip(), done.stderr.strip()


def expect(label, command, denied, cwd, raw=None):
    state["checks"] += 1
    payload = {"tool_name": "Bash", "cwd": str(cwd), "tool_input": {"command": command}}
    rc, out, err = run(payload, raw)
    ok = rc == 0 and not err and (('"deny"' in out and REASON_MARK in out) if denied else out == "")
    if not ok:
        state["bad"] += 1
        kind = "DENY MISS" if denied else "ALLOW FP "
        print(f"{kind} [{label}] {command!r} rc={rc} out={out[:200]!r} err={err[-200:]!r}")


def git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True,
                   env={**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null"})


def main():
    with tempfile.TemporaryDirectory() as base:
        repo = Path(base) / "repo"
        outside = Path(base) / "plain"
        for directory in (repo / "src", outside / "src"):
            directory.mkdir(parents=True)
        git(repo, "init", "-q")
        (repo / "src" / "a.py").write_text("x = 1\n")
        (repo / "src" / "a.c").write_text("int x;\n")
        scratch = Path(base) / "scratch"
        scratch.mkdir()
        (scratch / "x.py").write_text("x = 1\n")
        (scratch / "x.ts").write_text("export {};\n")
        code_dir, asset_dir, big_dir = (Path(base) / name for name in ("codedir", "assetdir", "bigdir"))
        (code_dir / "pkg").mkdir(parents=True)
        (code_dir / "pkg" / "m.py").write_text("x = 1\n")
        asset_dir.mkdir()
        (asset_dir / "logo.png").write_bytes(b"png")
        (asset_dir / "notes.md").write_text("notes\n")
        big_dir.mkdir()
        for index in range(DIRECTORY_SCAN_CAP + 1):
            (big_dir / f"f{index}.png").write_bytes(b"")

        deny = {
            "cp -r directory holding code": f"cp -r {code_dir} src/",
            "mv directory holding code": f"mv {code_dir} src/",
            "rsync directory holding code": f"rsync -a {code_dir}/ src/",
            "cp -r directory over the scan cap": f"cp -r {big_dir} src/",
            "redirect through $PWD": 'echo x > "$PWD/src/a.py"',
            "redirect through ${PWD}": "echo x > ${PWD}/src/a.py",
            "variable assigned earlier": 'F=src/a.py; cat > "$F"',
            "unresolved variable in a repo cwd": 'cat > "$OUT/x.py"',
            "cp to an unresolved code destination": f'cp {scratch}/x.py "$OUT/x.py"',
            "cp to an unresolved directory": f'cp {scratch}/x.py "$OUT/"',
            "mv to an unresolved directory": f"mv {scratch}/x.ts $OUT/",
            "cp -r code directory to an unresolved directory": f'cp -r {code_dir} "$OUT/"',
            "hyphenated heredoc delimiter then a write": "cat <<'A-B'\nx\nA-B\necho y > src/a.py",
            "heredoc cat": "cat > src/a.py <<'EOF'\nx = 1\nEOF",
            "append redirect": "echo x >> src/a.py",
            "clobber redirect": "echo x >| src/a.py",
            "redirect after args": "printf '%s' x > src/new.ts",
            "tee": "echo x | tee src/a.ts",
            "tee -a": "echo x | tee -a src/a.py",
            "sed -i": "sed -i 's/a/b/' src/a.py",
            "perl -pi": "perl -pi -e 's/a/b/' src/a.c",
            "python heredoc": PYTHON_HEREDOC,
            "python -c open": "python3 -c \"open('src/a.py','w').write('x')\"",
            "node -e": "node -e \"fs.writeFileSync('src/a.ts','x')\"",
            "cd then redirect": f"cd {repo} && cat > a.py <<EOF\nx\nEOF",
            "cp from outside": f"cp {scratch}/x.py src/a.py",
            "mv into dir": f"mv {scratch}/x.ts src/",
            "install": f"install -m644 {scratch}/x.py src/a.py",
            "rsync from outside": f"rsync -a {scratch}/x.py src/",
            "absolute redirect": f"echo x > {repo}/src/abs.py",
            "chained": "ls && echo x > src/b.py",
            "wrapped in env": "env FOO=1 tee src/c.py",
            "nested shell": "bash -c 'echo x > src/d.py'",
            "cd into subdir": "cd src && printf x > e.ts",
            "heredoc body mentions another file": "cat > src/f.py <<'EOF'\nprint('> notes.md')\nEOF",
        }
        for label, command in deny.items():
            expect(f"DENY {label}", command, True, repo)

        allow_outside = {
            "redirect": "cat > src/a.py <<'EOF'\nx = 1\nEOF",
            "sed -i": "sed -i 's/a/b/' src/a.py",
            "tee": "echo x | tee src/a.ts",
            "cp": f"cp {scratch}/x.py src/a.py",
            "unresolved variable": 'cat > "$OUT/x.py"',
            "cp to an unresolved code destination": f'cp {scratch}/x.py "$OUT/x.py"',
            "cp to an unresolved directory": f'cp {scratch}/x.py "$OUT/"',
            "cp -r directory holding code": f"cp -r {code_dir} src/",
        }
        for label, command in allow_outside.items():
            expect(f"ALLOW outside a work tree: {label}", command, False, outside)
        expect("ALLOW /tmp redirect from a repo cwd", "echo x > /tmp/bwg-scratch.py", False, repo)
        expect("ALLOW scratch dir redirect from a repo cwd", f"echo x > {scratch}/y.py", False, repo)

        allow = {
            "markdown": "echo hi > notes.md",
            "json": "echo '{}' > out.json",
            "txt": "echo hi > log.txt",
            "ruff format": "ruff format src/a.py",
            "prettier": "prettier --write src",
            "script output": "python3 script.py > out.txt",
            "cat": "cat src/a.py",
            "git diff patch": "git diff > x.patch",
            "git mv": "git mv src/a.py src/b.py",
            "mv within repo": "mv src/a.py src/b.py",
            "cp within repo": "cp src/a.py src/c.py",
            "cp to non-code": f"cp {scratch}/x.py src/a.py.bak",
            "read-only python": "python3 -c \"print(open('src/a.py').read())\"",
            "python without a path literal": "python3 -c \"open(name, 'w').write('x')\"",
            "python writes elsewhere": "python3 -c \"open('/tmp/x.txt', 'w').write('x')\"",
            "grep with arrow text": "grep -n '=>' src/a.py",
            "comparison in test": "[ 2 -gt 1 ] && echo ok",
            "stderr merge": "ls src 2>&1",
            "dev null": "echo x > /dev/null",
            "quoted angle bracket": "grep '>' src/a.py",
            "heredoc into non-code file": "cat > notes.md <<'EOF'\necho x > src/a.py\nEOF",
            "cd out of the repo": "cd /tmp && echo x > a.py",
            "cp -r directory without code": f"cp -r {asset_dir} src/",
            "mv directory without code": f"mv {asset_dir} src/",
            "unresolved variable with a non-code suffix": 'echo x > "$OUT/x.txt"',
            "cp to an unresolved non-code destination": f'cp {scratch}/x.py "$OUT/x.txt"',
            "cp of non-code files to an unresolved directory": f'cp {asset_dir}/logo.png "$OUT/"',
            "variable assigned to a non-code file": 'F=notes.md; cat > "$F"',
            "hyphen heredoc into a non-code file": "cat > notes.md <<'A-B'\necho x > src/a.py\nA-B",
            "dash heredoc into a non-code file": "cat > notes.md <<-END-X\n\techo x > src/a.py\n\tEND-X",
        }
        for label, command in allow.items():
            expect(f"ALLOW {label}", command, False, repo)

        expect("ALLOW malformed JSON", "", False, repo, raw="{nope")
        expect("ALLOW list payload", "", False, repo, raw="[]")
        expect("ALLOW missing command", "", False, repo, raw=NO_COMMAND)
        expect("ALLOW non-Bash payload", "", False, repo,
               raw=json.dumps({"tool_name": "Edit", "tool_input": {"command": "echo x > src/a.py"}}))
    print(f"bash-write-guard matrix: {state['checks']} checks, {state['bad']} failed")
    sys.exit(1 if state["bad"] else 0)


if __name__ == "__main__":
    main()
