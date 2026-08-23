"""T4: transliteration candidates for the three masthead entries, for a human to rule on.

The shapes the harvest pass does not recognise as personal names are put to the
same prompt the pass itself uses, one entry at a time, so the candidate a person
rules on is the answer the machinery would have given had it asked. Nothing here
writes a ruling: it writes a draft with an empty verdict beside each candidate,
and the batch stops until a person fills the verdicts in.

Two of the three are personal names the shape rule missed -- a parenthetical
nickname and a run of single letter initials. The third is a design studio's
name, which the pass was right to leave alone; it is put here too so that
leaving it alone is a decision on the record rather than an omission.

Writes examples/output/b11_5/t4_draft.json. Costs a handful of API calls and
they are cached like every other call of this project.

Usage:
    python t4_candidates.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from babeldoc.magazine import corpus  # noqa: E402
from babeldoc.magazine import name_harvest  # noqa: E402
from babeldoc.magazine.cache_setup import use_project_cache  # noqa: E402
from babeldoc.magazine.prompt_loader import load_prompt  # noqa: E402
from babeldoc.translator.translator import OpenAITranslator  # noqa: E402
from babeldoc.translator.translator import set_translate_rate_limiter  # noqa: E402

SAMPLE = "FD-en-v2"
MODEL = "gpt-4o"
QPS = 4
OUT = ROOT / "examples" / "output" / "b11_5" / "t4_draft.json"

# The three entries the harvest pass recorded as person_shaped false on the
# b11.4 run of this sample, with the shape each of them is an instance of.
ENTRIES = [
    {
        "source": "Huong (Vanessa) Le",
        "page": 5,
        "blind_spot": "parenthetical nickname between the given and family name",
        "expected_person": True,
    },
    {
        "source": "S M Ali Abbas",
        "page": 5,
        "blind_spot": "run of single letter initials with no stops",
        "expected_person": True,
    },
    {
        "source": "2communiqué",
        "page": 5,
        "blind_spot": "leading digit",
        "expected_person": False,
    },
]


def load_dotenv() -> None:
    path = ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip().strip("\"'"))


def main() -> int:
    load_dotenv()
    use_project_cache(ROOT)
    set_translate_rate_limiter(QPS)

    source_lang, target_lang = corpus.direction_of(SAMPLE)
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit("no credential in the environment")
    engine = OpenAITranslator(
        lang_in=source_lang,
        lang_out=target_lang,
        model=MODEL,
        base_url=os.environ.get("OPENAI_BASE_URL") or None,
        api_key=key,
        ignore_cache=False,
        enable_json_mode_if_requested=False,
        send_dashscope_header=False,
        send_temperature=True,
    )

    working = ROOT / "examples" / "output" / "b11_5" / "t4_work"
    working.mkdir(parents=True, exist_ok=True)

    rows = []
    digest = None
    for entry in ENTRIES:
        prompt = load_prompt(
            name_harvest.PROMPT_NAME,
            {
                "target_language": target_lang,
                "names": f"- {entry['source']}",
            },
            working_dir=working,
        )
        digest = prompt.digest
        raw = engine.llm_translate(
            prompt.text, rate_limit_params={"request_json_mode": True}
        )
        answers = name_harvest._parse_answers(raw)
        answer = answers.get(entry["source"]) or {}
        rows.append(
            {
                **entry,
                "candidate": (answer.get("target") or "").strip(),
                "is_person_says_model": bool(answer.get("is_person")),
                "harvest_said_person_shaped": False,
                "verdict": "",
                "verdict_note": "",
            }
        )
        print(
            f"{entry['source']!r} -> {rows[-1]['candidate']!r} "
            f"is_person={rows[-1]['is_person_says_model']}",
            flush=True,
        )

    draft = {
        "task": "b11.5 T4",
        "sample": SAMPLE,
        "target_lang": target_lang,
        "prompt": f"prompts/{name_harvest.PROMPT_NAME}.md",
        "prompt_sha256": digest,
        "model": MODEL,
        "how_to_rule": (
            "Write the target form you want into verdict for each row. Write the "
            "source string itself to keep the entry in its source form. Leave "
            "verdict empty on no row: an empty verdict is an unruled row and the "
            "batch will not proceed past it. verdict_note is yours and is not "
            "read by anything."
        ),
        "what_a_ruling_does": (
            "Each ruled row becomes a terms entry in "
            "reviews/FD-en-v2.decisions.json, which outranks the naming policy "
            "wherever the string appears in the document."
        ),
        "requests": len(ENTRIES),
        "api_calls": engine.translate_call_count - engine.translate_cache_call_count,
        "cache_hits": engine.translate_cache_call_count,
        "rows": rows,
    }
    OUT.write_text(
        json.dumps(draft, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        f"draft at {OUT.relative_to(ROOT)}; "
        f"api={draft['api_calls']} hits={draft['cache_hits']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
