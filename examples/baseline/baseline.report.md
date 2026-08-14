# Upstream baseline — six sample translations

Unmodified upstream BabelDOC 0.6.4, run against the six paper samples to produce the
comparison baseline for the fork. **No metrics are computed in this document.** Scores
belong to the fork-side evaluation batch, which should run its own tooling over the PDFs
frozen here so both sides are measured by one instrument.

Machine-readable companion: [`manifest.json`](manifest.json).

---

## Provenance and the git check

`D:\Codes\BabelDOC-main` **is not a git repository** — it is the GitHub `main` zip
download, so the requested `git status` / `git rev-parse HEAD` could not be run. Rather
than leave provenance unevidenced, two substitutes were used, both stronger than the
original check:

**Identity.** Every file of the download was hashed with `git hash-object` and compared
against `git ls-tree -r 17480db` (the fork's upstream base, *Release v0.6.4*):

| result | count |
| --- | --- |
| byte-identical to fork base | 408 / 410 |
| differing | 1 — `README.md` |
| at fork base, absent here | 1 — `examples/ci/test.pdf` |
| here only | 6 — the sample PDFs you added |

The `README.md` delta is prose only: two links moved from
`github.com/PDFMathTranslate/PDFMathTranslate-next` to `pdf2zh-next.com`. **Every source,
asset and grammar file is byte-identical**, so the download is `main` sitting a little
ahead of the `v0.6.4` tag with no code difference.

**Zero-modification proof.** All 415 files were SHA-256'd before `pip install -e .` and
again after the full batch; the two snapshots are **identical**. The editable install
wrote only into site-packages. Snapshots are frozen at
[`integrity/tree_sha256_before.txt`](integrity/tree_sha256_before.txt) and
[`integrity/tree_sha256_after.txt`](integrity/tree_sha256_after.txt).

### Version pair

| side | path | version | commit |
| --- | --- | --- | --- |
| upstream | `D:\Codes\BabelDOC-main` | 0.6.4 | *no git metadata* (main, post-`v0.6.4`-tag) |
| fork | `D:\Codes\BabelDOC` | 0.6.4 | base `17480db` "Release v0.6.4"; HEAD `9b3437f` |

The two agree. Recorded only — how the comparison is worded in the paper is your call.

---

## Environment

Conda env `babeldoc-upstream`, Python 3.13.14, `pip install -e D:\Codes\BabelDOC-main`.
The isolation check passed: `babeldoc.__file__` resolves to
`D:\Codes\BabelDOC-main\babeldoc\__init__.py`, **not** the fork.
openai 3.0.0 · PyMuPDF 1.28.2 · onnxruntime 1.28.0 · Windows 11 (10.0.26200).

The fork's `.venv` runs 3.13.3 against this env's 3.13.14 — same minor series, noted for
completeness.

## Invocation

Shared by all six runs:

```
--openai --openai-model gpt-4o --watermark-output-mode no_watermark
--no-dual --no-auto-extract-glossary
```

qps left at its default (4, not passed). `--debug` not passed. `--no-auto-extract-glossary`
is required rather than optional: upstream 0.6.4 enables automatic term extraction by
**default**, so omitting the flag would have diverged from the fork's b5 smoke
configuration.

`babeldoc --warmup` was run once beforehand, so no sample's elapsed time includes asset
downloads. The six ran sequentially, one process each.

**API key.** babeldoc 0.6.4 offers no environment-variable path for `--openai-api-key`, so
the key was written alone into a TOML outside the repository and passed with `-c`. Its path
shows as `<API_KEY_ONLY_CONFIG>` in the manifest, the file was deleted after the batch, and
the key appears in no log, command file, or manifest.

## Cache

Upstream has no project-local cache; it writes the global
`~/.cache/babeldoc/cache.v1.db`. That db was **already populated** before this batch (75
rows, 655,360 bytes, 2026-08-10). Those rows could not contaminate the baseline: 73 carry
`model=gpt-4o-mini` and 2 carry the fork-only `magazine_brief` engine, and the model is
part of the cache key, so a `gpt-4o` batch cannot hit them. **These outputs are fresh
translations, not cache replays.**

After the batch: 337 rows, 262 new — 220 `gpt-4o en→zh` and 42 `gpt-4o zh→en`.

The frozen copy at [`cache/cache.v1.db`](cache/cache.v1.db) was made with SQLite's **backup
API, not a file copy**: at freeze time the live db carried a 4.1 MB uncommitted WAL, so a
plain copy would have silently dropped this batch's newest rows. The backup folds the WAL
in and is self-contained and replayable.

> **Attribution caveat.** Two fork-side processes (`spec_checks/run_all.py`,
> `spec_checks/spec_check_b2.py`, in the separate `babeldoc` env) held the global db open
> throughout and were deliberately left running. Every new row carries `gpt-4o` with
> exactly this batch's two language pairs and no other engine or model appears, so
> attribution is consistent — but by construction it is not exclusive.

---

## Results

All six succeeded. **Nothing failed, including Courier-zh** — see its section below, since
its behaviour was the open question.

| # | sample | direction | exit | elapsed | pages in→out | output sha256 (head) |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Courier-en | en→zh | 0 | 134.89 s | 8 → 8 | `d78d442b…` |
| 2 | Vogue-en | en→zh | 0 | 86.83 s | 3 → 3 | `b4e9ad6d…` |
| 3 | CERNCourier-en | en→zh | 0 | 144.10 s | 4 → 4 | `c78bce91…` |
| 4 | AramcoWorld-en-v2 | en→zh | 0 | 151.46 s | 9 → 9 | `9d45fc58…` |
| 5 | FD-en-v2 | en→zh | 0 | 140.46 s | 9 → 9 | `7b2d9989…` |
| 6 | Courier-zh | zh→en | 0 | 143.66 s | 8 → 8 | `71ca4c37…` |

Total 801.4 s. Page counts preserved 1:1 everywhere. Full hashes and command lines are in
`manifest.json`.

Upstream's own fallback warnings, counted from the logs (these are upstream behaviour, not
errors):

| sample | same-as-input | too long/short | → fell back to simple | length mismatch |
| --- | --- | --- | --- | --- |
| Courier-en | 1 | 2 | 3 | 1 |
| Vogue-en | 0 | 0 | 0 | 0 |
| CERNCourier-en | 17 | 2 | 19 | 0 |
| AramcoWorld-en-v2 | 16 | 2 | 18 | 0 |
| FD-en-v2 | 2 | 3 | 5 | 0 |
| Courier-zh | 0 | 5 | 5 | 0 |

Worth flagging for the paper: **warning count does not track visible quality.** Vogue-en
emitted zero warnings yet contains the batch's most blatant untranslated block, while
CERNCourier-en emitted 19 fallbacks and produced the cleanest page.

---

## Quick look, sample by sample

Every page of all six outputs was rendered and eyeballed (41 pages). Observations only —
no scoring.

### 1. Courier-en — en→zh, 8 pp

Body translation reads well and the two-page spread title splits correctly across pp. 2–3.
Defects:

- **Drop-cap collisions (p4, p5).** The large initial 很 is drawn on top of the 广角
  section chip on p4; on p5 the initial 在 collides with the small run-in text
  普鲁斯河上，当光线渐渐. This is the clearest recurring layout failure in the en→zh set.
- **Untranslated Latin drop cap (p7).** The original "T" initial survives untranslated and
  overlaps the intro paragraph's last line 在。
- **Masthead overprint (p1).** "Courier" plus a clipped 联合国教科文组织 / 科文组织 stacked
  on each other.
- **Inconsistent section chips (p1).** ZOOM and IDEAS stay English while 广角, 我们的嘉宾
  and 深入探讨 translate.
- **Orphan fragments (p4).** Two tiny stray blocks (传统知识 / 水资源管理,) float mid-column
  at the wrong size; two more in the bottom info box.
- **Column-tail truncation (p6, p8)** — paragraphs cut mid-sentence at the column foot.

### 2. Vogue-en — en→zh, 3 pp

The shortest sample and the one that most complicates a naive reading of the logs.

- **p1 (FENDI ad)** is entirely graphic; nothing translated, which is correct behaviour.
- **p2 (OMEGA ad): a real, selectable English paragraph is left completely untranslated** —
  "The new Constellation Collection. Like the star at six o'clock…". This is a genuine miss,
  not a graphic, and it produced **no warning at all**.
- **p3 (contents)** translates but the layout is badly crowded: entries collide with their
  page numbers and one block is garbled into 行动时刻！Wh e论无论你是乘火车…. Rotated
  right-hand credits stay English.

### 3. CERNCourier-en — en→zh, 4 pp

Contains the single best page of the batch and one of the worst overlaps.

- **p2 is the cleanest page in the whole batch** — contents fully translated, layout intact.
- **p3: superimposed lines.** In the ad's lower-left bullet list three lines are printed on
  top of one another and are unreadable.
- **"Th|e" ligature split.** The drop-cap ligature leaves a stranded "Th": Th欧洲战略重申了…,
  Th战略过程显示了…
- **p1**: the translated masthead CERN快报 is clipped at the page's top edge; the print slug
  `CCJulAug26_Cover_v2.indd 1` is visible.
- **p4**: good translation, two column tails truncated.

### 4. AramcoWorld-en-v2 — en→zh, 9 pp

Longest sample; mostly strong (pp. 4, 6, 7, 8 are clean) but holds the batch's worst defect.

- **p5 — worst defect of the batch. The original English display title ("RAILS…") is never
  erased.** The translated 铁路 headline is drawn straight on top of the surviving original,
  and the orange intro paragraph overprints both. Three layers of text occupy the same area.
- **p9 — surviving English mid-paragraph.** A leftover run "…lamic life has always emerged
  not through sameness but through plurality|binds this volume together." overprints the
  Chinese text: a partially-translated paragraph whose English tail was left behind.
- **p2**: the structured staff/credits list collapses into a single run-on paragraph with
  mixed font sizes; "Co mpany" splits mid-word.
- **p3**: a contents entry overlaps the large numeral 8.
- **Garbled position markers** where the original had directional cues: `#mi`, `卡方` (p5),
  `卜万`, `kkkk` (p6).
- **p1**: cover masthead is artwork (untranslated, expected); the date line reorders to
  第77卷 第4 | 期.

### 5. FD-en-v2 — en→zh, 9 pp

The strongest sample overall. pp. 1, 2, 6, 7 are clean, and **p7 translates a bar chart
completely and correctly** — legend, axis labels, and source line.

- **p5 — RTL breakage.** The Arabic call-out (اقرأ بالعربية!) is fragmented and reordered
  into ةغللاب أرقا / ة / يبرع / لا!. Also on this page, the English role labels
  (EDITOR-IN-CHIEF, MANAGING EDITOR, SENIOR EDITORS, …) stay English while the names beside
  them are transliterated into Chinese, and labels run into names without separation.
- **p8 — untranslated Latin drop cap**, same class as Courier-en p7: "W hen 在国际贸易方面…".
- **p9 — untranslated sidebar.** The monospace caption "A glacier buttercup appears on the
  front of the draft 1,000 franc note." is left entirely in English.
- **p3**: header runs on without separation (金融与发展国际货币基金组织的季度刊物六月2026).

### 6. Courier-zh — zh→en, 8 pp — the U+001A question

**Upstream did not fail.** Exit 0, 143.66 s, 8 → 8 pages, no exception, no crash. It
processed 8,001 valid characters / 5,809 gpt-4o tokens and emitted only the ordinary
five "too long/short → simple" fallbacks.

On the control character itself: **no character below U+0020 appears anywhere in the
source at PyMuPDF's extraction layer, and none appears in the output either.** So the
U+001A your escape layer handles does not surface through this extraction path — it must
arise inside BabelDOC's own pdfminer path (for example a CID font lacking a usable
ToUnicode mapping), not in the text PyMuPDF exposes. This run therefore does **not**
reproduce the condition, and it should not be cited as evidence that upstream survives
U+001A — only that this file, through this path, produced no failure. Isolating the page
that triggers it in the fork would need instrumentation on the pdfminer side, which is out
of scope for an unmodified-upstream batch.

Rendering observations:

- **Display text stays Chinese.** The large headings 目录 (p1) and 土著知识 (p3), the
  masthead 信 使 / 联合国教科文组织, all section chips (广角, 聚焦, 观点, 嘉宾, 深度阅读),
  and 社论 / 总编辑 are untranslated, while body text and TOC entries render in English.
  The reverse direction leaves display typography behind far more than en→zh does.
- **Running title untranslated (p5).** The footer still reads 巴西: 水之民族的启示 | 7.
- **Rotated photo credits untranslated** on pp. 3, 5, 6.
- **Mid-word splits are pervasive in the English output** — "complex kno / wledge",
  "quantum s ensing", "i nfrared", "s pinosa", "indigenous k nowledge", "I n essence",
  "for mal". This artifact is much more visible zh→en than en→zh, since Chinese has no
  intra-word boundary to violate.
- **Duplicated byline (p2):** "Lagipoiva Cherelle Jackson ( Lagipoiva Cherelle Jackson)".
- **Orphan fragments** on pp. 4, 5, 6 and a caption truncated mid-word on p7
  ("(scientific na / me: Argania").
- **Column tails truncated (p8)**, cut mid-sentence.

---

## Cross-cutting patterns

Five defect families recur across samples and look like the useful axes for comparison:

1. **Un-erased original text** — Aramco p5 (display title), Aramco p9 (English mid-paragraph).
   The most damaging class, since it stacks two languages in one place.
2. **Drop caps** — collisions (Courier-en p4, p5), untranslated Latin initials
   (Courier-en p7, FD p8), stranded ligatures (CERN p3).
3. **Display/chrome text skipped** — section chips, mastheads, running titles, rotated
   credits; markedly worse zh→en.
4. **Text-flow damage** — mid-word splits (heavily zh→en), column-tail truncation, orphan
   fragments at the wrong size and position, run-on collapse of structured lists.
5. **Whole blocks silently untranslated** — Vogue p2, FD p9. Both emitted no warning.

## Contents of this directory

| path | what |
| --- | --- |
| `manifest.json` | version pair, per-sample command line / timing / exit / sha256, cache and integrity records |
| `baseline.report.md` | this report |
| `pdf/<sample>/` | the six translated PDFs (the actual baseline artifacts) |
| `logs/<sample>.log` | full upstream stdout+stderr per sample |
| `logs/<sample>.cmd.txt` | the command line as executed |
| `cache/cache.v1.db` | frozen replay carrier (SQLite backup, WAL folded in) |
| `integrity/tree_sha256_*.txt` | before/after hashes of all 415 upstream files |

Nothing was committed and no tag was created — this is not a fork batch. The upstream
working tree is provably unchanged.
