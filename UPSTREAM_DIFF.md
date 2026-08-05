# Upstream Diff Registry

Every modification to an upstream BabelDOC file must be registered here in the
same session it is made.

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
