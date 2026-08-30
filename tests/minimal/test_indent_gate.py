"""The indent policy's page gate, pinned as it stands.

B15's T2a set out to add a page-type gate and found it already wired: the
taxonomy declares ``indent_eligible`` on exactly ``article_opener`` and
``article_body``, ``page_is_eligible`` reads the flag off the page kind the
classifiers (and any HITL override) left in the IL, and ``decide`` clears a
paragraph on an ineligible page before it looks at anything narrower.  These
fixtures freeze that behavior so nothing re-opens it quietly: an
advertisement page takes no first-line indent, an article page still does,
and a kind the vocabulary does not declare is ineligible rather than
accidentally eligible.
"""

from __future__ import annotations

from types import SimpleNamespace

from babeldoc.magazine.indent_policy import SKIP_PAGE_INELIGIBLE
from babeldoc.magazine.indent_policy import decide
from babeldoc.magazine.indent_policy import load_indent_config
from babeldoc.magazine.indent_policy import page_is_eligible
from babeldoc.magazine.taxonomy import load_taxonomy


def taxonomy():
    return load_taxonomy()


def page_of(kind: str | None):
    return SimpleNamespace(page_kind=kind)


def test_only_the_two_article_kinds_are_eligible():
    """The closed list is the taxonomy's own declaration, nothing wider."""
    eligible = {
        page_type.name
        for page_type in taxonomy().page_types
        if page_is_eligible(page_of(page_type.name), taxonomy())[0]
    }
    assert eligible == {"article_opener", "article_body"}


def test_undeclared_and_absent_kinds_are_ineligible():
    assert page_is_eligible(page_of("no_such_kind"), taxonomy()) == (
        False,
        "no_such_kind",
    )
    assert page_is_eligible(page_of(None), taxonomy())[0] is False


def test_advertisement_page_clears_a_body_paragraph_first():
    """FD p2's shape: a ranked body paragraph on an ad page stays flush.

    The page reason wins over every narrower one, so the sidecar says the
    paragraph is flush *for its page* even when nothing else would have
    indented it either.
    """
    config = load_indent_config()
    outcome = decide("plain text", "all", False, True, 1, False, config)
    assert outcome == (False, SKIP_PAGE_INELIGIBLE)


def test_article_page_still_indents_the_same_paragraph():
    config = load_indent_config()
    outcome = decide("plain text", "all", True, True, 1, False, config)
    assert outcome == (True, None)
