from collections.abc import Callable, Mapping, Sequence

import pytest
from agy_context import (
    CallSites,
    changed_names,
    changed_paths,
    fit_lines,
    ordered_paths,
    select_call_sites,
)
from agy_workspace import GrepHit

LONG_PATH_LENGTH = 182


def file_diff(path: str, new_start: int, body: Sequence[str]) -> str:
    old_count = sum(1 for line in body if not line.startswith("+"))
    new_count = sum(1 for line in body if not line.startswith("-"))
    header = [
        f"diff --git a/{path} b/{path}",
        f"--- a/{path}",
        f"+++ b/{path}",
        f"@@ -{new_start},{old_count} +{new_start},{new_count} @@",
    ]
    return "\n".join([*header, *body]) + "\n"


def reader(images: Mapping[str, str]) -> Callable[[str], str | None]:
    return images.get


def more(count: int) -> str:
    return f"... {count} more"


def hit(name: str, path: str, line: int, text: str = "call()") -> GrepHit:
    return GrepHit(name, path, line, text)


def test_python_method_in_class_found_by_upward_scan() -> None:
    image = (
        "class Pricing:\n"
        "    def total(self, price):\n"
        "        base = price\n"
        "        return base * 3\n"
    )
    diff = file_diff(
        "pricing.py",
        3,
        [
            "         base = price",
            "-        return base * 2",
            "+        return base * 3",
        ],
    )

    names = changed_names(diff, reader({"pricing.py": image}))

    assert names == ["total", "Pricing"]


def test_python_top_level_def_changed_in_body() -> None:
    image = "X = 1\n\n\ndef total(price):\n    return price + 1\n"
    diff = file_diff(
        "pricing.py", 5, ["-    return price", "+    return price + 1"]
    )

    names = changed_names(diff, reader({"pricing.py": image}))

    assert names == ["total"]


def test_top_level_statement_change_names_nothing() -> None:
    image = "def other():\n    return 1\n\n\nif ready:\n    X = 2\n"
    diff = file_diff("pricing.py", 6, ["-    X = 1", "+    X = 2"])

    names = changed_names(diff, reader({"pricing.py": image}))

    assert names == []


def test_removed_definition_keeps_its_name() -> None:
    diff = file_diff(
        "pricing.py", 1, ["-def legacy_total(price):", "-    return price"]
    )

    names = changed_names(diff, reader({"pricing.py": "X = 1\n"}))

    assert names == ["legacy_total"]


def test_deleted_file_keeps_removed_definition_names() -> None:
    diff = (
        "diff --git a/gone.py b/gone.py\n"
        "deleted file mode 100644\n"
        "--- a/gone.py\n"
        "+++ /dev/null\n"
        "@@ -1,2 +0,0 @@\n"
        "-def vanished_total(price):\n"
        "-    return price\n"
    )

    names = changed_names(diff, reader({}))

    assert names == ["vanished_total"]


def test_typescript_function_definition() -> None:
    diff = file_diff(
        "cart.ts",
        1,
        ["+export function computeTotal(a: number): number {"],
    )

    assert changed_names(diff, reader({})) == ["computeTotal"]


def test_typescript_arrow_const_definition() -> None:
    diff = file_diff(
        "cart.ts",
        1,
        ["+export const applyDiscount = (price: number) => price * 2;"],
    )

    assert changed_names(diff, reader({})) == ["applyDiscount"]


def test_typescript_class_method_found_by_upward_scan() -> None:
    image = (
        "class Cart {\n"
        "  addItem(item: Item): void {\n"
        "    this.items.push(item);\n"
        "    this.count++;\n"
        "  }\n"
        "}\n"
    )
    diff = file_diff(
        "cart.ts", 3, ["     this.items.push(item);", "+    this.count++;"]
    )

    names = changed_names(diff, reader({"cart.ts": image}))

    assert names == ["addItem", "Cart"]


def test_multiline_arrow_function_name_found_from_body_change() -> None:
    image = "const total = (\n  a,\n) => {\n  return a * 3;\n};\n"
    diff = file_diff("cart.ts", 4, ["-  return a * 2;", "+  return a * 3;"])

    names = changed_names(diff, reader({"cart.ts": image}))

    assert names == ["total"]


def test_c_function_at_column_zero_found_from_body_change() -> None:
    image = (
        "static int compute_total(int price)\n{\n    return price * 3;\n}\n"
    )
    diff = file_diff(
        "pricing.c", 3, ["-    return price * 2;", "+    return price * 3;"]
    )

    names = changed_names(diff, reader({"pricing.c": image}))

    assert names == ["compute_total"]


def test_control_keywords_short_and_dunder_names_are_skipped() -> None:
    diff = file_diff(
        "mixed.py",
        1,
        [
            "+    if (ready) {",
            "+    for (item in items) {",
            "+def __init__(self):",
            "+def ab():",
        ],
    )

    assert changed_names(diff, reader({})) == []


def test_names_capped_in_first_seen_order() -> None:
    body = [f"+def func_{index:02d}():" for index in range(35)]
    diff = file_diff("many.py", 1, body)

    names = changed_names(diff, reader({}))

    assert names == [f"func_{index:02d}" for index in range(30)]


def test_changed_paths_cover_old_and_new_names() -> None:
    diff = (
        "diff --git a/old name.py b/new name.py\n"
        "similarity index 90%\n"
        "rename from old name.py\n"
        "rename to new name.py\n"
        "--- a/old name.py\t\n"
        "+++ b/new name.py\t\n"
        "@@ -1 +1 @@\n"
        "-X = 1\n"
        "+X = 2\n"
        "diff --git a/added.py b/added.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/added.py\n"
        "@@ -0,0 +1 @@\n"
        "+Y = 1\n"
    )

    assert changed_paths(diff) == {"old name.py", "new name.py", "added.py"}


def test_removed_dash_line_in_hunk_is_not_a_file_header() -> None:
    diff = file_diff("notes.sql", 1, ["--- a/fake.py", "+++ b/fake.py"])

    assert changed_paths(diff) == {"notes.sql"}


def test_call_sites_in_changed_files_excluded() -> None:
    hits = [
        hit("total", "pricing.py", 2),
        hit("total", "api.py", 5, "return pricing.total(price)"),
    ]

    sites = select_call_sites(["total"], hits, frozenset({"pricing.py"}))

    assert sites == CallSites(
        ["total:", "  api.py:5: return pricing.total(price)"], []
    )


def test_name_without_callers_reported_on_a_trailing_line() -> None:
    hits = [hit("total", "pricing.py", 2)]

    sites = select_call_sites(
        ["total", "orphan"], hits, frozenset({"pricing.py"})
    )

    assert sites.lines == []
    assert sites.all_lines() == [
        "No call sites in unchanged files: total, orphan"
    ]


def test_common_name_capped_per_name_and_total() -> None:
    names = [f"name_{index}" for index in range(11)]
    hits = [
        hit(name, f"caller_{line}.py", line)
        for name in names
        for line in range(1, 11)
    ]

    sites = select_call_sites(names, hits, frozenset())

    site_lines = [line for line in sites.lines if line.startswith("  ")]
    assert len(site_lines) == 80
    assert sites.lines.count("name_0:") == 1
    assert sum(1 for line in sites.lines if line.endswith(":")) == 10
    assert "name_10:" not in sites.lines
    assert sites.lines[8] == "  caller_8.py:8: call()"
    assert sites.lines[9] == "name_1:"


def test_site_text_cut_but_long_path_and_line_number_kept() -> None:
    path = "d/" * (LONG_PATH_LENGTH // 2) + "x.py"
    hits = [hit("total", path, 7, "y" * 400)]

    sites = select_call_sites(["total"], hits, frozenset())

    assert sites.lines[1] == f"  {path}:7: " + "y" * 160


def test_fit_lines_keeps_everything_that_fits() -> None:
    text = fit_lines("Header:", ["aa", "bb"], 100, more)

    assert text == "Header:\naa\nbb"


def test_fit_lines_cuts_on_line_boundary_with_marker() -> None:
    lines = ["aaaa", "bbbb", "cccc", "dddd", "eeee"]

    text = fit_lines("Header:", lines, 28, more)

    assert text == "Header:\naaaa\nbbbb\n... 3 more"


def test_fit_lines_exact_budget_is_kept_whole() -> None:
    text = fit_lines("Header:", ["aa", "bb"], len("Header:\naa\nbb"), more)

    assert text == "Header:\naa\nbb"


def test_fit_lines_empty_when_header_and_first_line_do_not_fit() -> None:
    assert fit_lines("Header:", ["aa", "bb"], 9, more) == ""


def test_fit_lines_counts_bytes_not_characters() -> None:
    text = fit_lines("H:", ["żż"] * 5, 20, more)

    assert text == "H:\nżż\n... 4 more"


def test_ordered_paths_puts_changed_directories_first() -> None:
    paths = ["z.py", "pkg/b.py", "pkg/a.py", "other/c.py", "a.py"]

    ordered = ordered_paths(paths, frozenset({"pkg/changed.py"}))

    assert ordered == ["pkg/a.py", "pkg/b.py", "a.py", "other/c.py", "z.py"]


def test_blank_first_changed_block_still_scans_enclosing_names() -> None:
    image = "def compute(a):\n    x = 1\n\n    return a + x\n"
    diff = file_diff(
        "calc.py",
        2,
        ["     x = 1", "+", "-    return a", "+    return a + x"],
    )

    names = changed_names(diff, reader({"calc.py": image}))

    assert names == ["compute"]


def test_suppressed_blank_context_line_is_not_a_changed_line() -> None:
    image = "def compute(a):\n    x = 1\n\n    return a + x\n"
    diff = file_diff("calc.py", 3, ["", "-    return a", "+    return a + x"])

    names = changed_names(diff, reader({"calc.py": image}))

    assert names == ["compute"]


def test_quoted_header_paths_are_unquoted_in_changed_paths() -> None:
    diff = (
        'diff --git "a/we\\"ird\\tname.py" "b/we\\"ird\\tname.py"\n'
        '--- "a/we\\"ird\\tname.py"\n'
        '+++ "b/we\\"ird\\tname.py"\n'
        "@@ -1 +1 @@\n"
        "-X = 1\n"
        "+X = 2\n"
        'diff --git "a/za\\305\\274\\303\\263.py"'
        ' "b/za\\305\\274\\303\\263.py"\n'
        'rename from "za\\305\\274\\303\\263.py"\n'
        'rename to "back\\\\slash.py"\n'
    )

    assert changed_paths(diff) == {
        'we"ird\tname.py',
        "zażó.py",
        "back\\slash.py",
    }


def test_quoted_path_post_image_is_read_by_its_real_name() -> None:
    image = "def total(price):\n    return price + 1\n"
    diff = (
        'diff --git "a/we\\"ird.py" "b/we\\"ird.py"\n'
        '--- "a/we\\"ird.py"\n'
        '+++ "b/we\\"ird.py"\n'
        "@@ -2 +2 @@\n"
        "-    return price\n"
        "+    return price + 1\n"
    )

    names = changed_names(diff, reader({'we"ird.py': image}))

    assert names == ["total"]


def test_column_zero_definition_with_inline_body_is_named() -> None:
    diff = file_diff(
        "pricing.c",
        1,
        ["+int compute_total(int price) { return price * 3; }"],
    )

    assert changed_names(diff, reader({})) == ["compute_total"]


def test_column_zero_prototype_is_not_a_definition() -> None:
    diff = file_diff("pricing.h", 1, ["+int compute_total(int price);"])

    assert changed_names(diff, reader({})) == []


@pytest.mark.parametrize(
    ("line", "name"),
    [
        ("    int getValue() const {", "getValue"),
        ("    void run() override {", "run"),
        ("    public void load() throws IOException {", "load"),
        ("    void save() throws IOException, SQLException {", "save"),
        ("    async fetchAll<T>(url: string): Promise<T[]> {", "fetchAll"),
    ],
)
def test_indented_method_with_qualifiers_or_generics_is_named(
    line: str, name: str
) -> None:
    diff = file_diff("Service.java", 1, [f"+{line}"])

    assert changed_names(diff, reader({})) == [name]


def test_indented_control_flow_is_still_not_a_method() -> None:
    diff = file_diff(
        "Service.java", 1, ["+    if (ready) {", "+    while (busy) {"]
    )

    assert changed_names(diff, reader({})) == []
