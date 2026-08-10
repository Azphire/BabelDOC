# B6.3 template iteration log

One row per round. The digest is the SHA-256 of the file as it was sent, which
is also what the run's `prompts.manifest.json` records and what the brief cache
key is built from, so a round is identifiable after the fact from the artefacts
alone.

Every round is one Courier run with `magazine_article_context` up, scored
against the frozen `context_off` arm by
`examples/output/b6_smoke/scripts/ab_check.py` and by the broad Latin-retention
sweep in the same directory. `article_brief.md` changed once, in round 1;
`article_brief_context.md` changed in rounds 1 to 4.

| round | `article_brief.md` | `article_brief_context.md` | API calls | retention regressions (stated names) | new Latin retentions (all words) |
| --- | --- | --- | --- | --- | --- |
| b6.2 baseline | `f2edf3af…` | `7beb9cac…` | 38 | 2 (`Paumari`, `pirarucu`) | not measured |
| 1 | `819373eb…` | `45d67114…` | 38 | 0 | 13 |
| 2 | `819373eb…` | `1d32bb2b…` | 34 | 0 | 7 |
| 3 | `819373eb…` | `54524787…` | 35 | 0 | **3** |
| 4 | `819373eb…` | `eb6e66d5…` | 34 | 0 | 4 |
| final = 3 | `819373eb…` | `54524787…` | 0 (39/39 cache) | 0 | 3 |

Round 4 did not improve on round 3, and round 4 was the cap, so round 3's
wording is what ships. Restoring it replayed round 3 from the cache exactly —
39 of 39 prompts served, no API call, every number reproduced — which is the
frozen-replay property the evaluation protocol rests on and, incidentally, the
cheapest possible proof that the revert is the same template and not merely a
similar one.

## Round 1 — the pair

**Motive.** The batch-b6.2 smoke found the engine reading `"names": ["Paumari",
"pirarucus"]` as an instruction to leave those names alone: `保马里人` became
`Paumari人` and `巨骨舌鱼` became `pirarucu鱼`. A bare list can only say which
names occur; it cannot say how one reads, so the only thing the engine could do
with it was preserve it.

**`article_brief.md`, before:**

```
- "names": an array of the personal, place and organisation names occurring in
  the text above, each written exactly as it appears there. Source form only:
  do not translate them here. An empty array when the text carries none.
```

**after:**

```
- "names": the proper names -- of people, places, organisations, peoples,
  species and anything else that names one particular thing -- which occur in
  the text above and will have to read the same way everywhere in the article.
  Each entry is an object with two fields: "source", the name exactly as it
  appears above, and "suggested_translation", how that name should read in
  {target_language} every time it occurs. Give a {target_language} rendering
  wherever one is idiomatic; where the convention in {target_language} is to
  leave the name in its original script, repeat the source form as the
  suggested translation. An empty array when the text carries no such name.
```

**`article_brief_context.md`, before:**

```
   - Names occurring in this article, in source form, empty when it carries
     none: {names}
```

**after:**

```
   - Proper names that have to read the same way everywhere in this article,
     written as `name in the source -> how to render it`. Wherever one of these
     names occurs in the paragraphs below, translate it as the rendering given
     for it here rather than choosing again; where the rendering given is the
     source form itself, leave the name in its source form. Empty when the
     article carries no such name: {names}
```

**Result.** The two named regressions disappeared and no stated name was
retained anywhere. But 13 Latin words the `off` arm had transliterated survived
in the `on` arm — `Chimamanda Ngozi Adichie`, `Ora Marek-Martinez`, `Carolina
Zambrano`, `David Jefferson` and others, none of them on any brief's list. The
block had raised name-salience generally: it fixed the listed names and broke
the unlisted ones.

## Round 2 — scoping the instruction

**Motive.** Round 1's block said what to do with names on the list and, by the
clause about leaving a name in its source form, implied something about names
in general. State the default explicitly instead.

**`article_brief_context.md`, after:**

```
   - Proper names that have to read the same way everywhere in this article,
     written as `name in the source -> how to render it`. Where a name on this
     list occurs in the paragraphs below, use the rendering given for it here
     instead of choosing one again. The list is not exhaustive and says nothing
     at all about any name that is not on it: every other name, and every other
     word, is translated exactly as it would be without this brief. Empty when
     the article carries no such name: {names}
```

**Result.** 13 → 7. Every remaining case is a paragraph consisting of nothing
but a name: `Jim Al-Khalili`, `Ora Marek-Martinez`, `Lagipoiva Cherelle
Jackson`, `David Jefferson`. Names inside running prose were fixed.

## Round 3 — the name-only paragraph

**Motive.** A paragraph that is only a name reads, to a request carrying a block
about proper names, as a name rather than as a paragraph. Name the shape.

**`article_brief_context.md`, after:**

```
   - A short list of proper names with the rendering each is to be given
     throughout this article, written as `name in the source -> how to render
     it`. Nothing about how you translate changes because this list is here,
     with one exception: where a name on the list occurs in the paragraphs
     below, use the rendering given here instead of choosing one again. A name
     that is not on the list is translated exactly as it would be with no brief
     at all, and that includes a paragraph which is nothing but a name -- a
     byline, a credit, a caption attribution -- which is translated in full as
     usual. Empty when the article carries no such name: {names}
```

**Result.** 7 → 3. One byline paragraph left, `Lagipoiva Cherelle Jackson` on
page 2.

## Round 4 — the prohibition, rejected

**Motive.** Add an explicit prohibition: the list never licenses leaving a name
in its original script.

**Change.** One sentence inserted after the exception clause: `This list never
licenses leaving a name in its original script.`

**Result.** 3 → 4, and the new one is `UNESCO` on page 1, which the `off` arm
had rendered and which arguably should stay an acronym anyway. No improvement,
the cap was reached, so round 3 ships. The move from 3 to 4 is within the
sampling noise this project has already documented for `gpt-4o` at temperature
0, and nothing here claims round 4 is *worse* than round 3 — only that it is
not better, which is what the stop rule asks.
