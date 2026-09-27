#!/usr/bin/env python3
"""Regression matrix for delegation-guard.py (the sibling file by default; pass another path as argv[1])."""
import json, os, subprocess, sys, tempfile, time

hook = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                          "delegation-guard.py")
PLAN = ("# Plan: fix the parser\n\n"
        "## task\nFix the parser.\n\n"
        "## test_plan\n- unit — test_parse_empty — raises — accepts today\n\n"
        "## acceptance_criteria\n- the matrix passes\n\n"
        "## commands\nUnit: ~/.claude/bin/verify -- 'cd /home/user/project && pytest -q'\n\n"
        "## repos\nYou may only touch /home/user/project; you may not touch anything else.\n")
PLAN_MARKERS = {
    "acceptance_criteria": ("## acceptance_criteria\n- the matrix passes\n", ""),
    "test_plan": ("## test_plan\n- unit — test_parse_empty — raises — accepts today\n", ""),
    "verify --": ("~/.claude/bin/verify -- ", "run "),
    "repo boundary": ("You may only touch /home/user/project; you may not touch anything else.\n", ""),
}


def developer_prompt(plan_path, extra=""):
    return f"Implement the plan below test-first.\nplan_file: {plan_path}\n{extra}"


def runner_prompt(plan_path, mode="code", project=None):
    project_line = "" if project is None else f"project_path: {project}\n"
    return f"mode: {mode}\nplan_file: {plan_path}\n{project_line}base: HEAD\n"


def run(tool_input, tool_name="Agent"):
    payload = json.dumps({"tool_name": tool_name, "tool_input": tool_input})
    done = subprocess.run(["python3", hook], input=payload, capture_output=True, text=True, timeout=10)
    return done.returncode, done.stdout.strip(), done.stderr.strip()


bad = 0
checks = 0
slowest = 0.0


def expect(label, tool_input, denied, tool_name="Agent"):
    global bad, checks, slowest
    checks += 1
    t0 = time.time()
    rc, out, err = run(tool_input, tool_name)
    slowest = max(slowest, time.time() - t0)
    ok = rc == 0 and not err and ('"deny"' in out if denied else out == "")
    if not ok:
        bad += 1
        kind = "DENY MISS" if denied else "ALLOW FP "
        print(f"{kind} [{label}] rc={rc} out={out[:200]!r} err={err[-200:]!r}")
    return out


with tempfile.TemporaryDirectory() as base:
    def plan_file(name, text):
        path = os.path.join(base, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    full = plan_file("full.md", PLAN)
    missing_plans = {marker: plan_file(f"incomplete-{index}.md", PLAN.replace(old, new))
                     for index, (marker, (old, new)) in enumerate(PLAN_MARKERS.items())}

    expect("developer without plan_file", {"subagent_type": "developer", "prompt": "just fix the bug"}, True)
    expect("developer relative plan_file",
           {"subagent_type": "developer", "prompt": developer_prompt("plans/full.md")}, True)
    expect("developer tilde plan_file",
           {"subagent_type": "developer", "prompt": developer_prompt("~/plans/full.md")}, True)
    expect("developer missing plan file",
           {"subagent_type": "developer", "prompt": developer_prompt(os.path.join(base, "nope.md"))}, True)
    expect("developer plan_file is a directory",
           {"subagent_type": "developer", "prompt": developer_prompt(base)}, True)
    for marker, path in missing_plans.items():
        expect(f"developer plan missing {marker}",
               {"subagent_type": "developer", "prompt": developer_prompt(path)}, True)
    expect("developer empty tdd_exempt",
           {"subagent_type": "developer", "prompt": developer_prompt(full, "tdd_exempt:\n")}, True)
    expect("developer blank tdd_exempt",
           {"subagent_type": "developer", "prompt": developer_prompt(full, "tdd_exempt:   \n")}, True)
    expect("developer empty prompt", {"subagent_type": "developer", "prompt": ""}, True)

    expect("developer complete", {"subagent_type": "developer", "prompt": developer_prompt(full)}, False)
    expect("developer complete via agent_type", {"agent_type": "developer", "prompt": developer_prompt(full)},
           False)
    expect("developer complete with model", {"subagent_type": "developer", "model": "opus",
                                             "prompt": developer_prompt(full)}, False)
    expect("developer backticked plan_file",
           {"subagent_type": "developer", "prompt": developer_prompt(f"`{full}`")}, False)
    expect("developer tdd_exempt with reason",
           {"subagent_type": "developer", "prompt": developer_prompt(full, "tdd_exempt: docs only\n")}, False)
    expect("developer markers in prompt when plan lacks them",
           {"subagent_type": "developer",
            "prompt": developer_prompt(missing_plans["verify --"], "Run ~/.claude/bin/verify -- pytest.\n")},
           False)
    expect("developer via Task", {"subagent_type": "developer", "prompt": developer_prompt(full)}, False, "Task")

    expect("codex-runner without mode",
           {"subagent_type": "codex-runner", "prompt": f"plan_file: {full}\n"}, True)
    expect("codex-runner without plan_file",
           {"subagent_type": "codex-runner", "prompt": "mode: code\nproject_path: /home/user/project\n"}, True)
    expect("codex-runner bad mode", {"subagent_type": "codex-runner", "prompt": runner_prompt(full, "final-audit")},
           True)
    expect("codex-runner relative plan_file",
           {"subagent_type": "codex-runner", "prompt": runner_prompt("plan.md")}, True)
    expect("codex-runner missing plan file",
           {"subagent_type": "codex-runner", "prompt": runner_prompt(os.path.join(base, "gone.md"))}, True)
    expect("codex-runner free text", {"subagent_type": "codex-runner", "prompt": "review the diff"}, True)
    expect("codex-runner without project_path",
           {"subagent_type": "codex-runner", "prompt": runner_prompt(full)}, True)
    expect("codex-runner relative project_path",
           {"subagent_type": "codex-runner", "prompt": runner_prompt(full, project="repo")}, True)
    expect("codex-runner missing project_path dir",
           {"subagent_type": "codex-runner", "prompt": runner_prompt(full, project=os.path.join(base, "gone"))},
           True)
    expect("codex-runner project_path is a file",
           {"subagent_type": "codex-runner", "prompt": runner_prompt(full, project=full)}, True)
    expect("codex-runner code complete",
           {"subagent_type": "codex-runner", "prompt": runner_prompt(full, project=base)}, False)
    expect("codex-runner plan complete",
           {"subagent_type": "codex-runner", "prompt": runner_prompt(full, "plan", project=f"`{base}`")}, False)
    words_only = plan_file("words-only.md", PLAN.replace("## acceptance_criteria\n", "acceptance_criteria TBD\n")
                           .replace("## test_plan\n", "no test_plan yet\n"))
    expect("developer plan with marker words but no headings",
           {"subagent_type": "developer", "prompt": developer_prompt(words_only)}, True)
    no_accept_heading = plan_file("no-accept-heading.md",
                                  PLAN.replace("## acceptance_criteria\n", "acceptance_criteria TBD\n"))
    expect("developer plan without acceptance heading",
           {"subagent_type": "developer", "prompt": developer_prompt(no_accept_heading)}, True)
    no_test_heading = plan_file("no-test-heading.md", PLAN.replace("## test_plan\n", "no test_plan yet\n"))
    expect("developer plan without test_plan heading",
           {"subagent_type": "developer", "prompt": developer_prompt(no_test_heading)}, True)
    heading_cases = {
        "empty acceptance section": PLAN.replace("## acceptance_criteria\n- the matrix passes\n",
                                                 "## acceptance_criteria\n\n"),
        "empty test_plan section": PLAN.replace("## test_plan\n- unit — test_parse_empty — raises — accepts today\n",
                                                "## test_plan\n   \n"),
        "both sections empty": "## acceptance_criteria\n## test_plan\n## commands\n"
                               "~/.claude/bin/verify -- pytest /abs/x\nyou may not touch /etc\n",
        "headings in backtick fence": PLAN.replace("## test_plan\n", "```\n## test_plan\n")
                                          .replace("- the matrix passes\n", "- the matrix passes\n```\n"),
        "headings in tilde fence": PLAN.replace("## test_plan\n", "~~~markdown\n## test_plan\n")
                                       .replace("- the matrix passes\n", "- the matrix passes\n~~~\n"),
    }
    for index, (label, text) in enumerate(heading_cases.items()):
        expect(f"developer plan {label}",
               {"subagent_type": "developer", "prompt": developer_prompt(plan_file(f"headings-{index}.md", text))},
               True)
    fenced_example = plan_file("fenced-example.md", PLAN + "\n```\n## acceptance_criteria\n```\n")
    expect("developer filled plan with an extra fenced example",
           {"subagent_type": "developer", "prompt": developer_prompt(fenced_example)}, False)
    subsection = plan_file("subsection.md", PLAN.replace("## acceptance_criteria\n- the matrix passes\n",
                                                         "## acceptance_criteria\n### unit\n- passes\n"))
    expect("developer acceptance section with a ### subheading",
           {"subagent_type": "developer", "prompt": developer_prompt(subsection)}, False)
    cased = plan_file("cased.md", PLAN.replace("## acceptance_criteria\n", "## Acceptance_Criteria  \n")
                      .replace("## test_plan\n", "## TEST_PLAN\n"))
    expect("developer plan headings case-insensitive with trailing spaces",
           {"subagent_type": "developer", "prompt": developer_prompt(cased)}, False)

    for model_only in ({"model": "claude-sonnet-5", "prompt": developer_prompt(full)},
                       {"model": "opus", "prompt": "anything"}, {"model": "haiku", "description": "quick fix"}):
        expect(f"bare model {model_only.get('model')}", model_only, True)

    for untouched in ("Explore", "Plan", "general-purpose", "claude-code-guide", "implementer",
                      "implementer-hard", "implementer-opus", "commander-opus"):
        expect(f"{untouched} untouched", {"subagent_type": untouched, "prompt": "just do it"}, False)
    expect("developer prompt not a string", {"subagent_type": "developer", "prompt": 42}, False)
    expect("developer without prompt", {"subagent_type": "developer"}, False)
    expect("no type and no model", {"prompt": "no subagent type and no model at all"}, False)

    spot = expect("developer spot", {"subagent_type": "developer", "prompt": "fix it"}, True)
    checks += 1
    needles = ["plan_file", "delegate"]
    missing = [n for n in needles if n not in spot]
    if missing:
        bad += 1
        print(f"SPOT developer missing={missing} -> {spot[:400]}")

    spot = expect("developer markers spot", {"subagent_type": "developer",
                                             "prompt": developer_prompt(plan_file("bare.md", "# Plan\n"))}, True)
    checks += 1
    needles = ["acceptance_criteria", "test_plan", "verify --", "may not touch"]
    missing = [n for n in needles if n not in spot]
    if missing:
        bad += 1
        print(f"SPOT markers missing={missing} -> {spot[:400]}")

    spot = expect("runner spot", {"subagent_type": "codex-runner", "prompt": "review"}, True)
    checks += 1
    missing = [n for n in ("mode", "plan_file", "project_path") if n not in spot]
    if missing:
        bad += 1
        print(f"SPOT runner missing={missing} -> {spot[:400]}")

    spot = expect("bare model spot", {"model": "sonnet", "prompt": "do it"}, True)
    checks += 1
    if "developer" not in spot:
        bad += 1
        print(f"SPOT bare model does not name developer -> {spot[:300]}")

garbage = [
    "", "not json", "null", "[]", "5",
    '{"tool_name":"Agent"}',
    '{"tool_name":"Agent","tool_input":null}',
    '{"tool_name":"Bash","tool_input":{"subagent_type":"developer","prompt":"nope"}}',
    '{"tool_name":"Agent","tool_input":{"subagent_type":42,"prompt":"nope"}}',
    '{"tool_name":"Agent","tool_input":[1,2,3]}',
]
for raw in garbage:
    checks += 1
    done = subprocess.run(["python3", hook], input=raw, capture_output=True, text=True, timeout=10)
    if not (done.returncode == 0 and not done.stderr and done.stdout == ""):
        bad += 1
        print(f"garbage {raw[:60]!r} -> rc={done.returncode} out={done.stdout[:60]!r} err={done.stderr[-160:]!r}")

print(f"hook: {hook}\nchecks: {checks}, slowest run: {slowest * 1000:.0f} ms, FAILURES: {bad}")
print(("FAIL " if bad else "PASS ") + f"{checks - bad}/{checks}")
sys.exit(1 if bad else 0)
