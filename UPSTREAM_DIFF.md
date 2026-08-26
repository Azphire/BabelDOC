# Upstream Diff Registry

<!-- UPSTREAM PIN: 17480db9df92ddcb37349ce34b312335226e8ec9
     (Release v0.6.4, 2026-07-17). All entries below are diffs
     against this commit. Dissertation citations of upstream
     source refer to this commit. -->

Every modification to an upstream BabelDOC file must be registered here in the
same session it is made.

Two kinds of entry appear below. A *modification* row records a change made to
an upstream file. A *coupling* row records extension code that calls into an
upstream symbol without changing it: nothing upstream moves, but the extension
breaks if that symbol's name or contract does, so the dependency is registered
for the same reason a modification is.

## Modifications

| file | symbol | purpose | batch |
| --- | --- | --- | --- |
| `babeldoc/format/pdf/translation_config.py` | `TranslationConfig.__init__` | Add `magazine_checkpoint: bool = False` constructor parameter and store it on the instance; gates IL XML checkpoint writing. | B0 |
| `babeldoc/format/pdf/high_level.py` | module imports | Import `dump_checkpoint` from `babeldoc.magazine.checkpoint`. | B0 |
| `babeldoc/format/pdf/high_level.py` | `_do_translate_single` | Add a `magazine_checkpoint`-gated `dump_checkpoint` call next to each existing debug `write_json` point (create_il, detect_scanned_file, layout_generator, table_parser, paragraph_finder, styles_and_formulas, il_translated, add_debug_information, typesetting). Existing debug JSON behaviour unchanged. | B0 |
| `babeldoc/translator/cache.py` | module scope | Add `_cleanup_enabled` module flag (default True) recording whether row eviction is active. | B0 |
| `babeldoc/translator/cache.py` | `TranslationCache._cleanup` | Return early when `_cleanup_enabled` is False, so the `set`/`get` eviction call sites become no-ops for the project-local cache. | B0 |
| `babeldoc/translator/cache.py` | `init_db` | Add optional `db_path: Path \| None = None` (None keeps the global `~/.cache/babeldoc` path) and `enable_cleanup: bool = True`; close an open connection before re-binding so a second `init_db` is safe. No-argument behaviour is unchanged. | B0 |
| `.gitignore` | n/a | Add `examples/output/*` and `examples/cache/*` with `.gitkeep` negations, as required by PLAN_B0 T0.3. Not source code; tracked separately from the upstream Python allow-list. | B0 |
| `.gitignore` | n/a | Replace the blanket `examples/` rule with per-subdirectory rules for `examples/input`, `examples/output` and `examples/cache` plus `.gitkeep` negations, and un-ignore `configs/*.json` and `corpus/*.json` so the batch deliverables are tracked despite the global `*.json` rule. | B1 |
| `babeldoc/format/pdf/document_il/il_version_1.rnc` | `Page`, `PDFParagraph` | Add optional attributes `pageKind`, `pageKindConf`, `pageKindSource` to `Page` and `chainId`, `chainIndex`, `dropCapCandidate`, `dropCapDecision`, `segmentSentenceStart`, `segmentSentenceEnd` to `PDFParagraph`. No existing declaration changes. | B1 |
| `babeldoc/format/pdf/document_il/il_version_1.rng` | `Page`, `PDFParagraph` | Same nine attributes as the RNC grammar, each wrapped in `<optional>`. Hand-edited because `trang` is unavailable (W-B1-01). | B1 |
| `babeldoc/format/pdf/document_il/il_version_1.xsd` | `page`, `pdfParagraph` | Same nine attributes as the RNC grammar, each declared without `use="required"`. Hand-edited because `trang` is unavailable (W-B1-01). | B1 |
| `babeldoc/format/pdf/document_il/il_version_1.py` | `Page`, `PdfParagraph` | Add the nine matching `X \| None = field(default=None, metadata={"name": <camelCase>, "type": "Attribute"})` fields. Hand-synchronised instead of regenerated (W-B1-01). | B1 |
| `babeldoc/format/pdf/translation_config.py` | `TranslationConfig.__init__` | Add `magazine_page_classify: bool = False` constructor parameter and store it on the instance; gates the deterministic page classifier stage. | B2 |
| `babeldoc/format/pdf/high_level.py` | module imports | Import `PageClassifier` from `babeldoc.magazine.page_classifier`. | B2 |
| `babeldoc/format/pdf/high_level.py` | `_do_translate_single` | Run `PageClassifier(...).process(docs)` after the `styles_and_formulas` checkpoint and before term extraction, gated by `magazine_page_classify`, followed by a `magazine_checkpoint`-gated `page_classifier` checkpoint. No effect while the switch is off. | B2 |
| `babeldoc/format/pdf/translation_config.py` | `TranslationConfig.__init__` | Add `magazine_chain_detect: bool = False` constructor parameter and store it on the instance; gates the article chain detection stage. | B4 |
| `babeldoc/format/pdf/high_level.py` | module imports | Import `ChainBuilder` from `babeldoc.magazine.chain_builder`. | B4 |
| `babeldoc/format/pdf/high_level.py` | `_do_translate_single` | Run `ChainBuilder(...).process(docs)` after the `page_classifier` checkpoint and before term extraction, gated by `magazine_chain_detect`, followed by a `magazine_checkpoint`-gated `chain_builder` checkpoint. No effect while the switch is off. | B4 |
| `babeldoc/format/pdf/translation_config.py` | `TranslationConfig.__init__` | Add `magazine_chain_translate: bool = False` constructor parameter and store it on the instance; gates chain level joint translation inside the translation stage. | B5 |
| `babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py` | module imports | Import `EMPTY_CLAIM`, `ChainClaim` and `plan_chain_translation` from `babeldoc.magazine.chain_translation`. | B5 |
| `babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py` | `ILTranslatorLLMOnly.translate` | Behind `magazine_chain_translate`: plan the chain pass before the two executors are opened, pass the resulting claim to the three producers, and apply the plan after both executors have closed. The claim defaults to the empty one, so with the switch down the three calls carry the value that changes nothing. | B5 |
| `babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py` | `ILTranslatorLLMOnly.process_cross_page_paragraph` | Add `chain_claim: ChainClaim = EMPTY_CLAIM` and drop an endpoint pair whose tail or head the chain pass has claimed. Asked after the endpoints are selected, so the endpoint role is still decided by the untouched filter. | B5 |
| `babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py` | `ILTranslatorLLMOnly.process_cross_column_paragraph` | Add `chain_claim: ChainClaim = EMPTY_CLAIM` and drop a same-page pair whose either half the chain pass has claimed, by the same rule and at the same point as the cross-page pairing. | B5 |
| `babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py` | `ILTranslatorLLMOnly.process_page` | Add `chain_claim: ChainClaim = EMPTY_CLAIM` and skip a claimed paragraph so it takes no slot in a batch. The existing running-title snapshot is moved above that skip, which leaves it reached by a claimed member as well; the move is behaviour preserving with the switch down, the statements it crosses being the batch accumulation, which neither reads nor writes the snapshot. | B5 |

| `babeldoc/format/pdf/translation_config.py` | `TranslationConfig.__init__` | Add `magazine_article_group: bool = False` constructor parameter and store it on the instance; gates the article grouping stage. | B6 |
| `babeldoc/format/pdf/high_level.py` | module imports | Import `ArticleBuilder` from `babeldoc.magazine.article_builder`. | B6 |
| `babeldoc/format/pdf/high_level.py` | `_do_translate_single` | Run `ArticleBuilder(...).process(docs)` after the `chain_builder` checkpoint and before term extraction, gated by `magazine_article_group`. No checkpoint follows it: the stage writes nothing into the intermediate language, so the document after it is the one the preceding checkpoint already holds. No effect while the switch is off. | B6 |
| `babeldoc/format/pdf/translation_config.py` | `TranslationConfig.__init__` | Add `magazine_article_context: bool = False` constructor parameter and store it on the instance; gates the article brief pass inside the translation stage. | B6 |
| `babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py` | module imports | Import `EMPTY_CONTEXT`, `ArticleContext` and `plan_article_context` from `babeldoc.magazine.article_context`. | B6 |
| `babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py` | `ILTranslatorLLMOnly.translate` | Behind `magazine_article_context`: describe every article before anything is translated, and pass the resulting context to the chain planner and to the three producers. The context defaults to the empty one, which opens no article, declares no heading label and hands out no brief, so with the switch down the four calls carry the value that changes nothing. Planned before the chain pass, because a chain is one batch of its article and carries what that article's other batches carry. | B6 |
| `babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py` | `ILTranslatorLLMOnly.process_cross_page_paragraph` | Add `article_context: ArticleContext = EMPTY_CONTEXT` and give each endpoint pair the brief of the article both its halves belong to. A pair straddling two articles, or touching a page in none, is part of no one piece and carries nothing. | B6 |
| `babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py` | `ILTranslatorLLMOnly.process_cross_column_paragraph` | Add `article_context: ArticleContext = EMPTY_CONTEXT` and give every same-page pair the brief of the page's article, read once for the page. | B6 |
| `babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py` | `ILTranslatorLLMOnly.process_page` | Add `article_context: ArticleContext = EMPTY_CONTEXT`, give every batch of the page its article's brief, clear the running title where an article opens so that a heading never carries into the next piece, and read the running title from the label set the context declares while one is in force. With no context in force the existing `layout_label == "title"` test is what decides, unchanged. | B6 |
| `babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py` | `ILTranslatorLLMOnly.translate_paragraph` | Add `article_brief: str | None = None` and hand it to the prompt builder. A batch given none builds the prompt it built before. | B6 |
| `babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py` | `ILTranslatorLLMOnly._build_llm_prompt` | Add `article_brief: str | None = None`, appended as one more numbered entry of the existing contextual hints block, and advance the hint counter after the recent-title entry so the numbering stays consecutive. The brief arrives rendered from its own template, so no wording is composed here. With no brief the block is byte for byte what it was. | B6 |

| `babeldoc/format/pdf/translation_config.py` | `TranslationConfig.__init__` | Add `magazine_hitl_export: bool = False` constructor parameter and store it on the instance; gates writing the review draft of what the machine decided unaided. | B7 |
| `babeldoc/format/pdf/translation_config.py` | `TranslationConfig.__init__` | Add `magazine_hitl_apply: bool = False` constructor parameter and store it on the instance; gates letting the decisions file beside that draft overrule those decisions. | B7 |
| `babeldoc/format/pdf/high_level.py` | module imports | Import the `hitl` module from `babeldoc.magazine`. | B7 |
| `babeldoc/format/pdf/high_level.py` | `_do_translate_single` | Call `hitl.after_page_classify(translation_config, docs)` after `PageClassifier.process` and before the `magazine_checkpoint`-gated `page_classifier` checkpoint, so a checkpoint carries the page kind the run went on to use rather than the one a ruling overruled. Both switches down, the call returns having read nothing. | B7 |
| `babeldoc/format/pdf/high_level.py` | `_do_translate_single` | Call `hitl.after_term_extract(translation_config, docs)` after the `AutomaticTermExtractor` block and before the translator is constructed. Unconditional rather than inside that block: a ruling on terms applies whether or not extraction ran, and the translator caches its glossaries as it is constructed, so this is the last point at which a ruled term can reach a prompt. Both switches down, the call returns having read nothing. | B7 |

| `babeldoc/format/pdf/high_level.py` | `_do_translate_single` | Call `hitl.after_translate(translation_config)` after the `ILTranslator` block and before the `il_translated` debug dump. Unconditional at the call site and guarded inside: what a ruling reached is only knowable once every request has been built, and the tracking file it reads is written by the translator immediately above. Both HITL switches down, the call returns having read nothing. | B8 |
| `babeldoc/format/pdf/translation_config.py` | `TranslationConfig.__init__` | Add `magazine_detect: bool = False` constructor parameter and store it on the instance; gates the post typesetting detection pass. | B8 |
| `babeldoc/format/pdf/high_level.py` | module imports | Import the `detectors` module from `babeldoc.magazine`. | B8 |
| `babeldoc/format/pdf/high_level.py` | `_do_translate_single` | Run `detectors.detect_issues(translation_config, docs)` after the `magazine_checkpoint`-gated `typesetting` checkpoint and before `PDFCreater` is constructed, gated by `magazine_detect`. That point is the only one at which the translation is written back and the geometry it will render at is final. The pass reads the document and writes a sidecar; it changes nothing, so with the switch off or on the produced PDF is the same. | B8 |

Batch b8.2 changes no upstream file. The repair loop reaches the pipeline
through the `detect_issues` call the row above already declares: that function
hands the pass to `magazine/react/controller.py` when `magazine_repair` is set
on the configuration object, and behaves exactly as before when it is not. The
switch is not a constructor parameter for the same reason the drop cap one is
not; see W-B8-01.

Batch b8.3 changes no upstream file either. It runs the pipeline with the
switches the two rows above declare and measures what came out; the only
executable code it adds is under `spec_checks/` and `examples/output/b8/`, and
the only production file it edits is a prompt template.

Batch b8.4 changes no upstream file either. Everything it adds is in the
extension package, in `configs/`, in `prompts/`, in `tools/` and under
`spec_checks/`. Two of those are worth naming here because other things read
them: `magazine/reading_order.py` is now the single place a paragraph is turned
into the text it shows, and `magazine/checkpoint.py` resolves a checkpoint
directory to the archive standing for it, which is what lets a frozen baseline
be one file rather than a directory without any reader knowing.
| `babeldoc/format/pdf/high_level.py` | module imports | Import the `paren_dedup` module from `babeldoc.magazine`. | B10.1 |
| `babeldoc/format/pdf/document_il/midend/il_translator.py` | module scope | Add `_normalised_for_identity` and `_is_identity_write_back`, and import `unicodedata` for the first of them. The pair answers whether a reply says what the source said, under NFKC with surrounding space dropped; the normalisation decides and writes nothing. | B11.1 |
| `babeldoc/format/pdf/document_il/midend/il_translator.py` | `ILTranslator.post_translate_paragraph` | Replace `translated_text == translate_input` with `_is_identity_write_back(translated_text, translate_input)`. The third argument is a `TranslateInput`, which carries its text on `.unicode` and defines no `__eq__`, so the original comparison of a string against that object was never true and the short circuit below it was unreachable: every reply identical to its source was recomposed and relaid out. The branch itself is unchanged, and a caller passing something that is not a `TranslateInput` falls back to the original comparison. | B11.1 |
| `babeldoc/format/pdf/document_il/midend/typesetting.py` | module scope | Add `HANG_CONFIG_PATH`, `HANG_REPORT_NAME`, the three hang verdict names and `load_hang_max_em`, which reads `configs/typeset_hang.json` through `magazine/page_features.validate_bounded_config`; import `json`, `lru_cache` and `Path` for it. The ceiling on hung punctuation is a declared length and no length is written in this file. | B11.1 |
| `babeldoc/format/pdf/document_il/midend/typesetting.py` | `Typesetting._layout_typesetting_units` | Bound the hung punctuation exemption. The unit loop becomes a `while` over an index so a placement can be reopened; each placement on the current line is recorded; a hung unit ending more than `hang_max_em` ems past `box.x2` triggers `_hang_retreat`, which takes the trailing hung run and the one unit before it off the line, and the loop resumes at that unit with a break forced. Where the retreat would empty the line it is refused and the old behaviour stands. Adds the `hang_log` parameter, appended to for every hung unit that ends past the box. With no hang past the box the loop places exactly what it placed before. | B11.1 |
| `babeldoc/format/pdf/document_il/midend/typesetting.py` | `Typesetting._hang_retreat` | New static method: where a line has to be reopened to move a hung run off its end, or None where the line holds nothing else. Bounded by construction -- never longer than the hung run plus one. | B11.1 |
| `babeldoc/format/pdf/document_il/midend/typesetting.py` | `Typesetting.__init__`, `._find_optimal_scale_and_layout`, `._record_hangs`, `._write_hang_report`, `.typesetting_document` | Keep and write the hang sidecar. The scale search lays a paragraph out once per scale it tries, so `_find_optimal_scale_and_layout` passes a fresh log per attempt and commits only the attempt it applies; `typesetting_document` clears the accumulator on entry and writes `typeset_hang.report.json` on exit. Observation only: the report is written after the document is laid out and nothing reads it back. | B11.1 |
| `babeldoc/format/pdf/high_level.py` | `_do_translate_single` | Call `paren_dedup.apply(translation_config, docs)` after `hitl.after_translate` and before the `il_translated` debug dump, gated inside by `magazine_paren_dedup`. That point is the only one at which the translation is written back and the geometry it will be set at is not yet fixed, so a paragraph shortened there is laid out once rather than twice. | B10.1 |

## Couplings

Extension code calling upstream symbols it does not change. Each row names the
caller, so an upstream rename is traceable to what it breaks.

| file | upstream symbol | caller | purpose | batch |
| --- | --- | --- | --- | --- |
| `babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py` | `ILTranslatorLLMOnly._build_llm_prompt` | `magazine/chain_translation.py`, `ChainPlan._translate` | Build a merged chain's request from the same template, glossary matching and title context a page batch is built from, so a chain is one row of the existing batch protocol rather than a second protocol beside it. Private by name, and the only way to reach that template. | B5 |
| `babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py` | `ILTranslatorLLMOnly._clean_json_output` | `magazine/chain_translation.py`, `ChainPlan._translate` | Strip the engine's response down to parseable JSON exactly as the per paragraph path does, so a chain and a batch tolerate the same malformed output. | B5 |
| `babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py` | `ILTranslatorLLMOnly._build_font_maps` | `magazine/chain_translation.py`, `ChainPlan._prepare` | Obtain the page and xobject font maps a member's `pre_translate_paragraph` call requires. Reused rather than reimplemented so a member is prepared identically whether the chain pass or the page batch prepares it. | B5 |
| `babeldoc/format/pdf/document_il/midend/il_translator.py` | `ILTranslator.pre_translate_paragraph` | `magazine/chain_translation.py`, `ChainPlan._prepare` | Obtain each member's source text and its placeholder set before the merge. Reached through `ILTranslatorLLMOnly.il_translator`, never changed: a chain member is prepared by exactly the call the per paragraph path would have made, which is what lets a chain be escalated back to that path unchanged. | B6 |
| `babeldoc/format/pdf/document_il/midend/il_translator.py` | `ILTranslator.post_translate_paragraph` | `magazine/chain_translation.py`, `ChainPlan.apply` | Write each member the piece the backfill cut for it, through the same writer the per paragraph path uses, so a merged member and an ordinary paragraph are written by one code path. Reached through `ILTranslatorLLMOnly.il_translator` and never changed. | B6 |
| `babeldoc/translator/translator.py` | `BaseTranslator.llm_translate` | `magazine/article_context.py`, `EngineTransport.complete` | Send one brief request through the engine already configured for the run, so its credential, endpoint and rate limiter are configured once rather than twice. Called with `ignore_cache=True`: the cache that serves a brief is the one in that module, whose key names the prompt file the request came from. | B6 |
| `babeldoc/translator/cache.py` | `TranslationCache` | `magazine/article_context.py`, `CachedBriefClient` | File brief replies in the project-local database under an engine name of their own, as `magazine/vlm_client.py` files vision replies. Only `get` and `set` are used. | B6 |
| `babeldoc/format/pdf/translation_config.py` | `SharedContextCrossSplitPart.user_glossaries`, `SharedContextCrossSplitPart.auto_extracted_glossary` | `magazine/hitl.py`, `apply_terms` | Put a human's ruling where the translator reads its glossaries from, and rebuild the finalised automatic glossary without the entries that ruling overruled. The two slots are written, never the extractor's own `raw_extracted_terms`. The automatic slot is emptied and its rebuilt glossary moved into the user list, because `get_glossaries_for_translation` returns the automatic glossary alone whenever extraction is enabled and that slot is filled; see W-B7-01. | B7 |
| `babeldoc/glossary.py` | `Glossary`, `GlossaryEntry`, `Glossary.normalize_source` | `magazine/hitl.py`, `apply_terms` | Build the ruled pairs into the same glossary type the extractor and the user glossary loader build, so a ruled term is matched against a batch by exactly the matcher every other term is matched by. | B7 |
| `babeldoc/format/pdf/document_il/il_version_1.py` | `PdfParagraph.drop_cap_candidate`, `PdfParagraph.drop_cap_decision` | `magazine/drop_cap.py`, `mark` and `apply_decisions` | First writer of the drop cap pair B1 added to the schema: the marking pass sets the candidate flag on the paragraphs it finds and the review layer's ruling sets the verdict. Only a candidate and only a ruled paragraph is written, so a document neither pass touched carries neither attribute. Nothing reads the verdict in this batch. | B7 |
| `babeldoc/format/pdf/document_il/il_version_1.py` | `PdfParagraph.pdf_paragraph_composition`, `PdfSameStyleCharacters.pdf_style`, `PdfCharacter.pdf_style` | `magazine/drop_cap.py`, `leading_run` and `median_font_size` | Read the characters a paragraph opens with and the sizes of all of them, which is the whole of the typographic evidence a drop cap is found from. The opening run is read off the leading characters rather than off the first composition, because the styling stage groups an enlarged initial with the body sized letters after it into one formula. Finding is read only. Acting on the verdict is not, and is registered on its own row: B9.4's `flatten` rewrites the composition. | B7 |
| `babeldoc/format/pdf/document_il/il_version_1.py` | `PdfParagraph.pdf_paragraph_composition`, `PdfParagraph.unicode`, `PdfSameStyleCharacters`, `PdfFormula`, `PdfCharacter.pdf_style` | `magazine/drop_cap.py`, `apply_decisions` | Write the flattened paragraph: the initial's composition is collapsed into the run after it, the paragraph's own base style is declared on the result, and the separator the paragraph finder synthesised between them is dropped. This is the one place the drop cap pass rewrites a composition, and it happens before the translator is built, so what typesetting later reads is a paragraph whose first word is one word. | B9.4 |
| `babeldoc/format/pdf/document_il/il_version_1.py` | `PdfParagraph.pdf_paragraph_composition`, `PdfParagraph.box`, `PdfParagraph.pdf_style`, `Page.pdf_figure`, `Page.pdf_xobject` | `magazine/detectors/`, `base.rendered_text` and the three page detectors | Read a finished page: the characters a paragraph is laid out as, its box and style, and the artwork boxes it may be standing on. Every read is after typesetting and nothing is written back, which is what makes detection a pass that cannot change a rendering. | B8 |
| `babeldoc/format/pdf/document_il/il_version_1.py` | `PdfParagraphComposition.pdf_character`, `PdfSameStyleCharacters`, `PdfLine`, `PdfFormula`, `PdfSameStyleUnicodeCharacters`, `PdfCharacter.box` | `magazine/reading_order.py`, `paragraph_reading_text` | Read a paragraph's style runs and the boxes of the characters inside them, which is the whole of the evidence the reading order of a rotated paragraph is derived from. Read only, and now the single place in the package that walks a composition for text: the detectors and the repair action both go through it, so a finding and the repair answering for it are about one string. | B8.4 |
| `babeldoc/format/pdf/document_il/midend/il_translator.py` | `ILTranslator.translate` tracking file (`translate_tracking.json`) | `magazine/hitl.py`, `read_tracking` | Read what text each paragraph was actually offered as, which is the string the glossary is matched against and the one a review draft does not show. The file is written by the translator whether or not this reads it, so nothing upstream changes and no request is spent to learn what a ruling reached. | B8 |
| `babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py` | `ILTranslatorLLMOnly.translate_paragraph`, `ILTranslatorLLMOnly._build_llm_prompt` | `tools/run_drift_trio.py`, `PromptTrace` | Wrap both at run time to record which paragraphs each request was built from, which is the only way to know whether the chain arm asked about the same batch as the off arms. Both wrappers call through and return what they were given, and are removed in a `finally`; nothing upstream is edited and the run is what it would have been. The batch entry point is wrapped rather than the prompt builder alone because the builder is also reached from the chain pass, which carries no batch. | E2.1 |
| `babeldoc/translator/translator.py` | `BaseTranslator.add_cache_impact_parameters`, `TranslationCache.translate_engine_params` | `tools/run_drift_trio.py`, `build_engine` and the run record | Give each independently sampled arm a cache namespace of its own, so that neither can be served the other's answers while both stay replayable, and record the resulting key so the gate can assert the two differ. The parameter reaches the cache key only; the request on the wire is unchanged. See W-E2-01. | E2.1 |
| `babeldoc/translator/cache.py` | `TranslationCache` | `tools/splice_judge.py`, `CachedJudgeClient` | File the splice judge's replies in the project-local database under an engine name of their own (`magazine_splice_judge`), as `magazine/vlm_client.py` files vision replies and `magazine/article_context.py` files brief replies. Only `get` and `set` are used, and the key is composed in the tool. | E2.2 |
| `babeldoc/format/pdf/translation_config.py` | `TranslationConfig.custom_system_prompt` | `magazine/translation_style.py`, `apply` | Carry the run's standing instruction about how a personal name is rendered. This slot is the only one every prompt builder on the translation path reads, which is why the policy travels by it rather than by the article brief the plan first named: a brief reaches no unassigned page and no retried orphan. Written only under a policy that states something; under `keep_source` the slot is left exactly as it was found, so the run is byte for byte the one that came before. A value already in the slot is kept and stated first. | B9.1 |
| `babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py` | `ILTranslatorLLMOnly._build_llm_prompt` | `spec_checks/spec_check_b9_1.py` | Read the role block the page batch and the merged chain are built with, to assert the standing instruction reaches both. Nothing upstream changes; the gate drives the same private builder the chain pass already couples to. | B9.1 |
| `babeldoc/format/pdf/document_il/midend/il_translator.py` | `ILTranslator._build_role_block` | `spec_checks/spec_check_b9_1.py` | Read the role block the orphan retry path is built with, reached through `ILTranslatorLLMOnly.il_translator`, which is the object a failed batch resubmits each of its paragraphs to. This is the coverage claim the standing instruction rests on, so it is asserted against the real method rather than against a copy of its logic. | B9.1 |
| `babeldoc/format/pdf/document_il/il_version_1.py` | `Page.cropbox`, `Page.mediabox`, `Box` | `magazine/detectors/base.py`, `page_frame` | Read the frame a page's own coordinates are bounded by, which is what makes "outside the page" a measurable claim. The crop box first and the media box only where a page carries none, which is the order the typesetting stage and the writer already read them in, and which puts a paragraph box and this box in one space with no transform between them. Read only. | B9.5 |
| `babeldoc/format/pdf/document_il/il_version_1.py` | `PdfCharacter.box`, `PdfCharacter.pdf_style`, `PdfParagraph.pdf_paragraph_composition` | `magazine/detectors/base.py`, `rendered_box`; `magazine/detectors/page_bounds.py` and `magazine/detectors/collision.py` | Measure the ink a paragraph puts on the page as the union of the boxes of the characters it was laid out as, rather than the box it was laid out into. The two differ exactly where the defect is: the stage anchors line spacing on a paragraph's modal unit size, so a display line sharing a paragraph with a small one is drawn outside the box that was measured for it. Read only. | B9.5 |
| `babeldoc/format/pdf/document_il/il_version_1.py` | `PdfCharacter.box`, `PdfCharacter.pdf_style`, `PdfParagraph.box`, `PdfStyle` | `magazine/react/contain.py`, `transform` | Write the containment map: every laid out character's box, and its style's size where the map scales. Both, because the writer emits `Tf <font_size>` and `Tm 1 0 0 1 <box.x> <box.y>` per character and reads neither `PdfParagraph.scale` nor `PdfParagraph.optimal_scale`, so a paragraph's rendering is an affine function of exactly these two fields. The style is replaced rather than edited, because one style object is shared across a run and editing it would resize text this action never looked at. | B9.5 |
| `babeldoc/format/pdf/document_il/il_version_1.py` | `PdfParagraph.debug_id` | `magazine/detectors/source_geometry.py`, `root_id` and `SourceGeometry.box_of` | Match a finished paragraph to the one the source drew, which is the whole of the evidence that separates an overlap the translation caused from one the designer set. The identity is minted once by the paragraph finder and carried unchanged by every stage after it; the derived ids line splitting mints are cut back to the parent's. Read only, and a paragraph the source checkpoint does not carry is left out of the comparison rather than assumed. | B9.5 |
| `babeldoc/format/pdf/document_il/il_version_1.py` | `PdfParagraph.pdf_paragraph_composition`, `PdfParagraph.box`, `PdfParagraph.unicode`, `PdfParagraph.pdf_style`, `PdfSameStyleCharacters`, `PdfCharacter.pdf_style`, `Page.pdf_font`, `PdfXobject.pdf_font` | `magazine/fragment_stitch.py`, `_stitch`, `_blank` and `face_names` | Rebuild a written unit the paragraph finder left in pieces: the members' characters become one style run on the first of them, its box, text and base style are recomputed from those characters, and every other member is left in place holding nothing. The font tables of the page and of each form are read because a font id is scoped to the resource dictionary it is reached through, so the same typeface carries a different id inside every form and only the name is comparable. Written before the translator is built, so what reaches a request is one unit. | B10.3 |
| `babeldoc/format/pdf/document_il/il_version_1.py` | `PdfParagraph.pdf_style`, `PdfStyle`, `PdfCharacter.pdf_style` | `magazine/line_split.py`, `record_style` and `_line_paragraph` | Declare on every record the pass builds the style that record's own characters are mostly set in, replacing the parent's base style rather than inheriting it. The base style is what `ILTranslator.get_translate_input` lays a translation out in, so a title record inheriting a byline-heavy parent's style is printed at byline size. A fresh style object is written rather than the character's own, because one style object is shared across a run. | B10.3 |
| `babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py` | `ILTranslatorLLMOnly._build_font_maps`, `._build_llm_prompt`, `._clean_json_output`, `.calc_token_count`, `.translate_engine`, `.il_translator.pre_translate_paragraph`, `.post_translate_paragraph`, `.total_count`, `.ok_count` | `magazine/short_unit.py`, `plan` and `apply` | Translate a paragraph the length floor never offered a request for, through the same prompt builder and the same two ends of the pipeline the chain pass has used since B5. The floor is read once per paragraph inside a loop this project does not own and there is no hook between it and the batch, so the shape exception is applied here rather than at the floor; the admitted paragraphs are then claimed, so the paragraph path leaves them alone. Nothing upstream changes. | B10.4 |
| `babeldoc/format/pdf/document_il/utils/paragraph_helper.py` | `is_cid_paragraph`, `is_pure_numeric_paragraph`, `is_placeholder_only_paragraph` | `magazine/short_unit.py`, `candidates` | Apply the three tests the page batch applies below the floor, so that the exception is to the length rule alone. A folio, a paragraph drawn in an unmapped encoding and a paragraph holding only a formula placeholder are refused a request at any length, and are refused one here by calling the same predicates rather than by restating them. Read only. | B10.4 |
| `babeldoc/translator/translator.py` | `BaseTranslator.translate` | `magazine/chain_translation.py`, `ChainPlan._aligned_lengths` | Measure how long one chain member's own translation is, to place the chain's cut by that length rather than by the member's share of the source. The plain cached path is used rather than the JSON one because what is wanted is a length and not a structure, and because its answers are cached under the engine's own key so a rerun sends nothing. The answer's text is discarded inside the method and never returned: a chain's output comes from the joint translation and from nothing else. | B10.4 |
| `babeldoc/format/pdf/document_il/il_version_1.py` | `PdfParagraph.pdf_paragraph_composition`, `PdfLine.pdf_character`, `PdfSameStyleCharacters.pdf_character`, `PdfCharacter.box`, `PdfCharacter.char_unicode`, `Page.pdf_paragraph` | `magazine/source_audit.py`, `paragraph_characters` and `audit_page` | Read a page a second time, character by character, to compare it against an extraction that shares no code with the pipeline. Every kind of composition is read rather than one, because a paragraph is recomposed as it moves down the pipeline and the audit runs at the point the stitch runs while also being runnable over any checkpoint. The em box is read rather than the inked one: two characters on one baseline share the first and differ in the second by their descenders. Read only. | B10.4 |
| `babeldoc/format/pdf/translation_config.py` | `TranslationConfig.input_file`, `.translator`, `.min_text_length`, `.lang_out` | `magazine/source_audit.py`; `magazine/short_unit.py`; `magazine/name_harvest.py`; `magazine/fragment_stitch.py` | Read the file a run was made from, so a page can be read a second time through an independent extractor; read the engine, so the harvest can ask once for the rendering of every name it found; read the floor this batch declares an exception to, so the exception is stated against the run's own value rather than against a copy of it. Read only. | B10.4 |
| `babeldoc/format/pdf/document_il/il_version_1.py` | `PdfParagraph.box`, `PdfLine.box`, `PdfSameStyleCharacters.box`, `PdfFormula.box`, `PdfCharacter.box`, `PdfCharacter.visual_bbox`, `Box.y`, `Box.y2` | `magazine/column_reflow.py`, `_boxes_of`, `raise_by` and `restore` | Raise one paragraph on the page by writing the vertical pair of every coordinate box it holds. Walked rather than listed, because a paragraph carries its coordinates in several places at once and a move that reached some of them would leave the document disagreeing with itself about where the paragraph is. Only the vertical pair is written, and the coordinate each box stood at is kept so a page put back is the page the stage produced rather than the same numbers arrived at again. | B10.5 |
| `babeldoc/format/pdf/document_il/il_version_1.py` | `PdfParagraph.xobj_id`, `PdfCharacter.xobj_id`, `Page.pdf_figure`, `Page.pdf_rectangle`, `Page.pdf_curve`, `Page.pdf_form`, `Page.pdf_character` | `magazine/column_reflow.py`, `inside_xobject` and `obstacle_boxes` | Read what the pass may not move. A paragraph drawn inside a form carries the form's id, and a form is one drawing placed on however many pages ask for it, so raising it on one page raises it on all of them; the running folio of this corpus is exactly that case. The page level collections are read for the same reason from the other side: they are ink this pass does not move, so a gap one of them stands in is not empty and is never closed. Read only. | B10.5 |
| `babeldoc/format/pdf/document_il/midend/typesetting.py` | `Typesetting._find_optimal_scale_and_layout` | `magazine/column_reflow.py`, `holds_formula` | Not called: the coupling is to what the stage does with a formula. It appends the curves and forms a formula unit renders to the *page* rather than to the paragraph, so a paragraph holding a formula cannot be moved without leaving its own artwork behind, and this pass anchors such a paragraph instead. Registered because the anchor is unnecessary the day that stops being true, and wrong the day it changes shape. | B10.5 |

Batch b10.5 changes no upstream file. The column reflow pass reaches the pipeline through the `detect_issues` call the B8 row above already declares: that function runs the extension owned passes of the post typesetting window before it consults its own switch, and the heading policy of B10.1 arrived by the same door. The three rows above register what the new pass reads and writes in the intermediate language.

## B11.2

| 文件 | 符号 | 调用方 | 目的 | 批次 |
| --- | --- | --- | --- | --- |
| `babeldoc/format/pdf/document_il/midend/il_translator.py` | `_is_identity_write_back`,新增 `_is_nfkc_only_identity` 与 `ILTranslator._record_nfkc_only_identity` | `ILTranslator.post_translate_paragraph` 自身 | 把恒等写回的判据由**归一化相等**收紧为**逐字节相等**。归一化比较回答的是另一个问题——两串折叠掉宽度与合成差异之后是否长得一样——而在这里回答它,就让短路成了一个关于外观的决定:模型把半角标点改写成全角形式的回复被判为"未改变",源形被保留,模型的标点决定被一个只为发现"模型原样退回输入"而写的比较悄悄推翻。归一化保留下来但只用于**记录**:仅归一化相等的段落逐条记入 `identity_criterion.report.json`(计数键 `nfkc_equal_not_byte_equal`,每条含两串原文),不参与任何判定。 | B11.2 |

除此一处,批次 b11.2 不改动任何上游文件。T4 的三项前瞻性修法全部落在扩展侧
(`tools/prune_outputs.py`、`spec_checks/run_all.py`、新增 `spec_checks/evidence.py`);
T3 的 `tools/column_continuity.py` 只读复用 `magazine/chain_signals.py`,不改动它。

## B11.3

| 文件 | 符号 | 调用方 | 目的 | 批次 |
| --- | --- | --- | --- | --- |
| `babeldoc/format/pdf/document_il/utils/formular_helper.py` | `is_formulas_font`,其 `broad_formula_font_pattern` 分支 | `collect_page_formula_font_ids` → `StylesAndFormulas.process_page_formulas`(`styles_and_formulas.py:571-576`),再经 `_classify_characters_in_composition:445` 的字体分支 | 见下方逐函数登记 | B11.3 |

### 逐函数登记

**`is_formulas_font(font_name, formular_font_pattern)`**

- **上游原行为**:当调用方不提供 `formular_font_pattern` 时,使用内建的 broad 模式判定
  字体是否为公式字体。该模式含 `.*Mono` 一项,即**字体族名中出现 "Mono" 即判为公式字体**。
  判定顺序为:precise(真数学字体)→ True;`pattern_text`(正文字体白名单)→ False;
  broad → True;否则 False。
- **本项目改后行为**:broad 模式中**移除 `.*Mono` 一项**,其余十四项(`CM[^RB]`、
  `(MS|XY|MT|BL|RM|EU|LA|RS)[A-Z]`、`LINE`、`LCIRCLE`、`TeX-`、`rsfs`、`txsy`、`wasy`、
  `stmary`、`.*Code`、`.*Sym`、`.*Math`、`AdvP4C4E74`、`AdvPSSym`、`AdvP4C4E59`)与三层
  判定顺序**一律不动**。precise 模式不动,`pattern_text` 白名单不动,
  `formular_font_pattern` 的配置通道语义(提供即整体替换 broad)不动。
- **理由**:`.*Mono` 描述的是字体的**度量**(等宽),不是它的**内容**。等宽只说明字面如何
  排布,不说明排的是什么;正文字体做成等宽与记号做成等宽一样常见。broad 模式的其余各项
  要么点名一个数学/符号字族(`.*Math`、`.*Sym`、`rsfs`、`txsy`、`wasy`、`stmary`、
  `TeX-`、`CM[^RB]`),要么点名一个铸字厂前缀,**只有 `.*Mono` 是纯度量描述**。真正既是
  数学字体又是等宽的那些面(`MiriamMonoCLM` 等)在 precise 模式里**逐个点名**,而 precise
  先于 broad 被查,故它们的判定不受影响。
  实测:全语料 133 个字体名中**仅 3 个**判定改变(`GTFlexaMono-Thin` /
  `-Light` / `-Regular`),且改后**全语料无一字体仍靠 broad 模式被判为公式字体**——
  即该分支在本语料上不再贡献任何标注。误标 **68 → 43**,新增 **0**;
  钉住的 **20 条真公式全部仍被正确标注**(`t3_repair.json`)。
- **改动只以 T1 判据词汇表述**:所用信号只有"字体名描述度量还是描述数学",不含刊物名、
  页码、段落 id 或任何取自样张的字符串。落点选定见 `t3_consumer_inventory.json`
  与本批报告 §7。

**落点与 PLAN 候选名的差异(用户裁决第 (3) 条)**:`PLAN_B11_3.md` 的候选表把 (A) 写作
「StylesAndFormulas 的标注条件」。以代码为准,做判定的是 `formular_helper.is_formulas_font`;
`styles_and_formulas.py:445` 只是一次集合成员判断(`font_id in formula_font_ids`),
在那里改会把一个**字体名**问题写成一个**分类器**问题。故落点订正为 `formular_helper.py`,
登记 W-B11-11。`styles_and_formulas.py` **本批未改动一行**。

## B11.5

| 文件 | 符号 | 调用方 | 目的 | 批次 |
| --- | --- | --- | --- | --- |
| `babeldoc/format/pdf/high_level.py` | `_do_translate_single`(译后、Typesetting 前一行调用)、模块级 import | 流水线主干 | 让 T3 的 `indent_policy` pass 在其声明窗口内运行:该窗口(`paren_dedup.apply` 之后、`dump_checkpoint("il_translated")` 之前)在主干上,magazine 侧无既有钩子够得到。两行:一行 import,一行调用。pass 自身默认关(`magazine_indent_policy` 缺省为假),故本改动在开关抬起前逐位无行为差异。计划的负向范围未列本文件,登记 W-B11-15 | B11.5 |
| `babeldoc/format/pdf/document_il/midend/styles_and_formulas.py` | 模块级 `load_initial_adjacent` / `paragraph_character_sizes` / `initial_adjacent_exemption`(新增);`StylesAndFormulas._classify_characters_in_composition`(新增形参 `exempt_span` 与一处 `is_corner_mark` 抑制);`StylesAndFormulas.process_page_formulas`(每段计算一次 `exempt_span` 并传下) | `process_page` → `process_page_formulas` → `_classify_characters_in_composition` | 见下方逐函数登记 | B11.5 |

### 逐函数登记

**`_classify_characters_in_composition(..., exempt_span=(0, 0))`**

- **上游原行为**:逐字符判角标。三个分支中最先触发的一个是"当前字号 < 前一字符字号 ×
  0.79 且前后皆非空格" —— 它把一个**字号台阶**读作"上标挂在正文上"。该处上游注释自称
  "同时考虑首字母放大的情况",而首字母放大**正是**制造这个台阶的排版手法:段首放大字之后
  紧跟的正文字母,恒满足该分支。命中即 `is_formula = is_formula or is_corner_mark`,于是
  开头单词的后几个字母被当作公式原样带过,不进翻译。
- **本项目改后行为**:新增形参 `exempt_span`,为段首放大 run 之后的一段**首行**字符下标
  区间。落在该区间内的字符,`is_corner_mark` 置假。**只抑制这一个谓词** ——
  `is_formula` 的其余各条(公式版面 id、公式字体、竖排、dummy 空格、视觉框错位、公式起始/
  中间字符)一律照原样计算,所以区间内的真公式仍是公式。区间外、非首行、以及不带放大首字的
  段落,行为逐位不变。
- **区间的取法**:`initial_adjacent_exemption(paragraph)` 只读几何与顺序 ——
  段内首字符的字号、段内字号中位数、以及同字号 run 的长度。放大判据为
  `首字号 ≥ 中位数 × initial_adjacent_ratio`,区间自 run 末尾起、长
  `initial_adjacent_chars` 个字符;run 归属容差为 `initial_adjacent_tolerance`。
  三个数全部声明在 `configs/initial_adjacent.json`(带允许范围),代码内无裸字面量。
  比值与容差与 `configs/drop_cap.json` 的候选阈同源,不是同一形状的第二个数。
- **理由**:这不是 corner_mark 全类修复。修的是一族**自反讽假阳** —— 规则自称考虑了首字母
  放大,却恰被首字母放大触发。全类修复留在缓议中,因为同一分支也命中真上标与小型大写正文;
  实测的两条小型大写(CERNCourier `Volume 66 …` 比值 1.18、`Policy` 比值 1.43)正落在
  2.0 之下,不被本豁免触及。
- **实测**(`t2_measurement.json`,以真实 stage 对 b10.5 stage-05 checkpoint 跑两遍取差):
  全语料 6 样张,命中放大区间的段 **6** 个,改判 **2** 处(FD-en-v2 p8#9 `hen `、
  Courier-en p1#9 `T `),反向改判 **0**,页级 curve/form 计数变动 **0 页**,
  改判者携带 `pdf_form`/`pdf_curve` **0** 个。消费者清单见 `t2_consumer_inventory.json`
  (22 站点,本批新做,逐站点以锚文本在当前树上定位)。
- **通用信号约束**:所用信号只有字号比、同字号 run 长度与字符顺序;不含刊物名、字体名、
  页码、段落 id 或任何取自样张的字符串。


## B11.7

| 文件 | 符号 | 调用方 | 目的 | 批次 |
| --- | --- | --- | --- | --- |
| `babeldoc/format/pdf/high_level.py` | `_do_translate_single`(三行调用与两行 import) | 流水线主干 | 两个新 pass 的挂点,均在主干上、magazine 侧无既有钩子够得到。(a) `formula_reclass.apply` 落在 `StylesAndFormulas` 之后、`PageClassifier` 之前:它要撤销的分组是前者做的,而后者与链检测都读段落文本,须在文本补全之后才读。(b) `rotated_lane.reset()` 与 `rotated_lane.write_report()` 夹住 `detectors.detect_issues`:车道是在修复回路里施加的,故其记录在回路跑完之后写,而不是自成一个 stage。两个 pass 默认关(`magazine_formula_reclass` / `magazine_rotated_lane` 缺省为假),开关抬起前逐位无行为差异 | B11.7 |
| `babeldoc/format/pdf/document_il/midend/typesetting.py` | 模块级 `LINE_HEAD_FORBIDDEN_PUNCTUATION`(新增);`TypesettingUnit.calc_is_hung_punctuation`(改读该常量) | `_layout_typesetting_units` 的悬挂标点分支;`chain_backfill._retreat_off_line_head` | 把该方法内联的 41 个字符的列表提到模块级冻结集合,方法改为读它。**行为逐位不变**:同一个集合、同一个 `in` 测试、同一个返回值。理由是 T2 的容量切要求"续段不得以行首禁排标点起头",而计划明写"复用排版器既有标点分类";把那 41 个字符抄进 magazine 侧会在树上留两份同样的表,正是 W-B11-18 认定为违规的形态。提取而非复制,是使"复用"这件事成立的最小改动 | B11.7 |

### 未做的改动,与为什么

**`babeldoc/format/pdf/document_il/midend/typesetting.py:861` 的 `vertical=False`**

计划 T3.4a 要求把它改为继承段落的 `vertical`。**本批不改**,理由是改了会错:该行构造的是
**stage 自己排出来的**译文字符,而 stage 对旋转段一律以水平轴排。让它继承段落标志,等于
把每一个旋转段的每一个译文字符都标成竖排 —— 包括车道从未认领、stage 已按水平摆好的那些 ——
渲染端随即以 `0 1 -1 0` 把它们旋转着画在水平位置上,那是比原缺陷更坏的结果。车道只在**它自己
摆放过的**字符上置该标志,作用面恰为它认领的段,无需任何上游改动。判定证据见
`examples/output/b11_7/t3_lane_feasibility.json` 的 `character_matrix` 项。

**`babeldoc/format/pdf/document_il/midend/il_translator.py:1043` 的 `if paragraph.vertical: return None, None`**

这是旋转段从未被译的**真正原因**,公式分组只是第二道闸。CLAUDE.md §2 禁止修改
`il_translator.py` 的行为,故**一字未改**,并按 §2 停止并报告(报告见批次交付报告 §3.4)。
用户裁决:走既有 react 孤行动作的第二类管辖(段落 `vertical`),不动该文件。该文件在本批的
`git diff` 中不出现。


## B11.8

| 文件 | 符号 | 调用方 | 目的 | 批次 |
| --- | --- | --- | --- | --- |
| `babeldoc/format/pdf/high_level.py` | `_do_translate_single`(一行调用)、模块级 import | 流水线主干 | 新 pass `drop_cap_render.apply` 的挂点。窗口:`dump_checkpoint("typesetting")` **之后**、`detectors.detect_issues` **之前**。在 checkpoint 之后,是为了让 `checkpoint.11_typesetting` 继续只表示"排版 stage 留下的样子";在检测之前,是为了让被检测的文档就是最终写进 PDF 的那一份。pass 默认关(`magazine_drop_cap_render` 缺省为假),开关抬起前逐位无行为差异。**计划的负向范围未列本文件**:计划把挂点写成"双向试装模块(新)",而一个排后 pass 需要一个主干调用点,magazine 侧唯一够得到的窗口是 `detectors.detect_issues` 头部。用户裁决取 high_level.py 而非 detectors/__init__.py,理由是位置直白且与既有 B8/B10.1/B11.5/B11.7 四处同类挂点同形。登记 W-B11-24 | B11.8 |
| `babeldoc/format/pdf/document_il/xml_converter.py` | 模块级 `_LazyPassthroughConverter`(新增)与一次 `converter.register_converter` 调用;`XMLConverter.to_xml` 与 `from_xml` **一字未改** | xsdata 序列化器的类型派发 | 见下方逐函数登记 | B11.8 |

### 逐函数登记(B11.8)

**`_LazyPassthroughConverter`(新增,模块级)**

`Converter` 子类,两个方法:`serialize(value)` 返回 `value.materialize()`;
`deserialize(value)` 原样返回。注册一次:
`converter.register_converter(LazyPassthroughInstruction, _LazyPassthroughConverter())`。

**为什么必须改**:`il_version_1.py:58` 把 `passthrough_per_char_instruction` 声明为
`str | None`,而前端在 `can_lazy_render` 分支里填进去的是 `LazyPassthroughInstruction`
—— 一个自述为「String-compatible wrapper」、`materialize()` 即那个字符串的包装。
同一文件里的 **JSON 写盘早就问了这个问题**(`_orjson_default` 调 `materialize()`),
**XML 写盘没问**,因为 xsdata 按具体类派发而该类没有注册转换器。后果是:一份持有
延迟指令的文档**能写成 JSON、写不成 XML**,而 checkpoint 走 XML —— 同一个字段的两个
reader 对「这份文档能不能写出来」给出相反答案。判例同 b8.4「一个 reader」:两路分歧
不存活。

**为什么现在才暴露**:旧六份样张都不进 `can_lazy_render` 分支;本批期间语料所有者
引入的中文源样张进。故这是**新语料触发的上游既有缺口**,不是 b11.8 的改动造成的。
表现为 `spec_check_b3_3` 在构建 artifact 时崩于
`ConverterError: No converter registered for 'LazyPassthroughInstruction'`。

**作用面**:仅当被序列化的值确为 `LazyPassthroughInstruction` 时才走到该转换器。
两条断言各自兑现一半 —— `spec_check_b11_8` 的 `07e` 断言含 lazy 字段的桩在 JSON 与
XML 两路上 materialize 后逐字节一致(**断言对称本身**);`07f` 断言不含 lazy 字段的桩
的 XML 渲染**修前修后逐字节相同**(修前基准在改动之前冻结,见
`examples/output/b11_8/xml_symmetry.json` 的 `plain`)。

**往返**:`deserialize` 原样返回。从 XML 读回来的已经是 materialize 之后的字符串,
与非 lazy 路径产出的类型相同,故经任一写盘往返都落在同一类型上。

### 未做的改动,与为什么

**`babeldoc/magazine/react/controller.py` 的 `_candidates` 过滤**

修复回路跑在本车道之后。若它挑中一个已被车道排好的段并重排之,首字放大会**静默丢失**。
预防的写法是在 `_candidates` 里按车道段引过滤,并在 `actions.py` 添一个拒绝理由常量 ——
两个文件,均在计划负向范围之外。用户裁决取**检测而非预防**:车道记下自己排过的段引,
门禁 `check_01g` 断言这些段引不出现在 `react_repair.report.json` 的 executed 段引里,
一旦相碰即红。理由是 CLAUDE.md §4.18 要防的是"改判即丢且无任何报错"里的**无报错**,
而红灯不是无报错。b11.7 实测两样张的修复回路都未触及这四段(Courier-en 触及
p1#10/p3#2/p5#10/p6#15,FD-en-v2 触及 p2#8/p4#3/p8#5/p9#9,与四条锚零交集)。
编码排除登记为 GAP-48。

**`babeldoc/format/pdf/document_il/midend/typesetting.py` 的行距**

首字字号 = 行数 × 行距,而行距在上游 `_layout_typesetting_units` 内部算出
(`max(font_size*scale*line_skip, mode_height*line_skip, max_height*1.05)`,
`line_skip` 为 1.50/1.3 两个裸字面量)。把 `line_skip` 提到模块级或抄进
`configs/drop_cap_render.json`,都会在树上留两份同一个数 —— 正是 W-B11-18 认定为违规的形态。
本批改为**从段落自身的基线实测行进量**,故上游一字未改,且任意正文字号的栏都得到成比例的首字。


## C01

| 文件 | 符号 | 调用方 | 目的 | 批次 |
| --- | --- | --- | --- | --- |
| `babeldoc/format/pdf/translation_config.py` | `TranslationConfig.__init__` | CLI、工具与公开 Python 配置入口 | 将正在使用的 21 个 magazine 开关全部公开为带兼容默认值的构造参数，并允许版本化 profile 在构造期间一次性提供有效值；未选择 profile 时保留原默认行为 | C01 |
| `babeldoc/main.py` | `create_parser`、`main` | BabelDOC CLI | 新增 `--magazine-profile` 正式入口并把所选文件交给 `TranslationConfig`，避免工具或测试脚本通过临时 `setattr` 才能启用功能 | C01 |
| `babeldoc/format/pdf/high_level.py` | `do_translate` | 同步与异步翻译入口 | 在读取、创建或修改 Document IL 前执行 magazine 依赖校验并写运行 manifest；非法组合在进入 PDF/IL 流水线前失败 | C01 |

## C02

| 文件 | 符号 | 调用方 | 目的 | 批次 |
| --- | --- | --- | --- | --- |
| `babeldoc/format/pdf/high_level.py` | `_do_translate_single` | 单文档 PDF 流水线 | 保存 ArticleBuilder 返回的唯一 `ArticleDocumentIR`，并显式传给 HITL 身份消费者、LLM-only 翻译器和缩进策略；sidecar 不再作为该次运行的身份来源 | C02 |
| `babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py` | `ILTranslatorLLMOnly.__init__`、`translate` | high-level LLM-only 翻译路径 | 接收同一 `ArticleDocumentIR`，article context 开启时直接用它规划 brief；缺少 canonical state 时拒绝重新分组 | C02 |

## C03

| 文件 | 符号 | 调用方 | 目的 | 批次 |
| --- | --- | --- | --- | --- |
| `babeldoc/format/pdf/high_level.py` | `_do_translate_single` | 单文档 PDF 流水线 | 在 ArticleBuilder 后冻结并创建唯一 `RunTrace`，显式传给翻译、排版与检测/修复路径；PDF 成功写出后绑定最终几何、验证终态并写统一 sidecar | C03 |
| `babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py` | `BatchParagraph`、`ILTranslatorLLMOnly.__init__`、`translate_paragraph` | high-level LLM-only 翻译路径 | 不改变请求内容或次数，在现有普通批请求边界记录稳定 source refs、prompt/config 哈希、translator 调用、whole target 与 fragment ranges | C03 |
| `babeldoc/format/pdf/document_il/midend/typesetting.py` | `Typesetting.__init__`、`typesetting_document` | high-level 与修复回路排版入口 | 接收同一可选 `RunTrace`，在完整排版结束时登记 pre-repair slot geometry；未传 trace 时行为保持不变 | C03 |

## C05

| 文件 | 符号 | 调用方 | 目的 | 批次 |
| --- | --- | --- | --- | --- |
| `babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py` | `ILTranslatorLLMOnly.translate` | LLM-only 翻译主路径 | 将 high-level 已注入的同一 canonical `ArticleDocumentIR` 显式传给 chain planner，使联合请求能在调用引擎前验证所有成员的文章身份；普通非 chain 请求路径不变 | C05 |

## C06

| 文件 | 符号 | 调用方 | 目的 | 批次 |
| --- | --- | --- | --- | --- |
| `babeldoc/format/pdf/document_il/midend/typesetting.py` | `Typesetting.fit_text_to_slot`、`SlotFitResult`、`LINE_TAIL_FORBIDDEN_PUNCTUATION` | continuity-chain allocation planner；既有 typesetting stage | 在固定目标字号和映射字体下复用真实断行器，返回最大合法 target 前缀、行指标与 ink bounds；测量只创建临时 units，不写 Document IL 或 PDF，正式排版路径保持原入口 | C06 |

## C07

| 文件 | 符号 | 调用方 | 目的 | 批次 |
| --- | --- | --- | --- | --- |
| `babeldoc/format/pdf/high_level.py` | `_do_translate_single` | 单文档 PDF 流水线 | 在 LLM-only 普通段落与 continuity chain 完成唯一翻译写回、括号去重与缩进策略都确定之后，正式排版之前调用 page-local article flow；复用同一 ArticleDocumentIR 与 RunTrace，开关关闭时旧路径不变 | C07 |

## C10

| 文件 | 符号 | 调用方 | 目的 | 批次 |
| --- | --- | --- | --- | --- |
| `babeldoc/format/pdf/high_level.py` | `_do_translate_single` | 单文档 PDF 流水线 | 将当前运行唯一的 canonical `ArticleDocumentIR` 与既有 `RunTrace` 一并显式传给最终 detector 聚合，使 ownership、slot capacity 与 hard-boundary 验收读取同一运行时身份；检测开关关闭时路径不变 | C10 |

## C11

| 文件 | 符号 | 调用方 | 目的 | 批次 |
| --- | --- | --- | --- | --- |
| `babeldoc/format/pdf/high_level.py` | `_do_translate_single` | 单文档 PDF 流水线 | 将 C03 创建的同一 `RunTrace` 显式传给翻译前 drop-cap intent 冻结/flatten 和 typeset 后 render，使源样式、intent、失败门控及目标首字符样式进入一条运行时追踪链；开关关闭时既有路径不变 | C11 |

## C12

| 文件 | 符号 | 调用方 | 目的 | 批次 |
| --- | --- | --- | --- | --- |
| `babeldoc/format/pdf/document_il/midend/typesetting.py` | `GlyphInkMetric`、`Typesetting.glyph_ink_metrics` | `babeldoc.magazine.drop_cap_render` | 暴露映射后字体对单个 Unicode code point 的真实 glyph ink bbox、advance 与 glyph id；接口只读字体映射，不改变既有排版或 Document IL | C12 |
| `babeldoc/format/pdf/high_level.py` | `_do_translate_single` | 单文档 PDF 流水线 | 将本次运行唯一的 `ArticleDocumentIR` 与刚完成正式排版的 `Typesetting` 实例传给 drop-cap render，使英文装饰首字读取同一文章 envelope 与映射字体度量；render 开关关闭时不执行任何新工作 | C12 |

## C15

| 文件 | 符号 | 调用方 | 目的 | 批次 |
| --- | --- | --- | --- | --- |
| `babeldoc/format/pdf/document_il/backend/pdf_creater.py` | `PDFCreater.__init__`、`restore_media_box`、`write`、`update_page_content_stream` | PDF 写出主路径 | 将原先仅记录日志并继续的 XObject font/stream、mediabox restoration 与 save fallback 转为结构化 writer warnings，随 `TranslateResult` 交给只读终态 validator；PDF 写出与 fallback 行为不变 | C15 |
| `babeldoc/format/pdf/high_level.py` | `do_translate`、`_do_translate_single`、PDF compliance 辅助函数 | 单文件与 split 合并流水线 | 在 CMap、metadata、TOC 和 split merge 全部完成后 reopen 真正交付的 mono PDF；聚合 part touched-page 期望与 warnings，并把 pass/degraded/fail 写回结果、运行 manifest 和 RunTrace | C15 |
| `babeldoc/format/pdf/translation_config.py` | `TranslationConfig.__init__`、`TranslateResult` | 公开 Python 配置与流水线返回值 | 公开兼容默认关闭的 `magazine_pdf_compliance` 开关，并显式返回报告路径、合规状态、fully-compliant 标志与 writer warnings | C15 |

## C16

| 文件 | 符号 | 调用方 | 目的 | 批次 |
| --- | --- | --- | --- | --- |
| `babeldoc/format/pdf/document_il/midend/typesetting.py` | `HANG_CONFIG_PATH` | 排版配置加载器 | 通过统一的源码/轮子资源定位器读取既有悬挂标点配置；调用方显式传入的路径仍优先 | C16 |
| `babeldoc/format/pdf/document_il/midend/styles_and_formulas.py` | `INITIAL_ADJACENT_CONFIG_PATH` | 放大首字邻接配置加载器 | 通过统一的源码/轮子资源定位器读取既有配置；调用方显式传入的路径仍优先 | C16 |
| `pyproject.toml` | 依赖、项目 URL 与 Hatch wheel force-include | 安装与构建入口 | 声明代码直接导入的 `regex`，把项目元数据指向 fork，并将根目录配置和提示词映射到 wheel 内 `babeldoc/_resources` | C16 |
| `.gitignore` | `uv.lock` 规则 | 依赖锁定 | 不再忽略可复现的依赖锁，使 C16 的锁文件刷新可提交 | C16 |
| `babeldoc/main.py` | `create_parser`、`effective_config_report`、`resolve_cli_credentials`、`build_translators`、`main` | CLI 启动入口 | 增加互斥内置 mode/自定义 profile、显式复核目录、模型加载前配置校验与稳定脱敏有效配置输出；普通翻译按 CLI/TOML、环境变量的优先级解析凭据，明确跳过翻译的路径使用无网络对象 | C16 |
| `babeldoc/format/pdf/translation_config.py` | `TranslationConfig.__init__` | CLI 与公开 Python 配置入口 | 接收 mode 和显式复核目录；mode 通过封闭注册表加载完整 profile，未选择时保持既有 22 个开关默认值 | C16 |
