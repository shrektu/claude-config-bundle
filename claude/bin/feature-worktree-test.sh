#!/usr/bin/env bash
usage() {
  cat <<'USAGE'
usage: feature-worktree-test.sh [path/to/feature-worktree]   (default: the sibling script)
Runs feature-worktree new/done/list against throwaway repositories with a bare origin and checks the base
choice, the refusals, that landed work is removed and that unlanded or dirty work is never removed.
Touches nothing outside its temporary directory.
USAGE
}
set -uo pipefail
case ${1:-} in -h|--help) usage; exit 0 ;; esac
FW=${1:-$(cd "$(dirname "$0")" && pwd)/feature-worktree}
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
export TMPDIR=$WORK/tmp
mkdir -p "$TMPDIR"
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1
export GIT_AUTHOR_NAME=tester GIT_AUTHOR_EMAIL=tester@example.com
export GIT_COMMITTER_NAME=tester GIT_COMMITTER_EMAIL=tester@example.com
FAILURES=0
CHECKS=0
EXIT_USAGE=64
EXIT_REFUSED=2
EXIT_NOT_DONE=1

fail() { echo "FAIL $1"; FAILURES=$((FAILURES + 1)); }
check() { CHECKS=$((CHECKS + 1)); if [ "$2" != 0 ]; then fail "$1"; fi; }
expect_rc() { CHECKS=$((CHECKS + 1)); [ "$2" = "$3" ] || fail "$1: exit $2, expected $3"; }
has() { CHECKS=$((CHECKS + 1)); grep -qF -- "$2" <<<"$1" || fail "$3"; }
exists() { CHECKS=$((CHECKS + 1)); [ -e "$1" ] || fail "missing $1"; }
gone() { CHECKS=$((CHECKS + 1)); [ ! -e "$1" ] || fail "still present $1"; }
has_branch() { git -C "$1" show-ref --verify --quiet "refs/heads/$2"; }
lacks_branch() { ! has_branch "$1" "$2"; }

new_repo() {
  local dir
  dir=$(mktemp -d "$WORK/case.XXXXXX")
  git init -q --bare -b main "$dir/origin.git"
  git init -q -b main "$dir/repo"
  printf 'base\n' > "$dir/repo/tracked.txt"
  git -C "$dir/repo" add tracked.txt
  git -C "$dir/repo" commit -q -m one
  git -C "$dir/repo" remote add origin "$dir/origin.git"
  git -C "$dir/repo" push -q origin main
  git -C "$dir/repo" remote set-head origin main
  echo "$dir/repo"
}
wt_path() { echo "$(dirname "$1")/$(basename "$1").worktrees/$2"; }
commit_in() {
  printf '%s\n' "$3" > "$1/$2"
  git -C "$1" add "$2"
  git -C "$1" commit -q -m "change $2"
}

if [ ! -x "$FW" ]; then
  fail "feature-worktree missing or not executable: $FW"
  echo "feature-worktree-test: FAILURES: $FAILURES"
  exit 1
fi

REPO=$(new_repo)
git -C "$REPO" checkout -q -b develop
commit_in "$REPO" dev.txt dev
git -C "$REPO" push -q origin develop
git -C "$REPO" checkout -q -b local-only
OUT=$("$FW" new "$REPO" feature/a 2>"$WORK/err"); RC=$?
expect_rc "new from origin/HEAD" "$RC" 0
WT=$(wt_path "$REPO" feature-a)
check "stdout is the path only" "$([ "$OUT" = "$WT" ]; echo $?)"
exists "$WT/tracked.txt"
gone "$WT/dev.txt"
check "branch has no upstream" "$(git -C "$REPO" rev-parse --abbrev-ref feature/a@{upstream} >/dev/null 2>&1; [ $? -ne 0 ]; echo $?)"
check "featureBase stored" "$([ "$(git -C "$REPO" config branch.feature/a.featureBase)" = origin/main ]; echo $?)"
check "worktree is on the branch" "$([ "$(git -C "$WT" branch --show-current)" = feature/a ]; echo $?)"
check "main checkout untouched" "$([ "$(git -C "$REPO" branch --show-current)" = local-only ]; echo $?)"

"$FW" new "$REPO" feature/a >/dev/null 2>&1; expect_rc "existing path" "$?" "$EXIT_REFUSED"
git -C "$REPO" branch feature/b
"$FW" new "$REPO" feature/b >/dev/null 2>&1; expect_rc "existing branch" "$?" "$EXIT_REFUSED"
gone "$(wt_path "$REPO" feature-b)"
"$FW" new "$REPO" topic/x >/dev/null 2>&1; expect_rc "bad prefix" "$?" "$EXIT_REFUSED"
gone "$(wt_path "$REPO" topic-x)"

"$FW" new "$REPO" bugfix/c develop >/dev/null 2>&1; expect_rc "new explicit base" "$?" 0
exists "$(wt_path "$REPO" bugfix-c)/dev.txt"
check "explicit base stored" "$([ "$(git -C "$REPO" config branch.bugfix/c.featureBase)" = develop ]; echo $?)"

REPO=$(new_repo)
git -C "$REPO" remote remove origin
git -C "$REPO" checkout -q -b hotfix-base
commit_in "$REPO" hot.txt hot
"$FW" new "$REPO" hotfix/d >/dev/null 2>&1; expect_rc "new without origin/HEAD" "$?" 0
exists "$(wt_path "$REPO" hotfix-d)/hot.txt"
check "current branch stored" "$([ "$(git -C "$REPO" config branch.hotfix/d.featureBase)" = hotfix-base ]; echo $?)"

"$FW" >/dev/null 2>&1; expect_rc "no args" "$?" "$EXIT_USAGE"
"$FW" bogus "$REPO" >/dev/null 2>&1; expect_rc "unknown subcommand" "$?" "$EXIT_USAGE"
"$FW" new "$REPO" >/dev/null 2>&1; expect_rc "new without branch" "$?" "$EXIT_USAGE"
"$FW" done "$REPO" >/dev/null 2>&1; expect_rc "done without branch" "$?" "$EXIT_USAGE"

REPO=$(new_repo)
"$FW" new "$REPO" feature/m >/dev/null 2>&1
WT=$(wt_path "$REPO" feature-m)
commit_in "$WT" m.txt m
"$FW" done "$REPO" feature/m >/dev/null 2>&1; expect_rc "done unmerged" "$?" "$EXIT_NOT_DONE"
exists "$WT"
check "unmerged branch kept" "$(has_branch "$REPO" feature/m; echo $?)"
LISTED=$("$FW" list "$REPO" 2>&1); expect_rc "list" "$?" 0
has "$LISTED" "$WT" "list shows the worktree"
git -C "$REPO" merge -q feature/m
git -C "$REPO" push -q origin main
"$FW" done "$REPO" feature/m >/dev/null 2>&1; expect_rc "done after merge" "$?" 0
gone "$WT"
check "merged branch deleted" "$(lacks_branch "$REPO" feature/m; echo $?)"
check "featureBase unset" "$(git -C "$REPO" config branch.feature/m.featureBase >/dev/null 2>&1; [ $? -ne 0 ]; echo $?)"

REPO=$(new_repo)
"$FW" new "$REPO" feature/s >/dev/null 2>&1
WT=$(wt_path "$REPO" feature-s)
commit_in "$WT" s.txt s
git -C "$WT" push -q origin feature/s
git -C "$REPO" merge -q --squash feature/s
git -C "$REPO" commit -q -m squashed
git -C "$REPO" push -q origin main
git -C "$REPO" push -q origin --delete feature/s
git -C "$REPO" fetch -q origin
"$FW" done "$REPO" feature/s >/dev/null 2>&1; expect_rc "done squash-merged" "$?" 0
gone "$WT"
check "squashed branch deleted" "$(lacks_branch "$REPO" feature/s; echo $?)"

REPO=$(new_repo)
"$FW" new "$REPO" feature/f >/dev/null 2>&1
WT=$(wt_path "$REPO" feature-f)
commit_in "$WT" f.txt f
git -C "$WT" push -q origin feature/f
OTHER=$(dirname "$REPO")/other
git clone -q "$(dirname "$REPO")/origin.git" "$OTHER"
git -C "$OTHER" merge -q origin/feature/f
git -C "$OTHER" push -q origin HEAD:main
git -C "$OTHER" push -q origin --delete feature/f
"$FW" done "$REPO" feature/f >/dev/null 2>&1; expect_rc "done after remote merge, no manual fetch" "$?" 0
gone "$WT"
check "remotely merged branch deleted" "$(lacks_branch "$REPO" feature/f; echo $?)"

REPO=$(new_repo)
"$FW" new "$REPO" feature/h >/dev/null 2>&1
WT=$(wt_path "$REPO" feature-h)
commit_in "$WT" h.txt h
git -C "$REPO" merge -q feature/h
git -C "$REPO" update-ref refs/remotes/origin/main main
git -C "$REPO" remote set-url origin "$WORK/missing.git"
ERR=$("$FW" done "$REPO" feature/h 2>&1 >/dev/null); expect_rc "done with failing fetch" "$?" 0
has "$ERR" "fetch" "failing fetch is warned about"
gone "$WT"

REPO=$(new_repo)
"$FW" new "$REPO" feature/g >/dev/null 2>&1
WT=$(wt_path "$REPO" feature-g)
commit_in "$WT" g.txt g
"$FW" done "$REPO" feature/g >/dev/null 2>&1; expect_rc "done never pushed, content missing" "$?" "$EXIT_NOT_DONE"
git -C "$WT" push -q origin feature/g
git -C "$REPO" push -q origin --delete feature/g
"$FW" done "$REPO" feature/g >/dev/null 2>&1; expect_rc "done upstream gone, content missing" "$?" "$EXIT_NOT_DONE"
exists "$WT/g.txt"
check "unlanded branch kept" "$(has_branch "$REPO" feature/g; echo $?)"

REPO=$(new_repo)
"$FW" new "$REPO" feature/dirty >/dev/null 2>&1
WT=$(wt_path "$REPO" feature-dirty)
git -C "$REPO" merge -q feature/dirty
printf 'uncommitted\n' >> "$WT/tracked.txt"
"$FW" done "$REPO" feature/dirty >/dev/null 2>&1; expect_rc "done dirty worktree" "$?" "$EXIT_NOT_DONE"
exists "$WT"
check "dirty changes kept" "$(grep -q uncommitted "$WT/tracked.txt"; echo $?)"
check "dirty branch kept" "$(has_branch "$REPO" feature/dirty; echo $?)"

REPO=$(new_repo)
git -C "$REPO" branch feature/nobase
"$FW" done "$REPO" feature/nobase >/dev/null 2>&1; expect_rc "done without featureBase" "$?" "$EXIT_NOT_DONE"
check "branch without featureBase kept" "$(has_branch "$REPO" feature/nobase; echo $?)"

echo "feature-worktree-test: checks: $CHECKS, FAILURES: $FAILURES"
[ "$FAILURES" = 0 ]
