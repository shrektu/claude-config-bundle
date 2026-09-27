#!/usr/bin/env bash
usage() {
  cat <<'USAGE'
usage: review-checkpoint-test.sh [path/to/review-checkpoint]   (default: the sibling script)
Runs review-checkpoint save/stat/diff against throwaway git repositories and checks that re-reviews are
incremental for new files, the real index is never touched, ignored files stay out, old stash-create
checkpoints still work and temporary files are removed. Touches nothing outside its temporary directory.
USAGE
}
set -uo pipefail
case ${1:-} in -h|--help) usage; exit 0 ;; esac
RC=${1:-$(cd "$(dirname "$0")" && pwd)/review-checkpoint}
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
export TMPDIR=$WORK/tmp
mkdir -p "$TMPDIR"
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
export GIT_AUTHOR_NAME=tester GIT_AUTHOR_EMAIL=tester@example.com
export GIT_COMMITTER_NAME=tester GIT_COMMITTER_EMAIL=tester@example.com
FAILURES=0
CHECKS=0

fail() { echo "FAIL $1"; FAILURES=$((FAILURES + 1)); }
check() { CHECKS=$((CHECKS + 1)); if [ "$2" != 0 ]; then fail "$1"; fi; }
has() { CHECKS=$((CHECKS + 1)); grep -qF -- "$2" <<<"$1" || fail "$3"; }
lacks() { CHECKS=$((CHECKS + 1)); if grep -qF -- "$2" <<<"$1"; then fail "$3"; fi; }
numbered() { for i in 01 02 03 04 05 06 07 08 09 10; do echo "$1$i"; done; }
new_repo() {
  mkdir -p "$1" && git -C "$1" init -q && printf 'base\n' > "$1/tracked.txt"
  git -C "$1" add tracked.txt && git -C "$1" commit -q -m one
}
index_state() { echo "$(git ls-files -s)|$(git diff --cached --quiet; echo $?)|$(cksum < "$(git rev-parse --git-path index)")"; }

R=$WORK/repo
new_repo "$R"
cd "$R" || exit 1
printf '*.log\n' > .gitignore
numbered "ORIGINAL_LINE_" > new_module.py
printf 'IGNORED_SENTINEL\n' > debug.log
printf 'staged change\n' >> tracked.txt
git add tracked.txt
before=$(index_state)
sha=$("$RC" save)
check "save exits 0" $?
check "save prints a commit" "$(git cat-file -t "$sha" 2>/dev/null | grep -qx commit; echo $?)"
check "checkpoint parent is HEAD" "$([ "$(git rev-parse "$sha^" 2>/dev/null)" = "$(git rev-parse HEAD)" ]; echo $?)"
check "checkpoint holds the untracked file" "$(git cat-file -e "$sha:new_module.py" 2>/dev/null; echo $?)"
check "checkpoint holds the staged change" "$(git show "$sha:tracked.txt" 2>/dev/null | grep -qx 'staged change'; echo $?)"
check "checkpoint leaves ignored files out" "$(git cat-file -e "$sha:debug.log" 2>/dev/null; [ $? != 0 ]; echo $?)"
printf 'LATER_HUNK\n' >> new_module.py
printf 'MORE_IGNORED\n' >> debug.log
out=$("$RC" diff "$sha")
check "diff exits 0" $?
has "$out" "+LATER_HUNK" "diff misses the later hunk of the new file"
lacks "$out" "ORIGINAL_LINE_01" "diff re-sends the whole new file"
lacks "$out" "debug.log" "diff shows an ignored file"
lacks "$out" "untracked" "diff still lists untracked files separately"
stat=$("$RC" stat "$sha")
check "stat exits 0" $?
has "$stat" "new_module.py" "stat does not name the changed new file"
lacks "$stat" "tracked.txt" "stat names a file unchanged since the checkpoint"
lacks "$stat" "debug.log" "stat shows an ignored file"
check "real index unchanged by save/stat/diff" "$([ "$before" = "$(index_state)" ]; echo $?)"

printf 'second tracked edit\n' >> tracked.txt
old=$(git stash create)
check "git stash create made a checkpoint" "$([ -n "$old" ]; echo $?)"
printf 'third tracked edit\n' >> tracked.txt
out=$("$RC" diff "$old")
check "old stash-create checkpoint diffs" $?
has "$out" "+third tracked edit" "old checkpoint diff misses the new edit"
lacks "$out" "+second tracked edit" "old checkpoint diff repeats the checkpointed edit"

"$RC" diff 0000000000000000000000000000000000000000 >/dev/null 2>&1
check "unknown checkpoint exits 2" "$([ $? = 2 ]; echo $?)"

E=$WORK/empty
mkdir -p "$E" && git -C "$E" init -q
cd "$E" || exit 1
sha=$("$RC" save)
check "save in a repo without commits or index" $?
check "no-HEAD checkpoint has no parent" "$(git rev-parse -q --verify "$sha^" >/dev/null; [ $? != 0 ]; echo $?)"
numbered "FRESH_LINE_" > fresh.txt
sha=$("$RC" save)
check "second save without commits" $?
printf 'FRESH_HUNK\n' >> fresh.txt
out=$("$RC" diff "$sha")
check "diff without commits" $?
has "$out" "+FRESH_HUNK" "no-commit diff misses the later hunk"
lacks "$out" "FRESH_LINE_01" "no-commit diff re-sends the whole file"
check "no index file created in a repo without one" "$([ ! -e "$(git rev-parse --git-path index)" ]; echo $?)"

L=$WORK/locked
new_repo "$L"
cd "$L" || exit 1
good=$("$RC" save)
printf 'unreviewed\n' >> tracked.txt
printf 'secret\n' > locked.txt
chmod 000 locked.txt
if [ "$(id -u)" != 0 ]; then
  err=$("$RC" save 2>&1 >/dev/null)
  check "save fails when git add -A fails" "$([ $? != 0 ]; echo $?)"
  has "$err" "locked.txt" "save does not print git's error"
  err=$("$RC" diff "$good" 2>&1 >/dev/null)
  check "diff fails when git add -A fails" "$([ $? != 0 ]; echo $?)"
  has "$err" "locked.txt" "diff does not print git's error"
fi
chmod 644 locked.txt

check "temporary files removed" "$([ -z "$(ls -A "$TMPDIR")" ]; echo $?)"

echo "checks: $CHECKS, FAILURES: $FAILURES"
if [ "$FAILURES" != 0 ]; then echo FAIL; exit 1; fi
echo "PASS $CHECKS/$CHECKS"
