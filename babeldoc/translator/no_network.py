"""Translator sentinel for execution paths that explicitly disable translation."""

from __future__ import annotations

from babeldoc.translator.translator import BaseTranslator
from babeldoc.utils.atomic_integer import AtomicInteger


class NoNetworkTranslator(BaseTranslator):
    name = "no-network"

    def __init__(self, lang_in: str, lang_out: str):
        self.lang_in = lang_in
        self.lang_out = lang_out
        self.model = "disabled"
        self.ignore_cache = True
        self.translate_call_count = 0
        self.translate_cache_call_count = 0
        self.token_count = AtomicInteger()
        self.prompt_token_count = AtomicInteger()
        self.completion_token_count = AtomicInteger()
        self.cache_hit_prompt_token_count = AtomicInteger()

    @staticmethod
    def _disabled():
        raise RuntimeError("translation is disabled for this execution path")

    def translate(self, text, ignore_cache=False, rate_limit_params=None):
        self._disabled()

    def llm_translate(self, text, ignore_cache=False, rate_limit_params=None):
        self._disabled()

    def do_translate(self, text, rate_limit_params=None):
        self._disabled()

    def do_llm_translate(self, text, rate_limit_params=None):
        self._disabled()
