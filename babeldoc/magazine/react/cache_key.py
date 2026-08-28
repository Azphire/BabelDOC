"""The digest a cached request is filed under, and what is kept out of it.

Two request points share this. The loop asks for a decision once per round, and
the orphan action asks for a translation once per line; both render a prompt
from a template in ``prompts/``, send it to the run's engine, and file the reply
under a digest of everything that could change the answer. The digest is taken
over four things: the version below, which retires every key at once when the
composition changes; the engine the answer would come from; the template the
request was rendered from; and the request itself.

What the request itself means is the question this module exists to answer.

Why the rendered text is not the request
----------------------------------------

A finding names the paragraph it is about by ``debug_id``, and the paragraph
finder mints those afresh on every run: two runs over one unchanged document
produce the same pages, the same overlaps and the same measurements under
different ids. The evidence block is rendered into the prompt whole, so the two
runs ask a question that differs in five characters and is otherwise identical,
and a digest over the rendered text puts them in different places. The loop then
pays a model to answer a question it has an answer to, on every run, forever.
That is what the replay runs measured: every sample sent between one and three
requests a warm cache did not answer, and each of them was a decision whose
evidence differed from the stored one only in ids nothing decides on.

So the digest is taken over a projection of the request rather than over the
request. The projection drops the fields named in ``volatile_evidence_keys`` and
keeps everything else, and it is used for the key alone: what is sent to the
model is the unprojected rendering, unchanged, so a run against a fixed corpus
asks exactly what it asked before and the two are comparable byte for byte.

Why the declaration names what to drop
--------------------------------------

Naming what to keep would be the safer looking choice and is the more dangerous
one, because the two ways of being wrong here do not cost the same.

A key that still carries a volatile field misses a cache it should have hit. The
run pays for one request, the attribution line beside it records that it paid,
and the fault shows up as money in a ledger somebody reads.

A key that has dropped a field the decision actually turns on hits a cache it
should have missed. A decision taken about other evidence is replayed as though
it were about this evidence, the reply validates because it is a well formed
reply, and nothing in the run says anything happened. The repair is then applied
to findings nobody chose it for.

The first is visible and recoverable and the second is neither, so the list
names the fields to drop, and a field nobody has classified stays in the key. A
new detector adding a new evidence field gets a cache miss until somebody
decides the field is volatile, which is the failure this direction was chosen
for.
"""

from __future__ import annotations

import hashlib

# Bumped when the composition of a key changes, which retires every stored
# reply at once rather than leaving some served under the old composition. The
# projection below is such a change: a key taken over the rendered request and
# one taken over its projection are different keys for the same question.
CACHE_KEY_VERSION = 2

CONFIG_KEY = "volatile_evidence_keys"


def project(evidence: dict, volatile) -> dict:
    """One finding's evidence without the fields that change on every run."""
    dropped = set(volatile)
    return {key: value for key, value in evidence.items() if key not in dropped}


def digest(
    identity: str, prompt_digest: str, key_text: str, version: int | None = None
) -> str:
    """The key one request is filed under, from the four things that decide it.

    ``version`` names the composition to build the key under, and defaults to
    the current one. It is a parameter because a key an earlier batch filed was
    built under the composition of its own day, and reproducing that key is how
    a replay shows it reproduced that request: recomputing it under today's
    composition would only show that today's code agrees with itself.
    """
    fields = (
        f"cache_key_version={CACHE_KEY_VERSION if version is None else version}",
        f"engine={identity}",
        f"prompt_file_sha256={prompt_digest}",
        f"prompt_text_sha256={hashlib.sha256(key_text.encode()).hexdigest()}",
    )
    return hashlib.sha256("\n".join(fields).encode()).hexdigest()


# Why the cache did not answer a request, as the attribution row states it.
# Every real call carries one, because a call the run cannot account for is the
# thing the ledger exists to make impossible.
SERVED_MISS = "no_stored_reply_under_this_key"
SERVED_STALE = "stored_reply_no_longer_valid_under_this_vocabulary"
SERVED_BYPASSED = "cache_bypassed_for_this_run"
SERVED_RETRY = "retry_after_a_violated_reply"

# The two groups that spend a request, named so a ledger row says which of them
# spent it without the reader having to infer it from the prompt file.
GROUP_DECISION = "decision"
GROUP_ORPHAN = "orphan_translation"

# How much of a request a row quotes. A digest identifies it and a prefix lets a
# human recognise it; the whole of it belongs in the transcript and not here.
SUMMARY_CHARS = 160


def attribution(
    group: str,
    cache_verdict: str,
    key: str,
    prompt_digest: str,
    request_text: str,
    attempt: int,
    identity: str = "",
) -> dict:
    """One row for one call that reached the transport.

    Written where the call is made rather than counted afterwards, so the row
    and the charge cannot come apart: a request served from the cache adds no
    row, and a run's rows are exactly the calls it paid for. What the row holds
    is what a reader needs to ask why the call happened -- which group asked,
    why the cache did not answer, and enough of the request to recognise it --
    and a digest of the request rather than the request, which belongs in the
    transcript.
    """
    return {
        "group": group,
        "cache_verdict": cache_verdict,
        "cache_key": key,
        "engine_identity": identity,
        "prompt_sha256": prompt_digest,
        "request_sha256": hashlib.sha256(request_text.encode()).hexdigest(),
        "request_chars": len(request_text),
        "request_head": request_text[:SUMMARY_CHARS],
        "attempt": attempt,
    }
