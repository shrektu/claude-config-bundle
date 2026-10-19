from __future__ import annotations

import ast

import pytest
from magic_numbers import (
    MagicHit,
    MagicRule,
    literal_key,
    python_explained_lines,
    python_magic_hits,
    token_magic_hits,
)
from source_lexer import StaticLanguage, tokenize_source

NATIVE = StaticLanguage.NATIVE
SCRIPT = StaticLanguage.SCRIPT
COMPARISON = MagicRule.COMPARISON
REPEATED = MagicRule.REPEATED
DELAY = MagicRule.DELAY
EVERYWHERE = frozenset(range(1, 200))


def token_hits(
    text: str,
    language: StaticLanguage = NATIVE,
    changed: frozenset[int] = EVERYWHERE,
) -> list[MagicHit]:
    return token_magic_hits(tokenize_source(text, language), language, changed)


def python_hits(
    text: str, changed: frozenset[int] = EVERYWHERE
) -> list[MagicHit]:
    return python_magic_hits(ast.parse(text), changed, text)


def of_rule(hits: list[MagicHit], rule: MagicRule) -> list[MagicHit]:
    return [hit for hit in hits if hit.rule is rule]


def thrice(line: str) -> str:
    return (line + "\n") * 3


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("10U", 10),
        ("0x48", 72),
        ("0x10", 16),
        ("0xFFul", 255),
        ("0b11", 3),
        ("1'000", 1000),
        ("1_000", 1000),
        ("1e3", 1000.0),
        ("2.5f", 2.5),
        (".5", 0.5),
        ("9007199254740993n", 9007199254740993),
        ("0x1.8p3", None),
        ("0x", None),
        ("abc", None),
    ],
)
def test_literal_key_values(text: str, expected: float | None) -> None:
    assert literal_key(text) == expected


def test_hex_and_decimal_share_a_key() -> None:
    text = "int a = 0x25;\nint b = 37;\nint c = 0x25;\n"
    assert token_hits(text) == [
        MagicHit(1, REPEATED, ("0x25",), 9),
        MagicHit(2, REPEATED, ("37",), 9),
        MagicHit(3, REPEATED, ("0x25",), 9),
    ]


def test_big_integers_stay_distinct() -> None:
    text = (
        "const a = 9007199254740992n;\n"
        "const b = 9007199254740993n;\n"
        "const c = 9007199254740992n;\n"
    )
    assert token_hits(text, SCRIPT) == []


@pytest.mark.parametrize(
    ("line", "column"),
    [
        ("int a = 37;", 9),
        ("return 37;", 8),
        ("x = a + 37;", 9),
        ("f(37 + a);", 3),
        ("y = cond ? 37 : a;", 12),
    ],
)
def test_value_on_three_lines_is_repeated(line: str, column: int) -> None:
    text = thrice(line)
    expected = [MagicHit(n, REPEATED, ("37",), column) for n in (1, 2, 3)]
    assert of_rule(token_hits(text), REPEATED) == expected


def test_value_on_two_lines_is_not_repeated() -> None:
    assert token_hits("int a = 37;\nint b = 37;\n") == []


def test_same_value_twice_on_one_line_counts_once() -> None:
    assert token_hits("int a = 26, b = 26;\nint c = 26;\n") == []


def test_only_changed_lines_are_reported_but_all_are_counted() -> None:
    hits = token_hits(thrice("int a = 37;"), changed=frozenset({3}))
    assert hits == [MagicHit(3, REPEATED, ("37",), 9)]


def test_line_lists_every_repeated_value_on_it() -> None:
    text = "int a = 37, b = 55;\nint c = 37;\nint d = 55;\nint e = 37 + 55;\n"
    hits = of_rule(token_hits(text), REPEATED)
    assert hits[0] == MagicHit(1, REPEATED, ("37", "55"), 9)
    assert hits[-1] == MagicHit(4, REPEATED, ("37", "55"), 9)


@pytest.mark.parametrize("value", ["60", "100", "3600", "2", "10", "1000"])
def test_scale_and_obvious_values_never_repeat_hits(value: str) -> None:
    assert token_hits(thrice(f"int a = {value};")) == []


@pytest.mark.parametrize(
    "line",
    [
        "f(-37);",
        "f((37));",
        "obj.m(a, 37);",
        "auto p = new Foo(1, 37);",
    ],
)
def test_call_arguments_never_count_for_repetition(line: str) -> None:
    assert token_hits(thrice(line)) == []


def test_keyword_condition_parenthesis_is_not_a_call() -> None:
    text = thrice("while (37) {}")
    assert of_rule(token_hits(text), REPEATED) != []


@pytest.mark.parametrize(
    "line",
    [
        "x = buf[37];",
        "x = buf[i + 37];",
        "int table[37];",
        "x = grid[1][37];",
        "x = f(a)[37];",
    ],
)
def test_indices_and_array_sizes_are_exempt(line: str) -> None:
    assert token_hits(thrice(line)) == []


@pytest.mark.parametrize(
    "line",
    [
        "y = v >> 37;",
        "y = v << 37;",
        "y = v & 37;",
        "y = 37 | v;",
        "y = v ^ 37;",
        "y = ~37;",
        "y &= 37;",
        "y <<= 37;",
        "y >>= 37;",
    ],
)
def test_bitwise_operands_are_exempt(line: str) -> None:
    assert token_hits(thrice(line)) == []


@pytest.mark.parametrize(
    "line",
    [
        "std::array<int, 37> a;",
        "Foo<37>();",
        "std::vector<std::array<int, 37>> v;",
    ],
)
def test_template_arguments_are_exempt(line: str) -> None:
    assert token_hits(thrice(line)) == []


@pytest.mark.parametrize(
    "text",
    [
        "#define LIMIT 37\n",
        "#define CHECK(x) ((x) > 37)\n",
        "enum State { IDLE = 37, BUSY };\n",
        "static const int kLimit = 37;\n",
        "const int MAX_A = 37;\n",
    ],
)
def test_constant_definitions_do_not_count(text: str) -> None:
    assert token_hits(text + "int a = 37;\nint b = 37;\n") == []


def test_function_like_define_body_excluded() -> None:
    assert token_hits("#define CHECK(x) ((x) > 37)\n") == []


def test_other_directives_are_ignored() -> None:
    text = "#if VERSION > 5\n#pragma pack(4)\n#endif\n"
    assert token_hits(text) == []


@pytest.mark.parametrize(
    ("text", "values", "column"),
    [
        ("if (temp > 37) {}", ("37",), 12),
        ("if (temp >= 37) {}", ("37",), 13),
        ("if (temp < 37) {}", ("37",), 12),
        ("if (temp <= 37) {}", ("37",), 13),
        ("if (temp == 37) {}", ("37",), 13),
        ("if (temp != 37) {}", ("37",), 13),
        ("if (37 < temp) {}", ("37",), 5),
        ("ok = 37 == temp;", ("37",), 6),
        ("return temp > 0x25;", ("0x25",), 15),
        ("foo(temp > 37);", ("37",), 12),
        ("if (a > 37 && b < 99) {}", ("37", "99"), 9),
    ],
)
def test_comparison_operand_is_flagged(
    text: str, values: tuple[str, ...], column: int
) -> None:
    assert token_hits(text) == [MagicHit(1, COMPARISON, values, column)]


@pytest.mark.parametrize(
    "text", ["if (count === 7) {}", "if (count !== 7) {}"]
)
def test_strict_comparison_in_script_is_flagged(text: str) -> None:
    assert token_hits(text, SCRIPT) == [MagicHit(1, COMPARISON, ("7",), 15)]


@pytest.mark.parametrize(
    "text",
    ["x == -1", "x != 0", "x < 1", "x >= 1.0", "0 == x", "x > 0x0", "x < 1U"],
)
def test_obvious_comparison_values_are_not_flagged(text: str) -> None:
    assert token_hits(f"if ({text}) {{}}") == []


def test_negative_comparison_literal() -> None:
    assert token_hits("if (x > -5) {}") == [
        MagicHit(1, COMPARISON, ("-5",), 10)
    ]
    assert token_hits("if (x == -1) {}") == []


def test_parenthesised_operand_is_flagged() -> None:
    assert token_hits("if (x < (5)) {}") == [
        MagicHit(1, COMPARISON, ("5",), 10)
    ]


@pytest.mark.parametrize(
    "text",
    ["x + 5 < y", "x < 5 * k", "x < 5 + 1", "a - 5 < y", "x < f(5)"],
)
def test_partial_operand_is_not(text: str) -> None:
    assert of_rule(token_hits(f"if ({text}) {{}}"), COMPARISON) == []


@pytest.mark.parametrize(
    "text", ["y = x >> 4;", "y <<= 3;", "y = x << 5;", "y >>= 6;"]
)
def test_shift_operators_are_not_comparisons(text: str) -> None:
    assert token_hits(text) == []


def test_greater_equal_is_a_comparison() -> None:
    assert token_hits("if (a >= 5) {}") == [
        MagicHit(1, COMPARISON, ("5",), 10)
    ]


@pytest.mark.parametrize(
    "text",
    ["std::array<int, 4> a;", "Foo<8>();", "auto v = Foo<8>(1, 2);"],
)
def test_template_arguments_are_not_comparisons(text: str) -> None:
    assert token_hits(text) == []


def test_comparison_that_is_also_repeated_gives_both_rules() -> None:
    hits = token_hits(thrice("if (x > 37) {}"))
    assert hits[:2] == [
        MagicHit(1, COMPARISON, ("37",), 9),
        MagicHit(1, REPEATED, ("37",), 9),
    ]
    assert len(hits) == 6


def test_numbers_in_strings_and_comments_are_ignored() -> None:
    text = 'if (x > "37") {}\n// if (x > 37)\n'
    assert token_hits(text) == []


def test_python_value_on_three_lines_is_repeated() -> None:
    text = "a = 37\nb = foo + 37\nc = 37.0\n"
    expected = [
        MagicHit(1, REPEATED, ("37",), 5),
        MagicHit(2, REPEATED, ("37",), 11),
        MagicHit(3, REPEATED, ("37.0",), 5),
    ]
    assert python_hits(text) == expected


def test_python_value_on_two_lines_is_not_repeated() -> None:
    assert python_hits("a = 37\nb = 37\n") == []


def test_python_changed_lines_filter() -> None:
    hits = python_hits("a = 37\nb = 37\nc = 37\n", frozenset({2}))
    assert hits == [MagicHit(2, REPEATED, ("37",), 5)]


def test_python_comparisons_are_left_to_ruff() -> None:
    assert python_hits("if x > 37:\n    pass\n") == []


def test_python_negative_literal_is_one_value() -> None:
    text = "a = -37\nb = -37\nc = -37\nd = 37\n"
    hits = python_hits(text)
    assert [hit.values for hit in hits] == [("-37",)] * 3


def test_nested_python_constant_is_not_counted() -> None:
    text = "if X:\n    TIMEOUT = 37\na = 37\nb = 37\n"
    assert python_hits(text) == []


def test_python_enum_members_and_annotated_constants_do_not_count() -> None:
    text = (
        "from enum import Enum\n\n\nclass C(Enum):\n    A = 37\n\n"
        "LIMIT: int = 37\na = 37\nb = 37\n"
    )
    assert python_hits(text) == []


@pytest.mark.parametrize(
    "line",
    [
        "foo(37)",
        "foo(a, b=37)",
        "foo(-37)",
        "x = data[14:37]",
        "x = data[37]",
        "x = v >> 37",
        "x = v & 37",
        "x = ~37",
        "x |= 37",
    ],
)
def test_python_exempt_contexts_never_count(line: str) -> None:
    assert python_hits(thrice(line)) == []


def test_python_partial_call_argument_counts() -> None:
    hits = python_hits(thrice("foo(37 + a)"))
    assert len(hits) == 3


@pytest.mark.parametrize("value", ["60", "100", "3600", "2", "10"])
def test_python_scale_and_obvious_values_never_repeat(value: str) -> None:
    assert python_hits(thrice(f"a = {value}")) == []


def test_python_float_value_repeats_like_an_integer() -> None:
    hits = python_hits(thrice("a = 6.5"))
    assert [hit.values for hit in hits] == [("6.5",)] * 3


def test_parenthesised_negative_literal_keeps_its_sign() -> None:
    text = "int x = (-37);\nint y = -37;\nint z = -37;\n"
    assert token_hits(text) == [
        MagicHit(1, REPEATED, ("-37",), 11),
        MagicHit(2, REPEATED, ("-37",), 10),
        MagicHit(3, REPEATED, ("-37",), 10),
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [("010", 8), ("0", 0), ("00", 0), ("0.5", 0.5), ("01.5e3", 1500.0)],
)
def test_c_octal_literal_key(text: str, expected: float) -> None:
    assert literal_key(text) == expected


def test_octal_and_decimal_share_a_key() -> None:
    text = "int a = 010;\nint b = 8;\nint c = 8;\n"
    assert [hit.line for hit in token_hits(text)] == [1, 2, 3]


def test_magic_column_points_at_first_literal() -> None:
    comparison = token_hits("int a;\n    if (x > 37 || y < 55) {}\n")
    repeated = token_hits("a = 37; b = 55;\n    c = 37;\n    d = 37;\n")
    python = python_hits("a = 1\nb = x + 37\nc = 37\nd = 5 + 37 + 55\n")

    assert [(hit.line, hit.column) for hit in comparison] == [(2, 13)]
    assert [(hit.line, hit.column) for hit in repeated] == [
        (1, 5),
        (2, 9),
        (3, 9),
    ]
    assert [(hit.line, hit.column) for hit in python] == [
        (2, 9),
        (3, 5),
        (4, 9),
    ]


def test_jsx_text_number_is_not_a_comparison() -> None:
    text = "export const view = <div>37</div>;\n"

    assert token_hits(text, SCRIPT) == []


def test_jsx_expression_comparison_stays_flagged() -> None:
    text = "export const view = <div>{n > 37}</div>;\n"

    hits = token_hits(text, SCRIPT)

    assert [(h.line, h.rule, h.values) for h in hits] == [
        (1, COMPARISON, ("37",))
    ]


def test_python_column_counts_characters_not_bytes() -> None:
    hits = python_hits("é = x + 77\nb = 77\nc = 77\n")

    assert [(hit.line, hit.column) for hit in hits] == [(1, 9), (2, 5), (3, 5)]


def delay_values(hits: list[MagicHit]) -> list[tuple[int, tuple[str, ...]]]:
    return [(h.line, h.values) for h in of_rule(hits, DELAY)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("delay(200);", ["200"]),
        ("delayMicroseconds(50);", ["50"]),
        ("k_sleep(K_MSEC(10));", ["10"]),
        ("k_msleep(25);", ["25"]),
        ("vTaskDelay(pdMS_TO_TICKS(150));", ["150"]),
        ("HAL_Delay(40);", ["40"]),
        ("setTimeout(fn, 500);", ["500"]),
        ("setInterval(tick, 750);", ["750"]),
        ("usleep(300);", ["300"]),
        (
            "std::this_thread::sleep_for(std::chrono::milliseconds(200));",
            ["200"],
        ),
        ("delay(-15);", ["-15"]),
        ("delay(1.5);", ["1.5"]),
        ("delay(a + 7);", ["7"]),
        ("delay(f(g(7)));", ["7"]),
        ("delay(25, 35);", ["25", "35"]),
    ],
)
def test_delay_literals_are_reported_per_callee_form(
    text: str, expected: list[str]
) -> None:
    assert delay_values(token_hits(text)) == [(1, tuple(expected))]


@pytest.mark.parametrize(
    "text",
    [
        "delay(0);",
        "delay(DEBOUNCE_MS);",
        "delay(0x0);",
        "delay(f(0));",
        "#define PAUSE delay(200)",
        "delay(buf[200]);",
        "delay(v >> 3);",
    ],
)
def test_exempt_delay_arguments_are_not_reported(text: str) -> None:
    assert delay_values(token_hits(text)) == []


def test_scale_operand_of_a_delay_is_exempt_and_the_rest_is_not() -> None:
    hits = token_hits("sleep(5 * 60);\nsleep(1000 * 2);\nsleep(3600 / 4);\n")
    assert delay_values(hits) == [(1, ("5",)), (2, ("2",)), (3, ("4",))]


def test_plain_scale_value_as_a_delay_is_reported() -> None:
    assert delay_values(token_hits("sleep(60);")) == [(1, ("60",))]


def test_delay_constant_definition_is_exempt() -> None:
    assert delay_values(token_hits("const int SETTLE = sleep_for(200);")) == []


def test_delay_outside_the_argument_list_is_not_reported() -> None:
    assert delay_values(token_hits("delay(DEBOUNCE_MS); x = 200;")) == []


def test_delay_literal_reports_only_changed_lines() -> None:
    hits = token_hits("delay(200);\ndelay(300);\n", changed=frozenset({2}))
    assert delay_values(hits) == [(2, ("300",))]


def test_delay_literal_not_counted_for_repetition() -> None:
    hits = token_hits(thrice("delay(37);") + "int a = 37;\nint b = 37;\n")
    assert of_rule(hits, REPEATED) == []


def test_delay_literal_is_not_a_comparison() -> None:
    assert of_rule(token_hits("if (delay(200) > 37) {}"), COMPARISON) == [
        MagicHit(1, COMPARISON, ("37",), 17)
    ]


@pytest.mark.parametrize(
    "text",
    ["delayed(200);", "sleepy(5);", "my_delay(3);", "Delay(8);", "delay2(9);"],
)
def test_delay_callee_must_match_exactly(text: str) -> None:
    assert delay_values(token_hits(text)) == []


@pytest.mark.parametrize(
    "text",
    [
        "obj.delay(200);",
        "ns::sleep_for(5);",
        "this->delay(5);",
        "a.b.c.k_sleep(9);",
    ],
)
def test_member_delay_call_is_matched(text: str) -> None:
    assert len(delay_values(token_hits(text))) == 1


@pytest.mark.parametrize(
    "text",
    [
        "delay(200); // debounce",
        "delay(200); /* debounce */",
        "// settle time\ndelay(200);",
        "/* settle time */\ndelay(200);",
        "/* settle\n   time */\ndelay(200);",
        "// a\n// b\ndelay(200);",
    ],
)
def test_comment_explains_a_delay(text: str) -> None:
    assert delay_values(token_hits(text)) == []


def test_block_comment_above_explains() -> None:
    text = "/* settle\n   time */\ndelay(200);"
    assert delay_values(token_hits(text)) == []


def test_comment_two_lines_above_does_not_explain() -> None:
    assert delay_values(token_hits("// x\n\ndelay(200);")) == [(3, ("200",))]


def test_comment_in_string_does_not_explain() -> None:
    text = 'delay(200); s = "// no";'
    assert delay_values(token_hits(text)) == [(1, ("200",))]


def test_comment_after_code_does_not_explain_the_next_line() -> None:
    text = "x = 1; // note\ndelay(200);"
    assert delay_values(token_hits(text)) == [(2, ("200",))]


@pytest.mark.parametrize(
    "text",
    ["if (t > 37) // fever limit", "// fever limit\nif (t > 37)"],
)
def test_comment_explains_a_comparison(text: str) -> None:
    assert of_rule(token_hits(text), COMPARISON) == []


def test_comment_does_not_hide_repetition() -> None:
    text = "int a = 37; // x\n// y\nint b = 37;\nint c = 37;\n"
    assert [h.line for h in of_rule(token_hits(text), REPEATED)] == [1, 3, 4]


def test_python_delay_calls_are_reported() -> None:
    text = (
        "time.sleep(5)\n"
        "await asyncio.sleep(0.5)\n"
        "sleep(secs=7)\n"
        "sleep(5 * 60)\n"
        "sleep(0)\n"
        "sleep(DELAY)\n"
    )
    assert delay_values(python_hits(text)) == [
        (1, ("5",)),
        (2, ("0.5",)),
        (3, ("7",)),
        (4, ("5",)),
    ]


def test_python_delay_is_not_counted_for_repetition() -> None:
    text = thrice("sleep(37)") + "x = 37\ny = 37\n"
    assert of_rule(python_hits(text), REPEATED) == []


def test_python_delay_constant_definition_is_exempt() -> None:
    assert delay_values(python_hits("PAUSE = sleep(5)\n")) == []


def test_python_comment_explains_a_delay() -> None:
    text = "sleep(5)  \x23 settle\n\x23 relay\nsleep(6)\nsleep(7)\n"
    assert delay_values(python_hits(text)) == [(4, ("7",))]


def test_python_explained_lines_cover_comments_and_the_next_line() -> None:
    text = "x = 1  \x23 a\n\x23 b\ny = 2\nz = 3\n"
    assert python_explained_lines(text) == frozenset({1, 2, 3})


def test_python_explained_lines_on_tokenize_error() -> None:
    assert python_explained_lines('x = 1  \x23 a\ny = """abc\n') == frozenset()


CALLBACK_DELAYS = [
    ("setTimeout(() => { counter = 37; }, 500);", "500"),
    ("setTimeout(() => render(42), 250);", "250"),
    ("setTimeout(function () { counter = 37; }, 500);", "500"),
    ("setInterval(tick, () => { x = 37; }, 750);", "750"),
]


@pytest.mark.parametrize(("text", "expected"), CALLBACK_DELAYS)
def test_delay_callback_body_is_not_a_delay_argument(
    text: str, expected: str
) -> None:
    hits = token_hits(text, SCRIPT)
    assert delay_values(hits) == [(1, (expected,))]


def test_python_delay_lambda_body_is_not_a_delay_argument() -> None:
    hits = python_hits("sleep(lambda: x + 37, 5)\n")
    assert delay_values(hits) == [(1, ("5",))]
