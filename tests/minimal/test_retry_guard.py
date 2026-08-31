"""The one acceptance test every single-unit retry passes through.

The two replies under test are the ones the B18 corpus actually produced. Both
were written into finished pages, both were cached, and both honoured every
check the channel that asked for them had: the CERN reply carries the ruled
string ``ERNCOURIER`` four sentences deep in invented copy about a courier
company, and the Courier reply is a grammatical Chinese sentence about the
magazine where the magazine's name was asked for.

The negative half matters more than the positive half here, because a guard
that refuses honest translations turns a hallucination into an untranslated
page. The measured extremes of the corpus stand beside the two hallucinations
as fixtures.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from babeldoc.magazine import retry_guard

# The two replies, exactly as they came back, and the unit each answered.
CERN_UNIT = "ERNCOURIER"
CERN_REPLY = (
    "在现代物流行业中，ERNCOURIER 作为一个领先的快递服务提供商，致力于为客户提供"
    "高效、可靠的运输解决方案。无论是国内还是国际运输，ERNCOURIER 都能确保包裹安全"
    "准时送达。我们的团队由经验丰富的专业人士组成，他们随时准备满足客户的需求。"
    "选择 ERNCOURIER，您将体验到无与伦比的服务质量和客户支持。"
)
COURIER_UNIT = "CourierT H E UNESCO"
COURIER_REPLY = "《信使》是由联合国教科文组织《信使》出版的杂志，旨在传播文化和教育的价值。"
COURIER_RULED = "联合国教科文组织《信使》"


class TestTheRepliesThatReachedThePage:
    def test_four_sentences_about_a_courier_company_are_refused(self):
        accepted, reason, evidence = retry_guard.accept(CERN_UNIT, CERN_REPLY)
        assert accepted is False
        assert reason == retry_guard.REJECTED_SENTENCES
        assert reason in retry_guard.REJECTION_REASONS
        assert evidence["source_sentences"] == 0
        assert evidence["output_sentences"] == 4

    def test_the_ruled_string_being_present_does_not_save_it(self):
        """The ladder's own check passes on this reply. That is the defect."""
        assert "ERNCOURIER" in CERN_REPLY
        assert retry_guard.accept(CERN_UNIT, CERN_REPLY)[0] is False

    def test_one_invented_sentence_is_refused_too(self):
        """No length rule reaches this one: it is 37 characters long."""
        accepted, reason, evidence = retry_guard.accept(COURIER_UNIT, COURIER_REPLY)
        assert accepted is False
        assert reason == retry_guard.REJECTED_SENTENCES
        assert evidence["output_chars"] < 60
        assert evidence["ratio"] > evidence["sentence_max_ratio"]

    def test_the_answer_that_should_have_come_back_is_accepted(self):
        accepted, reason, _evidence = retry_guard.accept(
            COURIER_UNIT, COURIER_RULED
        )
        assert accepted is True
        assert reason is None


class TestWhatMustNotBeRefused:
    """The corpus's own extremes, measured rather than imagined."""

    @pytest.mark.parametrize(
        ("source", "output"),
        [
            # A five character Chinese term becoming a five word English name:
            # a character ratio of six, and correct.
            ("原 子 能 机 构", "International Atomic Energy Agency"),
            # The widest honest zh->en expansion in the B18 corpus.
            (
                "传统知识价值得到印证的案例不胜枚举,涵盖水资源管",
                "There are countless cases that validate the value of traditional "
                "knowledge, covering water resource management, agriculture and "
                "forestry, healthcare, and fisheries.",
            ),
            # A name carried into another script shares no token with its source.
            ("拉斐尔·马里亚诺·格罗西", "Rafael Mariano Grossi"),
            # A fragment whose honest translation closes with a full stop.
            (
                "For over a thousand years, Amazigh women have used argan oil",
                "超过一千年来，阿马齐格女性一直在使用阿甘油，这是一种现在在全球范围内商业化的产品。",
            ),
            # Latin stops that end no sentence: the naive reading called this
            # multi-sentence prose.
            (
                "编印单位 华为技术有限公司 ICT BG",
                "Published by Huawei Technologies Co., Ltd. ICT BG",
            ),
            ("编者的话", "Editorial"),
        ],
    )
    def test_honest_translations_pass(self, source, output):
        accepted, reason, _evidence = retry_guard.accept(source, output)
        assert accepted is True, reason


class TestSizeIsScriptNeutral:
    def test_one_han_character_weighs_one_english_word(self):
        assert retry_guard.effective_size("原子能机构") == 5
        assert retry_guard.effective_size("International Atomic Energy Agency") == 4

    def test_a_glyph_spaced_source_is_not_measured_as_its_spacing(self):
        assert retry_guard.effective_size("技 术 在 能 源") == 5


class TestSentenceCounting:
    @pytest.mark.parametrize(
        ("text", "count"),
        [
            ("Artron Art Group Co., Ltd", 0),
            # An abbreviation before an acronym reads as a sentence end and is
            # counted as one. Left over-counting rather than given a
            # dictionary of abbreviations: the sentence test only refuses a
            # reply that is also several times the size of what it answered,
            # and this one is four fifths of it. Measured on the whole B18
            # corpus, no unit is refused for a stop like this.
            ("Published by Huawei Technologies Co., Ltd. ICT BG", 1),
            ("A minute of silence. He was a friend.", 2),
            ("这是一句话。", 1),
            ("一句。两句。三句。", 3),
            ("Wait... really", 0),
            ("An ellipsis at the end...", 1),
        ],
    )
    def test_only_stops_that_end_something_are_counted(self, text, count):
        assert retry_guard.sentence_count(text) == count


class TestGrossLength:
    def test_both_conditions_are_required(self):
        config = retry_guard.load_retry_guard_config()
        # Over the ratio but short: an honest name expansion.
        short = "word " * 12
        accepted, _reason, evidence = retry_guard.accept("名", short)
        assert evidence["ratio"] > config.retry_output_max_ratio
        assert evidence["output_chars"] < config.retry_output_max_chars
        assert accepted is True
        # Over the cap but within the ratio: an honest long retry.
        long_source = "核安保" * 40
        accepted, _reason, evidence = retry_guard.accept(long_source, "word " * 120)
        assert evidence["output_chars"] > config.retry_output_max_chars
        assert evidence["ratio"] <= config.retry_output_max_ratio
        assert accepted is True

    def test_both_together_refuse(self):
        accepted, reason, _evidence = retry_guard.accept("名", "词 " * 200)
        assert accepted is False
        assert reason == retry_guard.REJECTED_LENGTH


class TestCacheDiscard:
    def test_a_refused_reply_is_forgotten(self):
        seen = []

        class Cache:
            def discard(self, text):
                seen.append(text)
                return True

        engine = SimpleNamespace(cache=Cache())
        assert retry_guard.discard_from_cache(engine, "the prompt") is True
        assert seen == ["the prompt"]

    def test_an_engine_with_no_cache_is_not_an_error(self):
        assert retry_guard.discard_from_cache(SimpleNamespace(), "x") is False

    def test_a_cache_that_raises_is_not_an_error(self):
        class Cache:
            def discard(self, _text):
                raise RuntimeError("locked")

        assert (
            retry_guard.discard_from_cache(SimpleNamespace(cache=Cache()), "x")
            is False
        )


class TestConfigBounds:
    def test_out_of_range_ratio_is_refused(self):
        with retry_guard.CONFIG_PATH.open(encoding="utf-8") as f:
            raw = json.load(f)
        raw["retry_output_max_ratio"] = 99.0
        with pytest.raises(retry_guard.RetryGuardError):
            retry_guard.parse_retry_guard_config(raw, "retry_guard.json")

    def test_shipped_config_is_within_its_own_bounds(self):
        config = retry_guard.load_retry_guard_config()
        assert 1.5 <= config.retry_output_max_ratio <= 16.0
        assert 40 <= config.retry_output_max_chars <= 400
        assert 1.0 <= config.retry_sentence_max_ratio <= 12.0
