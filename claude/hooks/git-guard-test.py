#!/usr/bin/env python3
"""Regression matrix for git-guard.py (the sibling file by default; pass another path as argv[1])."""
import json, subprocess, os, time, sys
hook = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "git-guard.py")
deny = [
 "git reset --hard HEAD~1", "git checkout -- src/a.py", "git checkout main", "git checkout .", "git checkout -B feature/x",
 "git stash", "git stash pop", "git stash push -m x", "git stash -q pop", "git clean -fd", "git restore stats.py", "git restore -W -S f",
 "git push --force origin feature/x", "git push -f origin feature/x", "git push -fu origin feature/x",
 "cd /repo && git reset --hard", "git -C /repo reset --hard", "git -c core.pager=cat reset --hard",
 "sh -c 'git stash'", "bash -c \"cd /r && git clean -fdx\"", "eval git reset --hard", "git switch --discard-changes main",
 "git switch -f main", "make test; git checkout -- .", "/usr/bin/git restore .", "env GIT_DIR=x git reset --merge",
 "git log | head; git reset --hard", "command git stash drop", "sudo git clean -f",
 "sudo -n git reset --hard", "env -i git reset --hard", "command -- git reset --hard", "bash -lc \"git reset --hard\"",
 "sh -c \"git reset --hard; echo done\"", "(git reset --hard)", "( cd /r && git reset --hard )", "git switch --force-create feature/fix HEAD~1",
 "git switch -C feature/fix", "git clean -f -- -n", "git restore -- --staged", "git clean -fn --no-dry-run", "git restore --staged --no-staged file",
 "git push --force --force-with-lease origin feature/x", "timeout 30 git clean -fd", "git reset --hard > /dev/null 2>&1", "git reset --hard >/dev/null 2>&1",
 "echo `git reset --hard`", "echo \"`git stash`\"", "x=$(git reset --hard)", "echo \"$(git reset --hard)\"", "diff <(git diff) <(git reset --hard)",
 "git status\ngit reset --hard", "git switch -fc feature/x", "xargs -n1 git checkout --", "nohup git clean -fdx &", "git reset --soft HEAD~1 && git reset --hard",
 "git stash&&git status", "git clean -fd;git status", "true||git reset --hard", "git reset --hard|cat",
 "git status # inspect tree\ngit reset --hard", "git reset $(git rev-parse HEAD) --hard", "git push origin $(git branch --show-current) --force",
 "if true; then git reset --hard; fi", "for dir in .; do git -C \"$dir\" clean -fd; done", "while true; do git stash; done",
 "bash -o pipefail -c 'git reset --hard'", "bash -eo pipefail -c 'git reset --hard'", "bash -euo pipefail -c 'git reset --hard'", "bash -c -o pipefail 'git reset --hard'",
 "cat <<EOF\n$(git reset --hard)\nEOF", "cat <<EOF\n`git clean -fd`\nEOF",
 "echo \"<<EOF\"\ngit reset --hard", "git 2>/dev/null reset --hard", "git reset --hard # comment", "git reset --hard 2>&1 | tee log",
 "X=1 git reset --hard", "! git reset --hard", "{ git reset --hard; }", "git reset `git rev-parse HEAD` --hard", "echo hi; git reset --hard # done",
 "git commit -m \"x\" && git push -f", "cat <<'EOF' > f\nx\nEOF\ngit reset --hard", "bash -c 'git status; git reset --hard'",
 # round 3
 "bash -c 'echo ok\ngit reset --hard'", "bash -c \"echo ok\ngit reset --hard\"", "cat <<<\"$(git reset --hard)\"", "echo ok >\"$(git reset --hard; printf /dev/null)\"",
 "cat <<EOF\n'$(git reset --hard)'\nEOF", "cat <<EOF\n# $(git reset --hard)\nEOF", "bash -oc pipefail 'git reset --hard'", "bash -oec pipefail 'git reset --hard'",
 "bash -Oec extglob 'git reset --hard'", "eval 'echo ok\ngit reset --hard'", "cat 0<<EOF\n$(git clean -fd)\nEOF", "echo ok > $(git reset --hard)",
 "echo ok 2>\"$(git stash)\"", "sh -c 'x=1\ngit clean -fd'",
 # round 4
 "cat <<EOF\n`echo \\`git reset --hard\\``\nEOF", "echo \"unterminated; git reset --hard",
]
allow = [
 "git status --short", "git diff --stat", "git diff HEAD --stat", "git diff HEAD -- a.py", "git stash create", "git stash list", "git stash show -p",
 "git stash -q list", "git reset HEAD~1", "git reset --soft HEAD~1", "git reset -- file.py", "git reset -- --hard", "git reset --hard --soft HEAD~1",
 "git checkout -b feature/x", "git checkout -q -b feature/y origin/develop", "git checkout -bfeature/fix",
 "git switch -c feature/y", "git switch -cfeature/fix", "git switch feature/z", "git switch --no-force main", "git clean -n", "git clean --dry-run -d",
 "git clean --no-dry-run -n", "git restore --staged file.py", "git restore -S file.py", "git push --force-with-lease origin feature/x",
 "git push --force --no-force origin feature/x", "git push -u origin feature/x", "git push", "git commit -s -m 'Add thing'",
 "git commit -s -m \"Document cleanup; git clean -f; explain danger\"", "git rebase -i --autosquash origin/develop", "git commit --fixup=abc123",
 "echo 'git reset --hard'", "grep -rn 'git stash' docs/", "git log --oneline | head -5", "python3 -m pytest -q", "gitk", "digit reset --hard",
 "git branch -d feature/old", "git checkout --orphan gh-pages", "~/.claude/bin/verify -- pytest -q", "git -C /repo status && git -C /repo diff --stat",
 "git -c a=b -C /x stash list", "cat > notes.md <<'EOF'\nnever run git reset --hard here\nEOF\ngit status",
 "git log --format=%s | grep -c 'git clean'", "git config --get remote.origin.url", "bash script.sh", "sh -c 'ls; git status'",
 "git diff 2>&1 | head", "git stash list >> log.txt", "git stash list 2>/dev/null", "time git status", "git commit -m 'msg' \\\n  -s",
 "x=\"$(git status --short)\"", "echo \"price: $5 (git)\"", "SHA=$(~/.claude/bin/review-checkpoint save)", "echo `git rev-parse HEAD`",
 "git commit -m \"Fix `mean()` off-by-one\"", "diff <(git diff) <(git diff HEAD)", "git diff HEAD --numstat > /tmp/x",
 "git commit -m 'Document $(git reset --hard) recovery command'", "git commit -m 'run `git reset --hard` to recover'",
 "cat <<'EOF'\n$(git reset --hard)\nEOF", "cat <<EOF\ngit reset --hard\nEOF", "cat <<\"EOF\"\n`git stash`\nEOF", "cat <<-EOF\n\tgit clean -fd\n\tEOF\ngit status",
 "git status # then maybe git reset --hard", "git stash list 2>&1", "git log -1 --format=%H > /tmp/sha", "echo '# git reset --hard'",
 "if git diff --quiet; then echo clean; fi", "git tag -l | grep -q v1 || echo none", "git diff --stat $(git merge-base HEAD develop)",
 "case $x in a) git status;; esac", "git log --grep='reset --hard'", "git show HEAD:file.py > /tmp/old.py", "bash -o pipefail -c 'git status'",
 "bash -eo pipefail -c 'git status'", "printf '%s\\n' 'git reset --hard' > notes.txt", "git commit -m \"Revert 'git clean -fd' docs\"", "echo \"# git stash\" >> README.md",
 "git stash list | wc -l", "git status 2>&1 >/dev/null", "git diff --name-only $(git merge-base HEAD develop) -- src/",
 # round 3
 "cat 0<<'EOF'\ngit reset --hard\nEOF", "cat <<'EOF'\n'$(git reset --hard)'\nEOF", "git commit -m 'line1\nline2 git reset --hard'",
 "git commit -m \"line1\nline2: git clean -fd\"", "echo ok > \"$(git rev-parse --show-toplevel)/log\"", "cat <<<\"$(git status --short)\"",
 "bash -oc pipefail 'git status'", "cat 2<<-EOF\n\tgit stash\n\tEOF", "bash -c 'echo a\necho b'", "python3 -c 'print(\"git reset --hard\")'",
 "git log --format='%H%n%s' | head", "git diff > \"/tmp/out $(date +%s).diff\"",
]
garbage = ["not json", "null", "[]", "1", '{"tool_input":{"command":42}}', '{"tool_name":"Bash","tool_input":null}',
           '{"tool_name":"Edit","tool_input":{"command":"git reset --hard"}}', '{"tool_name":"Bash","tool_input":{"command":null}}']
stress = [json.dumps({"tool_name":"Bash","tool_input":{"command":"$(" * 300}}), json.dumps({"tool_name":"Bash","tool_input":{"command":"`" * 501}}),
          json.dumps({"tool_name":"Bash","tool_input":{"command":"cat <<EOF\n" + "x\n" * 5000}}),
          json.dumps({"tool_name":"Bash","tool_input":{"command":"a=(1 2 3); echo ${a[@]} 2>&1 <<< 'x' | grep 1"}}),
          json.dumps({"tool_name":"Bash","tool_input":{"command":("git status && " * 2000) + "true"}}),
          json.dumps({"tool_name":"Bash","tool_input":{"command":"echo " + "\"$(" * 50 + "x" + ")\"" * 50}}),
          json.dumps({"tool_name":"Bash","tool_input":{"command":"cat <<EOF\n" + "$(echo x)\n" * 3000 + "EOF"}}),
          json.dumps({"tool_name":"Bash","tool_input":{"command":"echo >" * 3000}})]
def run(cmd):
    p = subprocess.run(["python3", hook], input=json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}}), capture_output=True, text=True, timeout=10)
    return p.returncode, p.stdout.strip(), p.stderr.strip()
bad = 0
for c in deny:
    rc, out, err = run(c)
    ok = rc == 0 and '"deny"' in out and not err
    bad += not ok
    if not ok: print(f"DENY MISS  {c!r} -> rc={rc} {out[:80]} {err[-160:]}")
for c in allow:
    rc, out, err = run(c)
    ok = rc == 0 and out == "" and not err
    bad += not ok
    if not ok: print(f"ALLOW FP   {c!r} -> rc={rc} {out[:160]} {err[-160:]}")
for raw in garbage:
    p = subprocess.run(["python3", hook], input=raw, capture_output=True, text=True, timeout=20)
    ok = p.returncode == 0 and not p.stderr and p.stdout == ""
    bad += not ok
    if not ok: print(f"garbage {raw[:60]!r} -> rc={p.returncode} out={p.stdout.strip()[:60]!r} err={p.stderr[-160:]!r}")
for raw in stress:
    t0 = time.time()
    p = subprocess.run(["python3", hook], input=raw, capture_output=True, text=True, timeout=20)
    ok = p.returncode == 0 and not p.stderr and time.time() - t0 < 5
    bad += not ok
    if not ok: print(f"stress {raw[:60]!r} -> rc={p.returncode} {time.time()-t0:.1f}s err={p.stderr[-160:]!r}")
print(f"hook: {hook}\ndeny cases: {len(deny)}, allow cases: {len(allow)}, garbage: {len(garbage)}, stress: {len(stress)}, FAILURES: {bad}")
sys.exit(1 if bad else 0)
