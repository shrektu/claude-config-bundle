#!/usr/bin/env python3
"""Regression matrix for bin/repo-facts (pass another path as argv[1])."""
import json, os, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
script = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(HERE), "bin", "repo-facts")
MAX_LINES = 40
MAX_CHARS = 1600
ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull}


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def repo(base, name, branch="main"):
    path = os.path.join(base, name)
    os.makedirs(path, exist_ok=True)
    done = subprocess.run(("git", "init", "-q", "-b", branch), cwd=path, capture_output=True, text=True, env=ENV)
    if done.returncode != 0:
        raise SystemExit(f"fixture setup failed: git init in {path}\n{done.stderr}")
    return path


def run(target=None, cwd=None, stdin="", env=None):
    args = ["python3", script] + ([target] if target else [])
    done = subprocess.run(args, input=stdin, capture_output=True, text=True, timeout=30,
                          cwd=cwd, env={**ENV, **(env or {})})
    return done.returncode, done.stdout, done.stderr


def python_fixture(base):
    path = repo(base, "py_repo", "main")
    write(os.path.join(path, "pyproject.toml"),
          '[project]\nname = "x"\nrequires-python = ">=3.11"\n')
    write(os.path.join(path, ".python-version"), "3.11.9\n")
    write(os.path.join(path, "uv.lock"),
          '[[package]]\nname = "fastapi"\nversion = "0.133.1"\n\n'
          '[[package]]\nname = "pytest"\nversion = "9.0.2"\n\n'
          '[[package]]\nname = "ruff"\nversion = "0.15.4"\n\n'
          '[[package]]\nname = "SQLAlchemy"\nversion = "2.0.47"\n')
    site = os.path.join(path, ".venv", "lib", "python3.11", "site-packages")
    for dist in ("fastapi-0.133.1", "pytest-8.0.0", "sqlalchemy-2.0.47"):
        write(os.path.join(site, dist + ".dist-info", "METADATA"), "Name: x\n")
    return path


def node_fixture(base):
    path = repo(base, "node_repo", "feature/x")
    write(os.path.join(path, "package.json"), json.dumps({
        "name": "web", "engines": {"node": ">=20"},
        "scripts": {"dev": "vite", "build": "vite build", "test": "vitest run"},
    }))
    write(os.path.join(path, "package-lock.json"), json.dumps({
        "lockfileVersion": 3,
        "packages": {
            "": {"name": "web"},
            "node_modules/react": {"version": "19.2.0"},
            "node_modules/vitest": {"version": "3.2.4"},
            "node_modules/typescript": {"version": "5.9.3"},
            "node_modules/vite/node_modules/react": {"version": "18.0.0"},
        },
    }))
    write(os.path.join(path, "node_modules", "react", "package.json"), json.dumps({"version": "19.0.0"}))
    write(os.path.join(path, "node_modules", "typescript", "package.json"), json.dumps({"version": "5.9.3"}))
    return path


def rust_fixture(base):
    path = repo(base, "rust_repo", "feature/rust")
    write(os.path.join(path, "Cargo.toml"),
          '[package]\nname = "demo"\nedition = "2021"\nrust-version = "1.82"\n\n'
          '[dependencies]\nserde = "1"\nsparsecrate = "2"\nmissingcrate = "3"\n'
          'gitcrate = { git = "https://example.com/g.git" }\n'
          'localcrate = { path = "../localcrate" }\n'
          'otherreg = "4"\n')
    write(os.path.join(path, "Cargo.lock"),
          '[[package]]\nname = "serde"\nversion = "1.0.210"\n'
          'source = "registry+https://github.com/rust-lang/crates.io-index"\n\n'
          '[[package]]\nname = "sparsecrate"\nversion = "2.1.0"\nsource = "sparse+https://index.crates.io/"\n\n'
          '[[package]]\nname = "missingcrate"\nversion = "3.0.0"\n'
          'source = "registry+https://github.com/rust-lang/crates.io-index"\n\n'
          '[[package]]\nname = "gitcrate"\nversion = "0.1.0"\nsource = "git+https://example.com/g.git#abc"\n\n'
          '[[package]]\nname = "localcrate"\nversion = "0.2.0"\n\n'
          '[[package]]\nname = "otherreg"\nversion = "4.0.0"\n'
          'source = "registry+https://my.registry.example/index"\n')
    cargo_home = os.path.join(base, "fake_cargo")
    registry = os.path.join(cargo_home, "registry", "src", "index.crates.io-6f17d22bba15001f")
    write(os.path.join(registry, "serde-1.0.210", "Cargo.toml"), '[package]\nname = "serde"\n')
    write(os.path.join(registry, "sparsecrate-2.1.0", "Cargo.toml"), '[package]\nname = "sparsecrate"\n')
    return path, cargo_home


def misc_fixture(base):
    path = repo(base, "misc_repo", "hotfix/y")
    write(os.path.join(path, "go.mod"),
          "module example.com/m\n\ngo 1.23\n\nrequire (\n\tgithub.com/gin-gonic/gin v1.10.0\n"
          "\tgolang.org/x/sync v0.8.0 // indirect\n)\n")
    write(os.path.join(path, "platformio.ini"),
          "[env:esp32]\nplatform = espressif32\nframework = arduino\nboard = esp32dev\n")
    write(os.path.join(path, "CMakeLists.txt"), "cmake_minimum_required(VERSION 3.20)\nproject(demo C)\n")
    write(os.path.join(path, ".tool-versions"), "nodejs 22.11.0\npython 3.12.1\n")
    write(os.path.join(path, ".nvmrc"), "22\n")
    write(os.path.join(path, "Makefile"),
          ".PHONY: test lint\nCFLAGS := -O2\ntest:\n\tpytest\nlint:\n\truff check .\n"
          "%.o: %.c\n\t$(CC) -c $<\ninternal-helper:\n\ttrue\n")
    return path


def pnpm_fixture(base):
    path = repo(base, "pnpm_repo", "feature/pnpm")
    write(os.path.join(path, "package.json"), json.dumps({"name": "root", "scripts": {"build": "vite build"}}))
    write(os.path.join(path, "apps", "web", "package.json"), json.dumps({"name": "web"}))
    write(os.path.join(path, "pnpm-lock.yaml"), """lockfileVersion: '9.0'

importers:

  .:
    dependencies:
      react:
        specifier: ^19.2.0
        version: 19.2.0
      typescript:
        specifier: ^5.9.3
        version: 5.9.3

  apps/web:
    dependencies:
      react:
        specifier: ^18.0.0
        version: 18.0.0

packages:

  react@18.0.0:
    resolution: {integrity: sha512-old}

  react@19.2.0:
    resolution: {integrity: sha512-new}
""")
    return path


def cargo_ambiguous_fixture(base):
    path = repo(base, "rust_ambiguous", "feature/amb")
    write(os.path.join(path, "Cargo.toml"),
          '[package]\nname = "demo"\nedition = "2024"\n\n[dependencies]\nrand = "0.9"\n')
    write(os.path.join(path, "Cargo.lock"),
          '[[package]]\nname = "rand"\nversion = "0.8.5"\n'
          'source = "registry+https://github.com/rust-lang/crates.io-index"\n\n'
          '[[package]]\nname = "rand"\nversion = "0.9.0"\n'
          'source = "registry+https://github.com/rust-lang/crates.io-index"\n')
    return path


def monorepo_fixture(base):
    path = repo(base, "mono_repo", "feature/mono")
    write(os.path.join(path, "apps", "api", "pyproject.toml"),
          '[project]\nname = "api"\nrequires-python = ">=3.12"\n')
    write(os.path.join(path, "apps", "api", "uv.lock"), '[[package]]\nname = "httpx"\nversion = "0.28.1"\n')
    write(os.path.join(path, "packages", "lib", "package.json"),
          json.dumps({"name": "lib", "scripts": {"build": "tsc"}}))
    write(os.path.join(path, "packages", "lib", "package-lock.json"), json.dumps({
        "lockfileVersion": 3, "packages": {"node_modules/typescript": {"version": "5.8.0"}}}))
    write(os.path.join(path, "docs", "notes.md"), "no manifest here\n")
    return path


def check(label, condition, detail=""):
    global bad
    if not condition:
        bad += 1
        print(f"FAIL {label} {detail}")


def budget(label, out):
    lines = out.splitlines()
    check(f"{label}: line budget", len(lines) <= MAX_LINES, f"{len(lines)} lines")
    check(f"{label}: char budget", len(out) <= MAX_CHARS, f"{len(out)} chars")


bad = 0
slowest = 0.0
with tempfile.TemporaryDirectory() as base:
    py = python_fixture(base)
    node = node_fixture(base)
    rust, cargo_home = rust_fixture(base)
    misc = misc_fixture(base)
    mono = monorepo_fixture(base)
    pnpm = pnpm_fixture(base)
    ambiguous = cargo_ambiguous_fixture(base)
    plain = os.path.join(base, "plain")
    os.makedirs(plain)

    t0 = time.time()
    rc, out, err = run(py)
    slowest = max(slowest, time.time() - t0)
    check("python: exit", rc == 0 and not err, f"rc={rc} err={err[-200:]}")
    for needle in ("requires-python=>=3.11", ".python-version=3.11.9", "venv=.venv(python3.11)",
                   "fastapi 0.133.1", "pytest locked=9.0.2 installed=8.0.0 MISMATCH",
                   "ruff locked=0.15.4 not installed", "sqlalchemy 2.0.47",
                   "NOT a work branch", "branch=main"):
        check("python: fact", needle in out, f"missing {needle!r} in:\n{out}")
    budget("python", out)

    rc, out, err = run(node)
    check("node: exit", rc == 0 and not err, f"rc={rc} err={err[-200:]}")
    for needle in ("engines.node=>=20", "lock=package-lock.json", "npm scripts: dev, build, test",
                   "react locked=19.2.0 installed=19.0.0 MISMATCH", "vitest locked=3.2.4 not installed",
                   "typescript 5.9.3", "branch=feature/x"):
        check("node: fact", needle in out, f"missing {needle!r} in:\n{out}")
    check("node: work branch quiet", "NOT a work branch" not in out, out)
    budget("node", out)

    rc, out, err = run(rust, env={"CARGO_HOME": cargo_home})
    check("rust: exit", rc == 0 and not err, f"rc={rc} err={err[-200:]}")
    for needle in ("edition=2021", "rust-version=1.82", "serde 1.0.210 installed",
                   "sparsecrate 2.1.0 installed", "missingcrate 3.0.0 not fetched",
                   "gitcrate 0.1.0 git-source (unverified)", "localcrate path=../localcrate",
                   "otherreg 4.0.0 unverified"):
        check("rust: fact", needle in out, f"missing {needle!r} in:\n{out}")
    budget("rust", out)

    rc, out, err = run(rust, env={"CARGO_HOME": os.path.join(base, "no_cargo_home")})
    check("rust: empty cargo home", "serde 1.0.210 unverified" in out, out)

    rc, out, err = run(misc)
    check("misc: exit", rc == 0 and not err, f"rc={rc} err={err[-200:]}")
    for needle in ("go=1.23", "github.com/gin-gonic/gin v1.10.0", "platform=espressif32",
                   "framework=arduino", "board=esp32dev", "cmake: minimum=3.20",
                   "nodejs 22.11.0", ".nvmrc: 22", "make targets: test, lint, internal-helper"):
        check("misc: fact", needle in out, f"missing {needle!r} in:\n{out}")
    check("misc: no indirect require", "golang.org/x/sync" not in out, out)
    check("misc: no pattern target", "%.o" not in out and "CFLAGS" not in out, out)
    budget("misc", out)

    rc, out, err = run(mono)
    check("mono: exit", rc == 0 and not err, f"rc={rc} err={err[-200:]}")
    for needle in ("[apps/api] python: requires-python=>=3.12", "[apps/api] python: requires-python=>=3.12 "
                   "no project venv", "httpx locked=0.28.1 not installed", "[packages/lib] node",
                   "[packages/lib] node: no node_modules", "typescript locked=5.8.0 not installed"):
        check("mono: fact", needle in out, f"missing {needle!r} in:\n{out}")
    check("mono: no docs prefix", "[docs/" not in out, out)
    budget("mono", out)

    rc, out, err = run(pnpm)
    check("pnpm: exit", rc == 0 and not err, f"rc={rc} err={err[-200:]}")
    for needle in ("react locked=19.2.0 not installed", "typescript locked=5.9.3 not installed"):
        check("pnpm: root importer", needle in out, f"missing {needle!r} in:\n{out}")
    root_lines = [line for line in out.splitlines() if line.startswith("node ")]
    check("pnpm: no foreign importer version", root_lines and "18.0.0" not in " ".join(root_lines),
          f"root node lines: {root_lines}")
    rc, out, err = run(os.path.join(pnpm, "apps", "web"))
    check("pnpm: subdir importer", "react locked=18.0.0 not installed" in out, out)
    check("pnpm: subdir prefix", "[apps/web]" in out, out)
    check("pnpm: subdir ignores root importer", "19.2.0" not in out.split("[apps/web]", 1)[1].split("\n")[0], out)

    rc, out, err = run(ambiguous, env={"CARGO_HOME": cargo_home})
    check("cargo: ambiguous versions", "rand locked=0.8.5|0.9.0 ambiguous" in out, out)
    check("cargo: ambiguous is never installed", "rand 0.9.0 installed" not in out, out)

    rc, out, err = run(os.path.join(mono, "apps", "api"))
    check("explicit subproject: exit", rc == 0 and not err, f"rc={rc} err={err[-200:]}")
    facts = [line for line in out.splitlines() if line.startswith("[")]
    check("explicit subproject: primary first", bool(facts) and facts[0].startswith("[apps/api]"),
          f"first prefixed line: {facts[:1]}")
    check("explicit subproject: not duplicated", out.count("[apps/api] python: requires-python=>=3.12") == 1, out)
    check("explicit subproject: root still scanned", "[packages/lib] node" in out, out)

    rc, out, err = run(plain)
    check("non-repo: silent", rc == 0 and out == "" and not err, f"rc={rc} out={out!r} err={err!r}")
    rc, out, err = run(os.path.join(base, "does-not-exist"))
    check("missing path: silent", rc == 0 and out == "" and not err, f"rc={rc} out={out!r}")

    payload = json.dumps({"hook_event_name": "SessionStart", "cwd": py, "effort": {"level": "xhigh"},
                          "session_id": "abc", "transcript_path": "/tmp/t.jsonl"})
    t0 = time.time()
    rc, out, err = run(stdin=payload, cwd=plain)
    slowest = max(slowest, time.time() - t0)
    check("hook: exit", rc == 0 and not err, f"rc={rc} err={err[-200:]}")
    check("hook: effort", "effort=xhigh" in out, out)
    check("hook: repo", f"repo: {py}" in out, out)
    budget("hook", out)

    started = time.monotonic()
    with subprocess.Popen(("sleep", "5"), stdout=subprocess.PIPE) as feeder:
        done = subprocess.run(("python3", script, py), stdin=feeder.stdout, capture_output=True, text=True, timeout=30, env=ENV)
        feeder.kill()
    check("open stdin pipe without data does not block the CLI", done.returncode == 0
          and time.monotonic() - started < 3 and done.stdout.startswith("repo:"))
    rc, out, err = run(stdin=json.dumps({"hook_event_name": "SessionStart", "cwd": plain}))
    check("hook: non-repo silent", rc == 0 and out == "" and not err, f"rc={rc} out={out!r}")

    rc, out, err = run(stdin=json.dumps({"hook_event_name": "SessionStart", "cwd": py, "effort": "high"}))
    check("hook: string effort", "effort=high" in out, out)

    rc, out, err = run(cwd=node, stdin="this is not json at all")
    check("cli: non-json stdin falls back to cwd", "branch=feature/x" in out, out)

    rc, out, err = run(cwd=py, stdin="")
    check("cli: no argument uses cwd", f"repo: {py}" in out, out)

    for raw in ("", "null", "[]", "42", "not json", '{"hook_event_name":"SessionStart"}',
                '{"hook_event_name":"SessionStart","cwd":42}', '{"hook_event_name":"Stop","cwd":"/nope"}'):
        done = subprocess.run(["python3", script], input=raw, capture_output=True, text=True, timeout=30,
                              cwd=plain, env=ENV)
        check("garbage", done.returncode == 0 and not done.stderr and done.stdout == "",
              f"{raw[:40]!r} -> rc={done.returncode} out={done.stdout[:80]!r} err={done.stderr[-120:]!r}")

print(f"script: {script}\nslowest run: {slowest * 1000:.0f} ms, FAILURES: {bad}")
print("FAIL" if bad else "PASS")
sys.exit(1 if bad else 0)
