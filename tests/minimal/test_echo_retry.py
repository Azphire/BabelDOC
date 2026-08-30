"""The masthead exclusion rule and the bounded echo retry.

FD's staff-list role lines ("EDITOR-IN-CHIEF") were never offered to the
translator: their editorial typeface name contains "Mono", the formula-font
table claims every such font, and a line whose every character wears a
formula font is swallowed whole. The word-run rescue hands that class back.
The names beside them were offered and echoed; the retry gives each such
unit one explicit second ask within a budget, and a unit that should stand
as it is (a brand, an acronym) survives the retry unchanged.
"""

from __future__ import annotations

from types import SimpleNamespace

from babeldoc.format.pdf.document_il import il_version_1 as il
from babeldoc.format.pdf.document_il.midend.styles_and_formulas import (
    StylesAndFormulas,
)
from babeldoc.magazine import echo_retry


def formula(text: str, y_offset: float = 0.0) -> il.PdfFormula:
    return il.PdfFormula(
        pdf_character=[
            il.PdfCharacter(char_unicode=character, formula_layout_id=None)
            for character in text
        ],
        y_offset=y_offset,
        x_offset=0.0,
    )


def is_translatable(item: il.PdfFormula) -> bool:
    stage = object.__new__(StylesAndFormulas)
    return stage.is_translatable_formula(item)


def test_word_shaped_font_swallowed_lines_are_rescued() -> None:
    assert is_translatable(formula("EDITOR-IN-CHIEF"))
    assert is_translatable(formula("ADVISORS TO THE EDITOR"))
    assert is_translatable(formula("CREATIVE AND MARKETING"))
    # The digit rescue the rule always had still holds.
    assert is_translatable(formula("12, 34"))


def test_formula_shaped_runs_stay_formulas() -> None:
    # A single letter is what a variable looks like.
    assert not is_translatable(formula("W"))
    # Operators and digits mixed with letters are not a word run.
    assert not is_translatable(formula("E=mc2"))
    assert not is_translatable(formula("f(x) + 1"))
    # A raised run is a superscript whatever its characters are.
    assert not is_translatable(formula("AB", y_offset=2.0))


class FakeEngine:
    def __init__(self, reply: str):
        self.reply = reply
        self.calls = 0

    def llm_translate(self, prompt, rate_limit_params=None):
        self.calls += 1
        return self.reply


class HeldConfig:
    """Weak-referenceable stand-in for one run's translation config."""

    def __init__(self, switch: bool = True):
        self.lang_out = "zh"
        setattr(self, echo_retry.SWITCH, switch)


def config(tmp_path, switch: bool = True):
    return HeldConfig(switch)


def test_a_name_echo_earns_one_retry_and_accepts_a_rendering(tmp_path) -> None:
    engine = FakeEngine('{"output": "吉塔·巴特"}')
    text, outcome = echo_retry.attempt(config(tmp_path), engine, "Gita Bhatt")
    assert outcome == echo_retry.ACCEPTED
    assert text == "吉塔·巴特"
    assert engine.calls == 1


def test_a_unit_that_should_stand_survives_the_retry_unchanged(tmp_path) -> None:
    engine = FakeEngine('{"output": "IMF Publications"}')
    text, outcome = echo_retry.attempt(
        config(tmp_path), engine, "IMF Publications"
    )
    assert text is None
    assert outcome == echo_retry.EXHAUSTED


def test_a_target_script_unit_is_never_re_asked(tmp_path) -> None:
    engine = FakeEngine('{"output": "换一个"}')
    text, outcome = echo_retry.attempt(config(tmp_path), engine, "请阅读中文版!")
    assert text is None
    assert outcome == echo_retry.SKIP_SCRIPT
    assert engine.calls == 0


def test_the_budget_is_per_document_and_runs_out(tmp_path) -> None:
    held = config(tmp_path)
    engine = FakeEngine('{"output": "翻译"}')
    budget = int(echo_retry.load_echo_retry_config()["echo_retry_budget"])
    for _ in range(budget):
        _, outcome = echo_retry.attempt(held, engine, "Some Name")
        assert outcome == echo_retry.ACCEPTED
    _, outcome = echo_retry.attempt(held, engine, "Some Name")
    assert outcome == echo_retry.SKIP_BUDGET
    assert engine.calls == budget


def test_an_unusable_reply_keeps_the_pasteback(tmp_path) -> None:
    engine = FakeEngine("I would translate this as follows...")
    text, outcome = echo_retry.attempt(config(tmp_path), engine, "Peter Walker")
    assert text is None
    assert outcome == echo_retry.UNUSABLE


def test_the_switch_off_spends_nothing(tmp_path) -> None:
    engine = FakeEngine('{"output": "翻译"}')
    text, outcome = echo_retry.attempt(
        config(tmp_path, switch=False), engine, "Peter Walker"
    )
    assert text is None
    assert outcome == echo_retry.SKIP_SWITCH
    assert engine.calls == 0
