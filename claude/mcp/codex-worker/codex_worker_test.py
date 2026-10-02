#!/usr/bin/env python3
"""Unit tests for codex_worker.py against a fake codex binary; run with the worker's venv python."""
import inspect
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import codex_worker as worker

CANNED_ANSWER = "src/app.py:3: off-by-one in the loop bound"
TURN_USAGE = ({"input_tokens": 1200, "cached_input_tokens": 100, "output_tokens": 30},
              {"input_tokens": 800, "cached_input_tokens": 0, "output_tokens": 12})
PLAN_TEXT = textwrap.dedent("""\
    # Plan: widget

    ## task
    TASK-SENTINEL build the widget.

    ## test_plan
    - unit — TESTPLAN-SENTINEL — asserts — missing today

    ## acceptance_criteria
    - ACCEPTANCE-SENTINEL the widget renders

    ## commands
    Unit: pytest
    """)
PLAN_WITHOUT_ACCEPTANCE = "# Plan\n\n## task\nNo criteria here.\n"
DISABLED = ("apps", "browser_use", "browser_use_external", "computer_use", "goals", "image_generation",
            "in_app_browser", "multi_agent", "personality", "plugins", "remote_plugin", "skill_search",
            "sleep_tool", "tool_suggest", "view_image", "workspace_dependencies", "fast_mode")
CODE_MODE_FEATURE = "code_mode_host"
FAKE_CODEX = textwrap.dedent("""\
    #!/usr/bin/env python3
    import json, os, sys, time
    record = os.environ["FAKE_CODEX_RECORD"]
    argv = sys.argv[1:]
    prompt = sys.stdin.read()
    with open(record, "w", encoding="utf-8") as handle:
        json.dump({"argv": argv, "stdin": prompt, "cwd": os.getcwd()}, handle)
    time.sleep(float(os.environ.get("FAKE_CODEX_SLEEP", "0")))
    if os.environ.get("FAKE_CODEX_WRITE", "1") == "1":
        with open(argv[argv.index("-o") + 1], "w", encoding="utf-8") as handle:
            handle.write(os.environ["FAKE_CODEX_ANSWER"])
    print(json.dumps({"type": "thread.started", "thread_id": "t1"}))
    for event in json.loads(os.environ.get("FAKE_CODEX_EVENTS", "[]")):
        print(json.dumps(event))
    for usage in json.loads(os.environ["FAKE_CODEX_USAGE"]):
        print(json.dumps({"type": "turn.completed", "usage": usage}))
    print(os.environ.get("FAKE_CODEX_STDERR", ""), file=sys.stderr)
    sys.exit(int(os.environ.get("FAKE_CODEX_RC", "0")))
    """)


def git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)


def git_out(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


class WorkerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.record = self.base / "record.json"
        fake = self.base / "fake-codex"
        fake.write_text(FAKE_CODEX)
        fake.chmod(0o755)
        self.env_backup = dict(os.environ)
        os.environ.update({
            "CODEX_BIN": str(fake),
            "FAKE_CODEX_RECORD": str(self.record),
            "FAKE_CODEX_ANSWER": CANNED_ANSWER,
            "FAKE_CODEX_USAGE": json.dumps(TURN_USAGE),
        })
        self.plan = self.base / "plan.md"
        self.plan.write_text(PLAN_TEXT)
        self.repo = self.base / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "t")
        (self.repo / "app.py").write_text("def f():\n    return 1\n")
        (self.repo / "other.py").write_text("x = 1\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "one")
        self.first = git_out(self.repo, "rev-parse", "HEAD")

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.env_backup)
        self.tmp.cleanup()

    def review(self, mode, **kwargs):
        kwargs.setdefault("plan_file", str(self.plan))
        kwargs.setdefault("project_path", str(self.repo))
        return worker.codex_review_changes(mode=mode, **kwargs)

    def recorded(self):
        return json.loads(self.record.read_text())

    def argv_value(self, argv, flag):
        return argv[argv.index(flag) + 1]

    def config_values(self, argv):
        return [argv[i + 1] for i, word in enumerate(argv) if word == "-c"]

    def test_tool_has_no_model_or_effort_parameters(self):
        params = list(inspect.signature(worker.codex_review_changes).parameters)
        self.assertEqual(params, ["mode", "plan_file", "project_path", "base", "recheck"])

    def test_plan_mode_uses_sol_high_and_full_plan(self):
        out = self.review("plan")
        argv, prompt = self.recorded()["argv"], self.recorded()["stdin"]
        self.assertEqual(self.argv_value(argv, "-m"), "gpt-6-sol")
        self.assertIn('model_reasoning_effort="high"', self.config_values(argv))
        self.assertIn(PLAN_TEXT, prompt)
        self.assertIn(str(self.repo), prompt)
        self.assertIn(worker.PLAN_INSTRUCTIONS, prompt)
        self.assertTrue(out.startswith("codex plan gpt-6-sol/high"), out)

    def test_both_instructions_demand_weighted_line_prefix(self):
        for instructions in (worker.PLAN_INSTRUCTIONS, worker.CODE_INSTRUCTIONS):
            self.assertIn("`H: ", instructions)
            self.assertIn("`L: ", instructions)
            self.assertIn("exactly PASS", instructions)

    def test_plan_instructions_limit_reading_to_plan_named_files(self):
        self.assertIn("only the files the plan names", worker.PLAN_INSTRUCTIONS)
        self.assertIn("only to check a claim the plan makes", worker.PLAN_INSTRUCTIONS)

    def test_code_mode_uses_sol_high(self):
        self.review("code")
        argv = self.recorded()["argv"]
        self.assertEqual(self.argv_value(argv, "-m"), "gpt-6-sol")
        self.assertIn('model_reasoning_effort="high"', self.config_values(argv))

    def test_code_prompt_carries_only_acceptance_section(self):
        self.review("code")
        prompt = self.recorded()["stdin"]
        self.assertIn(worker.CODE_INSTRUCTIONS, prompt)
        self.assertIn("ACCEPTANCE-SENTINEL", prompt)
        self.assertNotIn("TASK-SENTINEL", prompt)
        self.assertNotIn("TESTPLAN-SENTINEL", prompt)
        self.assertIn(str(self.repo), prompt)

    def test_code_prompt_has_tracked_diff(self):
        (self.repo / "app.py").write_text("def f():\n    return 2\n")
        self.review("code")
        prompt = self.recorded()["stdin"]
        self.assertIn("-    return 1", prompt)
        self.assertIn("+    return 2", prompt)

    def test_code_prompt_inlines_untracked_text_file(self):
        (self.repo / "new_module.py").write_text("UNTRACKED_SENTINEL = 7\n")
        self.review("code")
        prompt = self.recorded()["stdin"]
        self.assertIn("new_module.py", prompt)
        self.assertIn("+UNTRACKED_SENTINEL = 7", prompt)

    def test_binary_change_shows_binary_files_line(self):
        (self.repo / "blob.bin").write_bytes(b"\x00\x01BINARY_SENTINEL\x00" * 10)
        self.review("code")
        prompt = self.recorded()["stdin"]
        self.assertIn("Binary files /dev/null and b/blob.bin differ", prompt)
        self.assertNotIn("BINARY_SENTINEL", prompt)

    def test_ignored_files_stay_out(self):
        (self.repo / ".gitignore").write_text("*.log\n")
        (self.repo / "debug.log").write_text("IGNORED_SENTINEL\n")
        self.review("code")
        prompt = self.recorded()["stdin"]
        self.assertNotIn("IGNORED_SENTINEL", prompt)
        self.assertNotIn("debug.log", prompt)

    def checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
            real_index = self.repo / ".git" / "index"
            (Path(tmp) / "index").write_bytes(real_index.read_bytes())
            subprocess.run(["git", "-C", str(self.repo), "add", "-A"], env=env, check=True)
            tree = subprocess.run(["git", "-C", str(self.repo), "write-tree"], env=env, check=True,
                                  capture_output=True, text=True).stdout.strip()
        return git_out(self.repo, "commit-tree", "--no-gpg-sign", tree, "-p", "HEAD", "-m", "review-checkpoint")

    def test_checkpoint_with_new_file_sends_only_later_hunk(self):
        (self.repo / "fresh_module.py").write_text("".join(f"ORIGINAL_LINE_{n:02}\n" for n in range(1, 11)))
        base = self.checkpoint()
        with (self.repo / "fresh_module.py").open("a") as handle:
            handle.write("LATER_HUNK\n")
        self.review("code", base=base)
        prompt = self.recorded()["stdin"]
        self.assertIn("+LATER_HUNK", prompt)
        self.assertNotIn("ORIGINAL_LINE_01", prompt)

    @unittest.skipIf(os.geteuid() == 0, "root can read mode-000 files")
    def test_error_when_snapshot_add_fails(self):
        (self.repo / "app.py").write_text("def f():\n    return 'UNREVIEWED'\n")
        locked = self.repo / "locked.py"
        locked.write_text("SECRET = 1\n")
        locked.chmod(0)
        try:
            out = self.review("code")
        finally:
            locked.chmod(0o644)
        self.assert_error(out, "locked.py")
        self.assertFalse(self.record.exists())

    def test_review_leaves_real_index_untouched(self):
        index = self.repo / ".git" / "index"
        (self.repo / "app.py").write_text("def f():\n    return 3\n")
        (self.repo / "brand_new.py").write_text("NEW = 1\n")
        before = (index.read_bytes(), git_out(self.repo, "ls-files", "-s"))
        self.review("code")
        self.assertIn("+NEW = 1", self.recorded()["stdin"])
        self.assertEqual((index.read_bytes(), git_out(self.repo, "ls-files", "-s")), before)
        staged = subprocess.run(["git", "-C", str(self.repo), "diff", "--cached", "--quiet"])
        self.assertEqual(staged.returncode, 0)

    def test_checkpoint_base_limits_diff(self):
        (self.repo / "other.py").write_text("x = 'COMMITTED_CHANGE'\n")
        git(self.repo, "commit", "-q", "-am", "two")
        checkpoint = git_out(self.repo, "rev-parse", "HEAD")
        (self.repo / "app.py").write_text("def f():\n    return 'WORKING_CHANGE'\n")
        self.review("code", base=checkpoint)
        prompt = self.recorded()["stdin"]
        self.assertIn("WORKING_CHANGE", prompt)
        self.assertNotIn("COMMITTED_CHANGE", prompt)
        self.assertIn(checkpoint, prompt)
        self.review("code", base=self.first)
        self.assertIn("COMMITTED_CHANGE", self.recorded()["stdin"])

    def test_recheck_block_only_when_given(self):
        self.review("code")
        self.assertNotIn(worker.RECHECK_HEADER, self.recorded()["stdin"])
        self.review("code", recheck="app.py:2: returns the wrong value")
        prompt = self.recorded()["stdin"]
        self.assertIn(worker.RECHECK_HEADER, prompt)
        self.assertIn("app.py:2: returns the wrong value", prompt)

    def test_oversize_diff_falls_back_to_stat(self):
        (self.repo / "app.py").write_text("HUGE_SENTINEL\n" * (worker.MAX_DIFF_CHARS // 10))
        (self.repo / "fresh.py").write_text("FRESH_SENTINEL = 1\n")
        self.review("code")
        prompt = self.recorded()["stdin"]
        self.assertNotIn("HUGE_SENTINEL", prompt)
        self.assertNotIn("FRESH_SENTINEL", prompt)
        self.assertRegex(prompt, r"app\.py\s+\|")
        self.assertRegex(prompt, r"fresh\.py\s+\|")
        self.assertIn("git diff HEAD -- <path>", prompt)
        self.assertLess(len(prompt), worker.MAX_DIFF_CHARS)

    def test_argv_is_minimal_and_read_only(self):
        self.review("code")
        record = self.recorded()
        argv = record["argv"]
        self.assertEqual(argv[0], "exec")
        for flag in ("--json", "--ephemeral", "--ignore-user-config", "--skip-git-repo-check"):
            self.assertIn(flag, argv)
        self.assertEqual(self.argv_value(argv, "--sandbox"), "read-only")
        self.assertNotIn("--disable", argv)
        configs = self.config_values(argv)
        features = sorted(value for value in configs if value.startswith("features."))
        self.assertEqual(features, sorted(f"features.{name}=false" for name in DISABLED))
        self.assertIn('web_search="disabled"', configs)
        self.assertIn('model_reasoning_summary="none"', configs)
        self.assertEqual(self.argv_value(argv, "-C"), str(self.repo))
        self.assertIn("-o", argv)
        self.assertEqual(argv[-1], "-")

    def test_code_mode_host_never_disabled(self):
        for mode in ("plan", "code"):
            self.review(mode)
            argv = self.recorded()["argv"]
            self.assertFalse(any(CODE_MODE_FEATURE in word for word in argv), argv)

    def test_result_header_sums_tokens_and_returns_answer(self):
        out = self.review("code")
        header, _, body = out.partition("\n")
        total_in = sum(u["input_tokens"] for u in TURN_USAGE)
        total_cached = sum(u["cached_input_tokens"] for u in TURN_USAGE)
        total_out = sum(u["output_tokens"] for u in TURN_USAGE)
        self.assertEqual(header, f"codex code gpt-6-sol/high tokens in={total_in} cached={total_cached} "
                                 f"out={total_out}")
        self.assertEqual(body.strip(), CANNED_ANSWER)

    def test_temp_dir_removed(self):
        self.review("code")
        output_path = Path(self.argv_value(self.recorded()["argv"], "-o"))
        self.assertFalse(output_path.parent.exists())
        os.environ["FAKE_CODEX_RC"] = "3"
        self.review("code")
        self.assertFalse(Path(self.argv_value(self.recorded()["argv"], "-o")).parent.exists())

    def assert_error(self, out, fragment=""):
        self.assertTrue(out.startswith("ERROR:"), out)
        self.assertIn(fragment, out)

    def test_error_unknown_mode(self):
        for mode in ("final-audit", "bogus", ""):
            self.assert_error(self.review(mode), "mode")
        self.assertFalse(self.record.exists())

    def test_error_plan_file_relative(self):
        self.assert_error(self.review("plan", plan_file="plan.md"), "plan_file")

    def test_error_plan_file_missing(self):
        self.assert_error(self.review("plan", plan_file=str(self.base / "missing.md")), "plan_file")
        self.assert_error(self.review("plan", plan_file=str(self.base)), "plan_file")

    def test_error_project_path_not_a_directory(self):
        for mode in ("plan", "code"):
            self.assert_error(self.review(mode, project_path=str(self.base / "absent")), "project")
        self.assertFalse(self.record.exists())

    def test_error_code_not_git_work_tree(self):
        plain = self.base / "plain"
        plain.mkdir()
        self.assert_error(self.review("code", project_path=str(plain)), "git")

    def test_error_code_base_not_commit(self):
        self.assert_error(self.review("code", base="no-such-ref"), "base")
        self.assert_error(self.review("code", base="--output=/tmp/x"), "base")

    def test_error_code_plan_without_acceptance(self):
        self.plan.write_text(PLAN_WITHOUT_ACCEPTANCE)
        self.assert_error(self.review("code"), "acceptance_criteria")
        self.assertFalse(self.record.exists())

    def test_plan_mode_does_not_need_acceptance_or_git(self):
        self.plan.write_text(PLAN_WITHOUT_ACCEPTANCE)
        plain = self.base / "plain"
        plain.mkdir()
        out = self.review("plan", project_path=str(plain))
        self.assertTrue(out.startswith("codex plan"), out)

    def test_error_nonzero_exit(self):
        os.environ["FAKE_CODEX_RC"] = "7"
        os.environ["FAKE_CODEX_STDERR"] = "x" * 5000 + "STDERR_TAIL"
        out = self.review("code")
        self.assert_error(out, "codex exited 7")
        self.assertIn("STDERR_TAIL", out)
        self.assertLess(len(out), 2200)

    def test_error_reports_json_error_events_from_stdout(self):
        os.environ["FAKE_CODEX_RC"] = "1"
        os.environ["FAKE_CODEX_WRITE"] = "0"
        os.environ["FAKE_CODEX_STDERR"] = "STDERR_DETAIL"
        os.environ["FAKE_CODEX_EVENTS"] = json.dumps([
            {"type": "error", "message": "MODEL_REJECTED for this account"},
            {"type": "turn.failed", "error": {"message": "MODEL_REJECTED for this account"}},
            {"type": "turn.failed", "error": {"message": "TURN_FAILED_DETAIL"}},
        ])
        out = self.review("code")
        self.assert_error(out, "codex exited 1")
        self.assertEqual(out.count("MODEL_REJECTED"), 1, out)
        self.assertIn("TURN_FAILED_DETAIL", out)
        self.assertIn("STDERR_DETAIL", out)

    def test_error_detail_is_capped(self):
        os.environ["FAKE_CODEX_RC"] = "1"
        os.environ["FAKE_CODEX_STDERR"] = "e" * 5000
        os.environ["FAKE_CODEX_EVENTS"] = json.dumps(
            [{"type": "error", "message": f"m{index}-" + "x" * 500} for index in range(20)])
        out = self.review("code")
        self.assert_error(out, "codex exited 1")
        self.assertLessEqual(len(out.partition("\n")[2]), worker.MAX_STDERR_CHARS)

    def test_error_missing_output_file(self):
        os.environ["FAKE_CODEX_WRITE"] = "0"
        self.assert_error(self.review("code"), "codex exited 0")

    def test_error_missing_binary(self):
        os.environ["CODEX_BIN"] = str(self.base / "no-codex")
        self.assert_error(self.review("code"), "not found")

    def test_error_timeout(self):
        os.environ["FAKE_CODEX_SLEEP"] = "3"
        saved = worker.REVIEW_TIMEOUT_SECONDS
        worker.REVIEW_TIMEOUT_SECONDS = 0.5
        try:
            self.assert_error(self.review("code"), "timed out")
        finally:
            worker.REVIEW_TIMEOUT_SECONDS = saved


if __name__ == "__main__":
    unittest.main(verbosity=1)
