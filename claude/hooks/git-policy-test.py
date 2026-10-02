#!/usr/bin/env python3
"""Regression matrix for git-policy.py (the sibling file by default; pass another path as argv[1])."""
import json, os, shutil, subprocess, sys, tempfile, time

hook = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "git-policy.py")
ENV = {**os.environ,
       "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
       "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
       "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com",
       "GIT_TERMINAL_PROMPT": "0"}
ROCKET = "\U0001f680"
CHECK = "✅"
BRANCH_REPOS = {"master": "master", "dev": "dev", "develop": "develop", "testx": "test/x", "release1": "release/1"}
UPSTREAM_REPOS = {"work_upstream": "main", "work_upstream_ok": "feature/x"}
WORK_REPOS = {"bugfix": "bugfix/x", "hotfix": "hotfix/x", "work_matching": "feature/x", "work_pushcfg": "feature/x",
              **{key: "feature/x" for key in UPSTREAM_REPOS}}
MESSAGE_FILES = {"msg_ok": "Add parser module\n", "msg_bad": "Updated stuff\n",
                 "msg_two": "Add parser module\nsecond line\n", "msg_missing": None}


def git(cwd, *args, check=True):
    done = subprocess.run(("git", *args), cwd=cwd, capture_output=True, text=True, env=ENV, timeout=30)
    if check and done.returncode != 0:
        raise SystemExit(f"fixture setup failed: git {' '.join(args)} in {cwd}\n{done.stdout}\n{done.stderr}")
    return done


def write(path, text):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def init_repo(path, branch):
    os.makedirs(path, exist_ok=True)
    git(path, "init", "-q", "-b", branch)
    write(os.path.join(path, "f.txt"), "base\n")
    git(path, "add", "f.txt")
    git(path, "commit", "-q", "-m", "base")
    return path


def conflicting_rebase(path, branch, extra_args=()):
    """Leaves <path> mid-rebase of <branch> (conflict), so the state dir carries head-name."""
    init_repo(path, branch)
    git(path, "switch", "-q", "-c", "other")
    write(os.path.join(path, "f.txt"), "other\n")
    git(path, "commit", "-q", "-am", "other change")
    git(path, "switch", "-q", branch)
    write(os.path.join(path, "f.txt"), "mine\n")
    git(path, "commit", "-q", "-am", "my change")
    git(path, "rebase", *extra_args, "other", check=False)
    return path


def build(base):
    dirs = {}
    dirs["main"] = init_repo(os.path.join(base, "main_repo"), "main")
    git(dirs["main"], "branch", "feature/old")
    git(dirs["main"], "branch", "release")
    git(dirs["main"], "config", "alias.publish", "push")
    git(dirs["main"], "config", "alias.lg", "log --oneline")
    git(dirs["main"], "config", "alias.shellhack", "!git push origin main")
    git(dirs["main"], "config", "alias.indirect", "publish")
    git(dirs["main"], "config", "alias.pub", "-c color.ui=false push")
    git(dirs["main"], "config", "alias.st", "-c color.ui=false status")
    dirs["work"] = init_repo(os.path.join(base, "work_repo"), "feature/x")
    git(dirs["work"], "branch", "feature/old")
    git(dirs["work"], "config", "alias.publish", "push")
    dirs["detached"] = init_repo(os.path.join(base, "detached_repo"), "main")
    git(dirs["detached"], "switch", "-q", "--detach", "HEAD")
    dirs["rebase_work"] = conflicting_rebase(os.path.join(base, "rebase_work"), "feature/x")
    dirs["rebase_main"] = conflicting_rebase(os.path.join(base, "rebase_main"), "main")
    dirs["apply_main"] = conflicting_rebase(os.path.join(base, "apply_main"), "main", ("--apply",))
    apply_state = os.path.join(dirs["apply_main"], ".git", "rebase-apply")
    if not os.path.exists(os.path.join(apply_state, "head-name")):
        shutil.rmtree(os.path.join(dirs["apply_main"], ".git", "rebase-merge"), ignore_errors=True)
        os.makedirs(apply_state, exist_ok=True)
        write(os.path.join(apply_state, "head-name"), "refs/heads/main\n")
    dirs["wt_release"] = os.path.join(base, "wt_release")
    git(dirs["main"], "worktree", "add", "-q", dirs["wt_release"], "release")
    dirs["wt_feat"] = os.path.join(base, "wt_feat")
    git(dirs["main"], "worktree", "add", "-q", "-b", "feature/wt", dirs["wt_feat"], "main")
    dirs["plain"] = os.path.join(base, "plain")
    os.makedirs(dirs["plain"], exist_ok=True)
    for key, branch in BRANCH_REPOS.items():
        dirs[key] = init_repo(os.path.join(base, f"{key}_repo"), branch)
    for key, branch in WORK_REPOS.items():
        dirs[key] = init_repo(os.path.join(base, f"{key}_repo"), branch)
    git(dirs["work_matching"], "config", "push.default", "matching")
    git(dirs["work_pushcfg"], "config", "remote.origin.push", "refs/heads/*:refs/heads/*")
    for key, remote_branch in UPSTREAM_REPOS.items():
        bare = os.path.join(base, f"{key}.git")
        git(base, "init", "-q", "--bare", bare)
        git(dirs[key], "remote", "add", "origin", bare)
        git(dirs[key], "push", "-q", "origin", f"feature/x:{remote_branch}")
        git(dirs[key], "branch", f"--set-upstream-to=origin/{remote_branch}")
        git(dirs[key], "config", "push.default", "upstream")
    for key, text in MESSAGE_FILES.items():
        dirs[key] = os.path.join(base, f"{key}.txt")
        if text is not None:
            write(dirs[key], text)
    return dirs


def cases(d):
    ask = [
        ("main", 'git commit -s -m "Add a thing."'),
        ("main", "git merge feature/old"),
        ("main", "git rebase feature/old"),
        ("main", "git cherry-pick abc1234"),
        ("main", "git revert HEAD"),
        ("main", "git am /tmp/patch.mbox"),
        ("main", "git reset --soft HEAD~1"),
        ("main", "git reset --mixed HEAD~1"),
        ("main", "git reset HEAD~1"),
        ("main", "git push origin main"),
        ("main", "git push"),
        ("main", "git push --dry-run --no-dry-run origin main"),
        ("main", "git push -n --no-dry-run origin main"),
        ("main", "git tag v1.0"),
        ("main", "git tag -d v1.0"),
        ("main", 'git tag -a v1.0 -m "release"'),
        ("main", "git tag -f v1.0"),
        ("main", "git branch -M renamed"),
        ("main", "git symbolic-ref HEAD refs/heads/feature/old"),
        ("main", "git filter-branch --tree-filter true HEAD"),
        ("main", "git filter-repo --path src"),
        ("main", "git replace abc1234 def5678"),
        ("main", 'git notes add -m "note" HEAD'),
        ("main", "git notes remove HEAD"),
        ("main", 'git notes append -m "more" HEAD'),
        ("main", 'bash -c \'git commit -s -m "Add a thing."\''),
        ("main", "sudo git reset HEAD~1"),
        ("main", 'git status && git commit -s -m "Add a thing."'),
        ("plain", f'cd {d["main"]} && git commit -s -m "Add a thing."'),
        ("plain", f'git -C {d["main"]} commit -s -m "Add a thing."'),
        ("work", f"git -C {d['main']} push origin main"),
        ("work", f'cd {d["main"]} && git reset --keep HEAD~1'),
        ("wt_release", 'git commit -s -m "Add a thing."'),
        ("wt_release", "git reset --soft HEAD~1"),
        ("detached", 'git commit -s -m "Add a thing."'),
        ("detached", "git reset HEAD~1"),
        ("rebase_main", "git rebase --continue"),
        ("rebase_main", 'git commit -s -m "Resolve the conflict."'),
        ("rebase_main", "git commit --amend --no-edit -s"),
        ("apply_main", "git rebase --continue"),
        ("apply_main", 'git commit -s -m "Resolve the conflict."'),
        ("main", "git pull"),
        ("main", "git pull --ff-only origin main"),
        ("main", "git pull --rebase"),
        ("plain", f"git --git-dir={d['main']}/.git push origin main"),
        ("plain", f"git --git-dir {d['main']}/.git commit -s -m \"Add a thing.\""),
        ("plain", f"git --work-tree={d['main']} --git-dir={d['main']}/.git reset HEAD~1"),
        ("work", f"git --git-dir={d['main']}/.git pull"),
        ("main", "git -c alias.publish=push publish origin main"),
        ("main", "git -c alias.nuke='reset --soft HEAD~1' nuke"),
        ("main", "git -calias.publish=push publish origin main"),
        ("main", "git publish origin main"),
        ("main", "git indirect origin main"),
        ("main", f"(cd {d['plain']} && pwd); git push origin main"),
        ("main", f"(cd {d['work']} && git status); git commit -s -m \"Add a thing.\""),
        ("plain", f"{{ cd {d['main']}; git push origin main; }}"),
        ("work", f"(cd {d['main']} && git commit -s -m \"Add a thing.\")"),
        ("plain",f'git --git-dir={d["main"]}/.git --work-tree={d["work"]} commit -s -m "Add a thing."'),
        ("work", f'git --work-tree={d["work"]} --git-dir={d["main"]}/.git push origin main'),
        ("main", f'git --work-tree={d["work"]} commit -s -m "Add a thing."'),
        ("main", "git -c alias.publish='-c color.ui=false push' publish origin main"),
        ("main", "git pub origin main"),
        ("work", f'(cd {d["main"]} && echo "$(git push origin main)")'),
        ("work", f'(cd {d["main"]} && echo "$(git commit -s -m \"Add a thing.\")")'),
        ("work", f'(cd {d["main"]}; case x in x) git push origin main;; esac)'),
        ("work", f'case x in x) (cd {d["main"]} && git push origin main);; esac'),
        ("work", f'(cd {d["main"]}; case x in x) echo skip;; *) git push origin main;; esac)'),
        ("main", "git pull --dry-run --no-dry-run"),
        ("main", f'cat >"$(git push origin main)"; (cd {d["work"]} && echo "$(git status)")'),
        ("main", f'(cd {d["work"]} && echo case); git push origin main'),
        ("main", 'git tag "esac"'),
        ("main", f'(cd {d["main"]} && cat <<EOF\n$(git push origin main)\nEOF\n)'),
        ("work", f'(cd {d["main"]} && cat <<EOF\n$(git push origin main)\nEOF\n)'),
        ("work", f'cat >"$(git -C {d["main"]} push origin main)"'),
        ("main", f'cat <<EOF\n$(cd {d["work"]})\n$(git push origin main)\nEOF'),
        ("main", f'(cd {d["main"]}; if true; then case x in x) git push origin main;; esac; fi)'),
        ("work", f'(cd {d["main"]}; if true; then case x in x) git push origin main;; esac; fi)'),
        ("work", f'(cd {d["main"]}; while true; do case x in x) git push origin main;; esac; done)'),
        ("main", "git tag __redir_0__"),
        ("main", "git tag __subst_0__"),
        ("main", 'git commit -s -m "Add parser module"'),
        ("master", 'git commit -s -m "Add parser module"'),
        ("dev", 'git commit -s -m "Add parser module"'),
        ("develop", 'git commit -s -m "Add parser module"'),
        ("testx", 'git commit -s -m "Add parser module"'),
        ("release1", 'git commit -s -m "Add parser module"'),
        ("detached", 'git commit -s -m "Add parser module"'),
        ("main", "git merge feature/x"),
        ("work", "git push origin HEAD:main"),
        ("work", "git push origin feature/x:main"),
        ("work", "git push origin +feature/x:refs/heads/develop"),
        ("work", "git push origin :main"),
        ("work", "git push --all"),
        ("work", "git push --mirror"),
        ("work", "git push --tags"),
        ("work", "git push --follow-tags"),
        ("work", "git push origin refs/tags/v1"),
        ("work", "git push origin tag v1"),
        ("work", "git push origin --delete develop"),
        ("work", "git push origin feature/x:"),
        ("work_matching", "git push"),
        ("work_pushcfg", "git push"),
        ("work_pushcfg", "git push origin"),
        ("work", "git branch -D main"),
        ("work", "git branch -m develop old"),
        ("work", "git branch -m renamed"),
        ("work", "git branch -f main HEAD~1"),
        ("work", "git branch -d feature/old main"),
        ("work", "git update-ref refs/heads/main HEAD"),
        ("work", "git update-ref -d refs/heads/master"),
        ("work", "git update-ref refs/heads/tmp HEAD"),
        ("rebase_main", "git rebase main"),
        ("work", "git update-ref --stdin"),
        ("work", "git --config-env=push.default=PUSHDEF push"),
        ("work", "git --config-env push.default=PUSHDEF push origin feature/x"),
        ("work", "git symbolic-ref refs/heads/main refs/heads/feature/x"),
        ("work", "git symbolic-ref -d refs/heads/main"),
        ("work_upstream", "git push"),
        ("work_upstream", "git push origin"),
        ("work", "git -c push.default=matching push"),
        ("work", "git -c remote.origin.push=refs/heads/*:refs/heads/* push"),
        ("main", 'git commit -s -m "Add parser module" && git push origin HEAD:main'),
        ("work", "gh pr merge 12 --squash"),
        ("plain", f"cd {d['work']} && gh pr merge --auto 3"),
        ("work", "gh -R org/repo pr merge 3"),
        ("work", 'bash -c "gh pr merge 3"'),
        ("work", "sudo gh pr merge 3"),
        ("work", f"(cd {d['plain']} && gh pr merge 3)"),
    ]
    deny = [
        ("main", "git commit --amend"),
        ("work", 'git commit -m "Add a thing."'),
        ("work", 'git commit -am "Add a thing."'),
        ("work", 'git commit -s -m "Add a thing." -m "And a body."'),
        ("work", 'git commit -s -m "Add a thing.\n\nWith a body."'),
        ("work", 'git commit -s -m "Add a thing. Co-Authored-By: Claude <x@y>"'),
        ("work", 'git commit -s -m "Add a thing (Generated with Claude Code)"'),
        ("work", 'git commit -s -m "Add a thing. Claude-Session: 1234"'),
        ("work", f'git commit -s -m "Ship it {ROCKET}"'),
        ("work", f'git commit -s -m "Done {CHECK}"'),
        ("work", f"git commit -s -F {d['msg_missing']}"),
        ("work", "git commit -s -C HEAD~1"),
        ("work", "git commit -s -c HEAD~1"),
        ("work", "git commit -s --reuse-message=HEAD~1"),
        ("work", "git commit -s --reedit-message=HEAD~1"),
        ("work", 'git commit --message="Add a thing." --message="body"'),
        ("wt_feat", 'git commit -m "Add a thing."'),
        ("work", 'git commit -s --no-signoff -m "Add a thing."'),
        ("work", 'git commit -s -m "Add a thing." --trailer "Co-Authored-By: Claude <x@y>"'),
        ("work", 'git commit -s -m "Add a thing." --trailer=Claude-Session:abc123'),
        ("work", 'git commit -s -m "Add a thing." --trailer "Generated with Claude Code"'),
        ("work", f'git commit -s --trailer "Co-Authored-By: Claude" -F {d["msg_ok"]}'),
        ("work", 'git commit -s -m "Add a thing." --trailer "Reviewed-by: x"'),
        ("work", 'git commit -s -m "Add parser module" --trailer "Co-Authored-By: x"'),
        ("work", 'git commit -s -m "Add parser"'),
        ("work", 'git commit -s -m "Add"'),
        ("work", 'git commit -s -m "Add the parser module to the build now"'),
        ("work", 'git commit -s -m "Added parser module"'),
        ("work", 'git commit -s -m "Adding parser module"'),
        ("work", 'git commit -s -m "Adds parser module"'),
        ("work", 'git commit -s -m "Fixes the parser bug"'),
        ("work", 'git commit -s -m "Uses cached parser output"'),
        ("work", 'git commit -s -m "fix parser module now"'),
        ("work", 'git commit -s -m "Fix parser. Add tests"'),
        ("work", 'git commit -s -m "Fix parser! Add tests"'),
        ("work", 'git commit -s -m "Add a thing, with a comma; and a semicolon."'),
        ("work", 'git commit -m "Add parser module"'),
        ("work", f"git commit -s -F {d['msg_bad']}"),
        ("work", f"git commit -s -F {d['msg_two']}"),
        ("work", "git commit -s"),
        ("work", 'git commit -s --fixup HEAD -m "Add parser module"'),
        ("work", 'git commit -s --squash HEAD -m "Add parser module"'),
        ("work", 'git commit -s --fixup=amend:HEAD -m "Add parser module"'),
        ("work", f"git commit -s --fixup=reword:HEAD -F {d['msg_ok']}"),
        ("work", "git update-ref --stdin", "developer"),
        ("work", "git commit -s -C HEAD"),
        ("work", "git commit --fixup HEAD"),
        ("work", "git commit --squash HEAD"),
        ("work", "git commit --amend --no-edit"),
        ("work", "git commit --amend -s"),
        ("work", 'git commit -s --amend'),
        ("work", 'git commit -s -m "Add parser module" --trailer "Reviewed-by: x"'),
        ("work", 'git commit -s -m "Add a thing. Co-Authored-By: Claude <x@y>" --amend'),
        ("work", 'git commit -s -m "Add parser module" -F /dev/null'),
        ("work", 'git commit -s -m "Add parser module" -C HEAD'),
        ("work", "git commit -s -m 'Add parser module' && git commit -s -m 'Added parser module'"),
        ("work", 'git commit -s -m "Add parser module"', "developer"),
        ("work", "git push", "general-purpose"),
        ("work", "git merge main", "developer"),
        ("work", "git rebase main", "developer"),
        ("work", "git reset --soft HEAD~1", "developer"),
        ("work", "git tag v1", "developer"),
        ("work", "git branch -D old", "developer"),
        ("work", "git cherry-pick abc1234", "developer"),
        ("work", "git pull", "developer"),
        ("work", "git update-ref refs/heads/feature/tmp HEAD", "developer"),
        ("work", "gh pr merge 3", "developer"),
        ("main", "git push origin main", "developer"),
    ]
    allow = [
        ("main", "git status"),
        ("main", "git status --porcelain"),
        ("main", "git log --oneline -5"),
        ("main", "git diff HEAD --stat"),
        ("main", "git show HEAD"),
        ("main", "git tag"),
        ("main", "git tag -l"),
        ("main", "git tag --list 'v*'"),
        ("main", "git tag -n5"),
        ("main", "git tag --points-at HEAD"),
        ("main", "git branch --list"),
        ("main", "git branch -a -v"),
        ("main", "git branch --show-current"),
        ("main", "git branch -u origin/main"),
        ("main", "git branch feature/new-work"),
        ("main", "git branch --contains HEAD"),
        ("main", "git push -n origin main"),
        ("main", "git push --dry-run origin main"),
        ("main", "git push --no-dry-run --dry-run origin main"),
        ("main", "git commit --dry-run"),
        ("main", "git checkout -b feature/new-work2"),
        ("main", "git switch -c feature/new-work3"),
        ("main", "git rebase --show-current-patch"),
        ("main", "git symbolic-ref --short HEAD"),
        ("main", "git replace -l"),
        ("main", "git notes list"),
        ("main", "git notes show HEAD"),
        ("main", "git stash list"),
        ("main", "git apply /tmp/some.patch"),
        ("main", "git fetch origin"),
        ("main", "git remote -v"),
        ("main", "git worktree list"),
        ("main", "git rev-parse HEAD"),
        ("main", "git describe --tags --always"),
        ("main", "echo 'git commit -s -m x'"),
        ("main", "grep -rn 'git commit' ."),
        ("main", "make test"),
        ("work", 'git commit -s -m "Add a thing."'),
        ("work", 'git commit --signoff --message="Add a thing."'),
        ("work", 'git commit -s -am "Add a thing."'),
        ("work", 'git commit -s -m "Add a thing, with commas"'),
        ("work", "git commit --amend --no-edit -s"),
        ("work", "git commit --amend --no-edit --signoff"),
        ("work", "git commit -s --fixup HEAD~1"),
        ("work", "git commit -s --squash HEAD~1"),
        ("work", "git commit -s --fixup=HEAD"),
        ("work", "git commit -s --amend --no-edit --no-verify"),
        ("bugfix", 'git commit -s -m "Add parser module"'),
        ("hotfix", 'git commit -s -m "Add parser module"'),
        ("work", 'git commit -s -m "Embed fonts in report"'),
        ("work", 'git commit -s -m "Process queued jobs"'),
        ("work", 'git commit -s -m "Address review notes"'),
        ("work", 'git commit -s -m "Seed demo programs"'),
        ("work", 'git commit -s -m "Fix parser bounds."'),
        ("work", 'git commit -s -m "Add the parser module to the build"'),
        ("work", 'git commit -s -m "Add v1.2 parser support"'),
        ("work", f"git commit -s -F {d['msg_ok']}"),
        ("work", f"cd {d['work']} && git commit -s -F ../msg_ok.txt"),
        ("work", 'git commit -s -m "Add parser module" --trailer "Signed-off-by: Test <test@example.com>"'),
        ("work_upstream_ok", "git push"),
        ("work", "git -c push.default=simple push"),
        ("work", "git -c user.name=x status"),
        ("work", "git --config-env=user.name=NAME_VAR status"),
        ("work", "git symbolic-ref refs/heads/feature/alias refs/heads/feature/x"),
        ("main", "git branch -d feature/old"),
        ("main", "git branch -f feature/old HEAD~1"),
        ("main", "git update-ref refs/heads/feature/old HEAD"),
        ("work", "git push -u origin feature/x"),
        ("work", "git push --force-with-lease"),
        ("work", "git push --force-with-lease origin feature/x"),
        ("work", "git push origin HEAD"),
        ("work", "git push origin feature/x:feature/y"),
        ("work", "git push origin +feature/x:refs/heads/feature/x"),
        ("work", "git push origin --delete feature/old"),
        ("work", "git push --dry-run --all"),
        ("work", "gh pr create --fill"),
        ("work", "gh pr view 3"),
        ("work", "gh pr list"),
        ("work", "gh pr checks 3"),
        ("work", "gh pr diff 3"),
        ("work", "gh pr comment 3 --body merge"),
        ("work", "gh pr edit 3 --title merge"),
        ("main", "gh pr view 3"),
        ("main", "echo gh pr merge 3"),
        ("main", "git branch -m feature/old feature/older"),
        ("main", "git status", "developer"),
        ("main", "git log --oneline -3", "developer"),
        ("work", "git commit --dry-run", "developer"),
        ("work", "git tag -l", "developer"),
        ("work", "gh pr create --fill", "developer"),
        ("work", "git reset --soft HEAD~1"),
        ("work", "git push origin feature/x"),
        ("work", "git merge main"),
        ("work", "git rebase main"),
        ("work", "git tag v9.9.9"),
        ("work", "git branch -d feature/old"),
        ("work", "git update-ref refs/heads/feature/tmp HEAD"),
        ("work", "git cherry-pick abc1234"),
        ("rebase_work", "git rebase --continue"),
        ("rebase_work", "git rebase --abort"),
        ("rebase_work", "git rebase --skip"),
        ("rebase_work", "git rebase --edit-todo"),
        ("rebase_work", 'git commit -s -m "Resolve the conflict."'),
        ("rebase_work", "git commit --amend --no-edit -s"),
        ("wt_feat", 'git commit -s -m "Add a thing."'),
        ("wt_feat", "git reset --soft HEAD~1"),
        ("plain", 'git commit -s -m "Add a thing."'),
        ("plain", "git reset --hard HEAD~1"),
        ("plain", f'cd {os.path.join(d["plain"], "nope")} && git commit -s -m "Add a thing."'),
        ("plain", "ls -la"),
        ("work", "git pull --rebase"),
        ("work", "git pull origin feature/x"),
        ("plain", f"git --git-dir={d['work']}/.git commit -s -m \"Add a thing.\""),
        ("main", f"git --work-tree={d['work']} --git-dir={d['work']}/.git commit -s -m \"Add a thing.\""),
        ("plain", f"git --git-dir={d['main']}/.git status"),
        ("main", "git shellhack"),
        ("main", "git lg"),
        ("main", "git -c alias.st=status st"),
        ("work", "git publish origin feature/x"),
        ("main", "git unknown-subcommand --flag"),
        ("plain", f"(cd {d['main']} && git status); ls"),
        ("work", f"(cd {d['plain']} && pwd); git commit -s -m \"Add a thing.\""),
        ("main", f"(cd {d['work']} && git commit -s -m \"Add a thing.\")"),
        ("main", "git commit --short"),
        ("main", "git commit --porcelain"),
        ("main", "git commit --dry-run --long"),
        ("work", 'git commit --dry-run -m "Preview"'),
        ("main", "git tag --verify v1.0"),
        ("main", "git tag -v v1.0"),
        ("main", "git replace -l abc"),
        ("main", "git replace --list"),
        ("work", 'git commit --no-signoff -s -m "Add a thing."'),
        ("plain", f'git --git-dir={d["work"]}/.git --work-tree={d["main"]} commit -s -m "Add a thing."'),
        ("work", f'git --work-tree={d["main"]} commit -s -m "Add a thing."'),
        ("work", f'git --work-tree={d["main"]} --git-dir={d["work"]}/.git push origin feature/x'),
        ("main", "git st --short"),
        ("main", "git -c alias.look='-c color.ui=false status' look"),
        ("main", f'(cd {d["work"]} && echo "$(git commit -s -m \"Add a thing.\")")'),
        ("main", f'x=$(cd {d["work"]} && git commit -s -m "Add a thing.")'),
        ("main", f'(cd {d["work"]}; case x in x) git commit -s -m "Add a thing.";; esac)'),
        ("main", f'case x in x) (cd {d["work"]} && git commit -s -m "Add a thing.");; esac'),
        ("work", 'case x in x) git commit -s -m "Add a thing.";; esac'),
        ("work", f'(cd {d["plain"]} && echo "$(git push origin main)")'),
        ("main", "git pull --dry-run"),
        ("main", "git commit -z -m x"),
        ("main", 'git commit -sz -m "Bad Co-Authored-By: Claude"'),
        ("main", "git commit --null"),
        ("work", f'cat >"$(git commit -s -m \'Add a thing.\')"; (cd {d["main"]} && echo "$(git status)")'),
        ("main", f'cat >"$(cd {d["work"]} && git commit -s -m \'Add a thing.\')"'),
        ("main", f'(cd {d["work"]} && cat <<EOF\n$(git commit -s -m "Add a thing.")\nEOF\n)'),
        ("main", f"(cd {d['work']} && cat <<'EOF'\n$(git push origin main)\nEOF\n)"),
        ("main", "cat <<'EOF'\n$(git push origin main)\nEOF"),
        ("main", 'git commit -s -m esac --dry-run'),
        ("main", 'echo case; git status'),
        ("work", f'(cd {d["work"]} && echo case); git commit -s -m "Add a thing."'),
        ("work", f'cat <<EOF\n$(cd {d["main"]})\n$(git commit -s -m "Add a thing.")\nEOF'),
        ("work", f'(cd {d["work"]}; if true; then case x in x) git push origin feature/x;; esac; fi)'),
        ("work", f'(cd {d["plain"]}; if true; then case x in x) git commit -s -m "Add a thing.";; esac; fi)'),
        ("main", "echo __subst_0__"),
        ("main", "echo __redir_3__ && git status"),
    ]
    return deny, ask, allow


GARBAGE = ["", "not json", "null", "[]", "1", '{"tool_input":{"command":42}}',
           '{"tool_name":"Bash","tool_input":null}',
           '{"tool_name":"Edit","tool_input":{"command":"git commit -m x"}}',
           '{"tool_name":"Bash","tool_input":{"command":null}}',
           '{"tool_name":"Bash","tool_input":{"command":"echo \'oops}',
           '{"tool_name":"Bash","cwd":42,"tool_input":{"command":"git log"}}',
           '{"tool_name":"Bash","cwd":{},"tool_input":{"command":"git status --porcelain"}}',
           json.dumps({"tool_name": "Bash", "tool_input": {"command": "$(" * 300}}),
           json.dumps({"tool_name": "Bash", "tool_input": {"command": "cat <<EOF\n" + "x\n" * 3000}})]


def run(cmd, cwd, agent=None):
    body = {"tool_name": "Bash", "cwd": cwd, "tool_input": {"command": cmd}}
    if agent:
        body["agent_type"] = agent
    done = subprocess.run(["python3", hook], input=json.dumps(body), capture_output=True, text=True, timeout=30,
                          env=ENV)
    return done.returncode, done.stdout.strip(), done.stderr.strip()


def check_bucket(name, entries, dirs, decision):
    bad, slowest = 0, 0.0
    for key, cmd, *rest in entries:
        t0 = time.time()
        rc, out, err = run(cmd, dirs[key], *rest)
        slowest = max(slowest, time.time() - t0)
        ok = rc == 0 and not err and (f'"{decision}"' in out if decision else out == "")
        bad += not ok
        if not ok:
            print(f"{name} MISS  [{key}]{rest} {cmd!r} -> rc={rc} {out[:200]} {err[-160:]}")
    return bad, slowest


def main():
    with tempfile.TemporaryDirectory() as base:
        dirs = build(base)
        deny, ask, allow = cases(dirs)
        bad = 0
        slowest = 0.0
        for name, entries, decision in (("DENY", deny, "deny"), ("ASK", ask, "ask"), ("ALLOW", allow, None)):
            missed, slow = check_bucket(name, entries, dirs, decision)
            bad += missed
            slowest = max(slowest, slow)
        for raw in GARBAGE:
            done = subprocess.run(["python3", hook], input=raw, capture_output=True, text=True, timeout=30)
            ok = done.returncode == 0 and not done.stderr and done.stdout == ""
            bad += not ok
            if not ok:
                print(f"garbage {raw[:60]!r} -> rc={done.returncode} out={done.stdout[:60]!r} err={done.stderr[-160:]!r}")

        spots = [
            (dirs["work"], 'git commit -m "Add a thing."', ["-s", "git commit -s -m 'Add a thing.'"], "deny"),
            (dirs["work"], 'git commit -s -m "A." -m "B."', ["ONE sentence", "2 `-m`"], "deny"),
            (dirs["work"], 'git commit -s -m "Add a thing. Co-Authored-By: Claude"',
             ["Co-Authored-By", "git commit -s -m 'Add a thing.'"], "deny"),
            (dirs["main"], 'git commit -s -m "Add a thing."', ["not a work branch", "main", "feature/"], "ask"),
            (dirs["detached"], "git reset HEAD~1", ["detached"], "ask"),
            (dirs["rebase_main"], "git rebase --continue", ["rebase", "main"], "ask"),
            (dirs["main"], "git publish origin main", ["`git push`", "not a work branch"], "ask"),
            (dirs["main"], "git pull", ["`git pull`", "not a work branch"], "ask"),
            (dirs["work"], 'git commit -s -m "Add a thing." --trailer "Claude-Session: x"',
             ["Claude-Session", "git commit -s -m 'Add a thing.'"], "deny"),
            (dirs["work"], 'git commit -s --no-signoff -m "Add a thing."',
             ["signed off", "git commit -s -m 'Add a thing.'"], "deny"),
            (dirs["main"], "git pub origin main", ["`git push`", "not a work branch"], "ask"),
            (dirs["work"], f'(cd {dirs["main"]} && echo "$(git push origin main)")', ["`git push`", "main"], "ask"),
            (dirs["work"], 'git commit -s -m "Add the parser module to the build now"',
             ["3–7 words", "<Imperative verb, 3–7 words>"], "deny"),
            (dirs["work"], 'git commit -s -m "Adding parser module"',
             ["imperative", "<Imperative verb, 3–7 words>"], "deny"),
            (dirs["work"], 'git commit -s -m "Fix parser. Add tests"',
             ["one sentence", "<Imperative verb, 3–7 words>"], "deny"),
            (dirs["work"], 'git commit -m "Add parser module"', ["signed off", "git commit -s -m 'Add parser module'"],
             "deny"),
            (dirs["work"], 'git commit -s -m "Add parser module" --trailer "Reviewed-by: x"',
             ["Signed-off-by", "git commit -s -m 'Add parser module'"], "deny"),
            (dirs["work"], "git commit -s", ["<Imperative verb, 3–7 words>"], "deny"),
            (dirs["work"], f"git commit -F {dirs['msg_ok']}", ["signed off", "git commit -s -m 'Add parser module'"],
             "deny"),
            (dirs["work"], f"git commit -s -F {dirs['msg_two']}", ["body"], "deny"),
            (dirs["work"], "git push", ["main session"], "deny"),
            (dirs["work"], "git push origin feature/x:main", ["main", "not a work branch"], "ask"),
            (dirs["work"], "gh pr merge 3", ["merges a PR into its base branch"], "ask"),
            (dirs["work"], "git branch -D main", ["main", "not a work branch"], "ask"),
            (dirs["main"], 'git commit -s -m "Add parser module" && git push origin HEAD:main',
             ["creates a commit", "publishes", "; "], "ask"),
            (dirs["work"], 'git commit -s --fixup HEAD -m "Add parser module"',
             ["plain `--fixup <sha>`", "Use: git commit -s --fixup HEAD"], "deny"),
            (dirs["work"], 'git commit -s --fixup=amend:HEAD~2 -m "Add parser module"',
             ["Use: git commit -s --fixup 'amend:HEAD~2'"], "deny"),
            (dirs["work"], 'git commit -s --squash abc1234 -m "Add parser module"',
             ["Use: git commit -s --squash abc1234"], "deny"),
            (dirs["work"], "git --config-env=push.default=PUSHDEF push", ["--config-env"], "ask"),
            (dirs["work_upstream"], "git push", ["`main`", "not a work branch"], "ask"),
        ]
        for cwd, cmd, needles, decision in spots:
            agent = "general-purpose" if needles == ["main session"] else None
            rc, out, err = run(cmd, cwd, agent)
            reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"] if out else ""
            missing = [n for n in needles if n not in reason]
            ok = rc == 0 and f'"{decision}"' in out and not missing
            bad += not ok
            if not ok:
                print(f"SPOT FAIL  {cmd!r} missing={missing} -> {out[:300]}")

        total = len(deny) + len(ask) + len(allow) + len(GARBAGE) + len(spots)
        print(f"hook: {hook}\ndeny cases: {len(deny)}, ask cases: {len(ask)}, allow cases: {len(allow)}, "
              f"garbage: {len(GARBAGE)}, spot checks: {len(spots)}, slowest run: {slowest * 1000:.0f} ms, "
              f"FAILURES: {bad}")
        print(("FAIL " if bad else "PASS ") + f"{total - bad}/{total}")
        return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
