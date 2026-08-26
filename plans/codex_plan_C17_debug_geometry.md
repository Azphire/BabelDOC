# Codex Plan C17：Debug overlay 隔离、原子几何写入与 ABB checkpoint 回放

计划版本：2026-08-26 rev.3  
两天编排：WT1首项，预计 5–6 agent-hours  
推荐执行模型：`gpt-5.6-sol`，reasoning `xhigh`  
网络/API：禁止翻译、术语、VLM、repair-manager 请求；只运行离线 checkpoint 与 parse-only。  
目标提交：`fix(debug): isolate overlays from semantic geometry`

## 0. 任务与完成边界

修复 ABB 第 3 页的 `geometry box coordinates must be ordered`，同时建立全局不变量：调试标注只存在于独立 overlay ledger 和最终渲染层，不能成为 `PdfParagraph`、ArticleIR element、chain endpoint、RunTrace source、fixed asset 或 detector input；任何语义 box 的修改必须以合法候选原子提交。

本计划不实现同页多文章/多章节。疑似页继续 `unsupported_same_page_multi_article` 和 no-reflow。本文件上下文自足；执行顺序上它是 C17→C18→C19 的第一项。

本计划的命令由 Codex 在 Linux/WSL Bash worktree 中执行。Windows PowerShell 用户无需手工复制 `timeout/export/test` 命令；若执行环境只有 PowerShell，Codex应使用其进程超时能力和 `uv run python` 等价检查，不调用 Windows 的 `timeout.exe`。

## 1. 权威与可复核输入

- Git 审计基线：`57a12552da7a13523ad5a2e27b45473f24183208`。
- 英文 TeX SHA-256：`a3e7a6237085d3879ab98f53265d3fac7450d18ee8610f6eb62230c6ba67fd08`。
- `ABB-zh.rar` SHA-256：`ca2af3fe9de87089b766dd698c9f200ae3afaf668b7d676d74fbac4cec42165b`。
- 原始 `examples/input/ABB-zh.pdf` 预期 SHA-256：`e8249e884bea2f35239f708247367105aac029e1b758d1905eda6d5f90802f97`。
- 归档 failed work input SHA-256：`e9d0b6c7351421a0dccd06694577e498c10508e05f2ea76c6bae2b4adbd477bc`；它不是原始输入，不能冒充 production rerun source。

当前审计环境已有仓库`babeldoc.zh-en.toml`（SHA-256 `0e704cddbf26e1a0da76e55c1a0cbdebbca3b19825f2246a9434e8ec98dd7ea9`），仍缺原始PDF。因此checkpoint replay可立即执行；production parse-only只有在hash正确的原始PDF进入执行worktree后才执行。缺失时报告`BLOCKED_PENDING_ORIGINAL_PDF`，代码修复与离线回归仍可完成。

## 2. Git/worktree 启动协议

由两天总调度器为本计划创建独立 worktree；本计划是唯一写入者：

```bash
git status --short --branch
git fetch origin
git rev-parse HEAD
git rev-parse origin/main
```

分支应基于总调度器冻结的 integration-base。若直接在 main 工作，只有工作树干净且 HEAD 可 fast-forward 时才执行：

```bash
git pull --ff-only origin main
```

发现用户改动、未知 staged file 或基线已含同类未审变更时停止；禁止 stash、reset、checkout 覆盖。

创建任务目录和 task-specific cache；不要修改 `HOME`：

```bash
mkdir -p .tmp/c17/archive .tmp/c17/replay .tmp/c17/parse-off .tmp/c17/parse-on
export UV_CACHE_DIR="$PWD/.tmp/c17-uv-cache"
```

## 3. 已确认根因

失败归档的 1-based page 3、`pdf_paragraph[11]` 为：

```json
{"unicode":"title","box":[54.0,117.70305,82.0,117.41005]}
```

`y > y2`。`title` 是 layout debug label。传播路径：

1. `LayoutParser.generate_fallback_line_layout_for_page()` 和 TableParser 的 debug helper 把 layout class label作为 `PdfParagraph` 追加到 page；
2. `ParagraphFinder` 把 page 中所有 paragraph 当语义对象；
3. overlap pass 用 `mid_y ± 1` 修改已有 box，没有合法候选 postcondition；
4. classifier、ArticleBuilder、RunTrace、fixed-asset inventory 和 detector 继续消费；
5. `RunTrace._checked_box()` 正确拒绝倒置框。

归档约有 373 个 debug label paragraph、176 个被 overlap 修改的 box，ArticleIR 200 个 elements 中约 145 个为 debug label。RunTrace 的严格检查不是问题，不得放宽或自动排序非法框。

另一个已确认风险：当前 `AddDebugInformation` 位于 Typesetting 和 post-typesetting detectors 之前；Typesetting 会把所有 paragraphs 放进空间索引并可能移动真实文字。仅把早期 layout labels 移走仍不能证明 debug on/off 语义等价。

## 4. 权威合同

英文 TeX 第 495、507、510、592、638、642 行要求显式中间状态、可处理元素边界、source→target→render 追踪、重排守恒、渲染 PDF 检查与人工约束合规。由此得到：

- diagnostic overlay 不是 source content、article content 或 fixed visual asset；
- debug 开关不得改变 classifier、ArticleIR、chain、translation request、typesetting、repair 或 validation 的语义输入；
- 非法语义 geometry 必须在最早写入点拒绝，错误带 stage/page/stable ref/before/candidate；
- debug on 仍须在最终 PDF/sidecar 中可观察，不能简单删掉调试能力。

## 5. 必须选择的架构：独立 DebugOverlayLedger

### 5.1 显式 provenance，不复用 `debug_info`

新增 closed provenance：

```text
ElementProvenance.SOURCE
ElementProvenance.DERIVED_SEMANTIC
ElementProvenance.DEBUG_OVERLAY
```

或语义等价的 typed ledger。禁止用现有 `debug_info` 布尔值推断 provenance，原因：

- `PdfParagraph` 本身没有统一 `debug_info` 字段；
- `AddDebugInformation` 只在嵌套 composition/char 标记；
- 真实源 shading/curve 也可能带 `debug_info=True`，全局过滤会丢 fixed assets。

只有完成inventory并列明的debug producer可创建`DEBUG_OVERLAY`：LayoutParser fallback labels/rectangles、TableParser labels/rectangles、ParagraphFinder line boxes、DetectScanned score helper、AddDebugInformation的框/文字，以及active/legacy IL frontend的`--show-char-box`。先用`rg "debug_info=True|show_char_box|_save_debug"`盘点每个writer，再以行为判定overlay；源PDF的shading/curve和content-filter notice属于SOURCE/DERIVED_SEMANTIC，不能因`debug_info=True`被过滤。TableParser/DetectScanned中当前未到达的helper也必须迁移到ledger或明确删除并以gate证明无调用点，不能留成未来绕过。未知producer不得自称overlay。

### 5.2 Ledger 内容

`DebugOverlayLedger` 是 run-scoped、不可作为 IL semantic element 的结构：

```text
schema_version
source_page_number
producer enum
overlay kind = label | box | line | point
box/points
text (bounded)
style token
related semantic stable_ref | null
```

约束：

- page identity 使用 physical source page number；
- box finite/ordered/page-bounded；
- text、count 和 coordinate ranges有上限；
- ledger 不被 checkpoint serializer当作 `pdf_paragraph`；可单独写 debug sidecar；
- overlay ID 不进入 semantic digest/cache/RunTrace。

### 5.3 流水线时序

按以下顺序实现：

```text
parse semantic IL
→ ParagraphFinder / classifier / chain / ArticleIR / RunTrace
→ translation / semantic Typesetting / repair
→ build DebugOverlayLedger from final semantic geometry
→ PDFCreater renders semantic PDF
→ FinalPdfValidator validates the non-overlay semantic PDF
→ writer-level overlay pass draws ledger on a separate debug copy
```

必须修改当前 `high_level.py` 时序：`AddDebugInformation` 不再向即将进入 Typesetting/detectors 的 `docs.page[].pdf_paragraph` 追加对象。

### 5.4 Writer-level 渲染

选择一个实现并写死：扩展 `PDFCreater.write_debug_info()`，在正常 PDF 已生成后消费 ledger，在 debug copy 上用 writer/PyMuPDF 的 rectangle/text drawing API 绘制。不得把 overlay 重新塞回 semantic IL 或语义 Typesetting 的 spatial index。

要求：

- label、box、颜色在 debug PDF 中可见；
- 只有`effective_debug=false`且`effective_show_char_box=false`时ledger为空且不生成debug artifact；show-char-only时ledger只含char boxes，不含layout/paragraph/formula等其他labels；
- overlay pass 失败时保留已通过validator的正常 non-debug PDF并返回 typed debug-artifact error；
- overlay 不改变 MediaBox、CropBox、rotation、正文 glyph、fixed assets 或 page count；
- `pdf_creater.py` 明确进入变更文件面和测试。

## 6. 几何原子写入

新增共享 helper，所有本批会修改 paragraph box 的路径必须调用：

```text
propose(before, candidate, page_bounds, stage, stable_ref)
→ validate finite
→ validate x <= x2 and y <= y2
→ validate positive area for processable text
→ validate page/role constraints
→ commit candidate OR keep before and emit typed refusal
```

禁止：

- 对非法框调用 `sorted()`、clamp 或交换端点后继续；
- 先改 `y` 再改 `y2` 的半状态；
- 修改 debug overlay 来“修复”语义 overlap；
- 用 `debug_id` 作为稳定 ref；
- 对合法 marker/passthrough 强制正面积。先盘点 zero-area对象并把 `processable text` 与合法 marker 的规则分开。

至少覆盖 `ParagraphFinder.fix_overlapping_paragraphs()` 和同批发现的共用 geometry writer。`RunTrace._checked_box()` 保持严格，仅增强错误上下文：source page、stage、stable ref、role/provenance、before/candidate。

## 7. Debug CLI 优先级

在 `babeldoc/main.py` 提供可逆 CLI：

```text
--debug      强制 true
--no-debug   强制 false
未提供       服从 TOML/default
```

使用同一 `dest=debug` 的互斥参数，默认值与 configargparse precedence 必须通过行为测试。`--no-debug` 是 C22 重放用户原 TOML 的前置能力，不能留到最终验收临时实现。

`--show-char-box`兼容规则写死：它单独出现时只请求char-box ledger/debug artifact，不自动开启其他labels；CLI同时给`--show-char-box --no-debug`在argparse阶段拒绝。TOML中的show-char-box遇到CLI `--no-debug`时由CLI master override为false并写redacted effective config。任何char box都不得写`page.pdf_rectangle` semantic IL。

`--print-effective-config` 需准确显示最终 bool，同时继续 redacted credential/base URL query。

## 8. 分阶段 semantic fingerprints

当前 runtime preflight manifest 在 IL 生成前写出，不能伪称含 post-parse fingerprint。升级 manifest/schema，允许原子追加 stage records：

```text
preflight: input/config/profile/code digests
post_article_ir: semantic source + ArticleIR digest
post_typesetting: semantic target geometry/text digest
post_repair: accepted semantic state digest
debug_overlay: ledger digest（单独，不并入前三项）
```

canonical projection明确：

- schema/version和stage写入 hash；
- physical page number、stable source refs、closed role、normalized text、semantic boxes、reading order；
- float 使用 finite decimal，round-half-even 到 `1e-4` PDF point，`-0` 归零；
- arrays按声明的 reading order/stable key，不按 volatile debug ID；
- 路径、timestamp、worker ID、random debug ID、overlay item 不进入 semantic hash。

manifest 更新采用临时文件+atomic replace。Debug on/off 的前三阶段 digests必须相同，ledger digest可不同。

## 9. 预期文件面

按实际模块名调整，但至少审计：

```text
babeldoc/main.py
babeldoc/format/pdf/high_level.py
babeldoc/format/pdf/new_parser/native_parse.py
babeldoc/format/pdf/document_il/frontend/il_creater_active.py
babeldoc/format/pdf/document_il/frontend/il_creater.py
babeldoc/format/pdf/document_il/midend/detect_scanned_file.py
babeldoc/format/pdf/document_il/midend/layout_parser.py
babeldoc/format/pdf/document_il/midend/table_parser.py
babeldoc/format/pdf/document_il/midend/paragraph_finder.py
babeldoc/format/pdf/document_il/midend/add_debug_information.py
babeldoc/format/pdf/document_il/midend/typesetting.py
babeldoc/format/pdf/document_il/backend/pdf_creater.py
babeldoc/magazine/run_trace.py
babeldoc/magazine/fixed_assets.py
babeldoc/magazine/runtime_profile.py
```

新增模块建议：

```text
babeldoc/magazine/debug_overlay.py
babeldoc/magazine/geometry_write.py
tools/replay_debug_geometry_checkpoint.py
spec_checks/spec_check_debug_semantic_invariance.py
spec_checks/spec_check_debug_overlay_render.py
spec_checks/spec_check_geometry_write_guard.py
```

新 fast gates 必须声明 `GATE_SET = "fast"`。本分支直接逐项运行并把准确文件名交给 WT0；只有 WT0 integration owner 修改 `spec_checks/run_all.py` 与 `spec_check_gate_registration.py` 的 canonical registry，避免并行分支争写。合入后由 WT0 验证注册存在、唯一、顺序正确。

## 10. 测试先行

### 10.1 `spec_check_debug_semantic_invariance.py`

同一 synthetic page debug off/on 运行到 post-repair：

- semantic page/paragraph count、classifier features、ArticleIR、chain、RunTrace、fixed assets、detectors、translation request cache key、前三阶段 fingerprints完全相同；
- 在`show_char_box=false`条件下，debug on ledger非空、debug off ledger空；另测show-char-only ledger非空且kind集合恰为char box，三种模式的semantic fingerprints仍相同；
- 已知真实 source `debug_info` curve/shading仍留在 fixed assets，证明没有按 bool 误滤。

### 10.2 `spec_check_debug_overlay_render.py`

生成两份小 PDF：

- non-debug PDF 与 debug PDF 的 page boxes、正文提取、semantic glyph boxes、图片/curve fingerprints相同；
- debug PDF 额外可见 label/rectangle；
- overlay文字无需进入 semantic Typesetting；
- overlay pass 不修改 semantic docs；
- 用spy validator/writer断言调用顺序：FinalPdfValidator只收到non-overlay semantic PDF并成功返回后，overlay writer才可运行；validator从未读取debug copy；
- overlay failure只影响debug artifact，返回/保留的是已经通过validator且hash未变的semantic PDF，不毁掉正常PDF。

### 10.3 `spec_check_geometry_write_guard.py`

覆盖 normal/overlap/zero-height/NaN/Inf/reversed/out-of-page：

- 合法 candidate原子 commit；
- 非法 candidate保留 before；
- processable text正面积，合法 marker走独立规则；
- 没有半写入；
- error含 stage/source page/stable ref/before/candidate；
- RunTrace继续拒绝人工注入非法框。

### 10.4 CLI 测试

扩展 `spec_check_cli_credentials.py` 或新增 fast gate：TOML true/false × absent/`--debug`/`--no-debug` 六种组合；再覆盖active与legacy frontend的show-char-box only、show-char-box+no-debug CLI冲突、TOML show-char-box被CLI no-debug覆盖。每种组合证明semantic IL/fingerprints不变、diagnostic只在ledger/debug copy，effective config与运行config一致，输出无secret。

## 11. ABB 失败归档精确回放

总调度器必须在创建worktree前把用户附件只读materialize/extract一次，并向所有worktrees传同一个绝对路径变量。当前审计环境已准备：

```bash
export ABB_FAILURE_ROOT="/workspace/scratch/c4885b0ecb55/abb_extracted"
test -d "$ABB_FAILURE_ROOT/ABB-zh/work/ABB-zh"
```

若在另一执行环境，调度器使用该环境已有的RAR解压能力将SHA为`ca2a…`的附件解到新的共享临时目录，再设置`ABB_FAILURE_ROOT`；各计划不得自行假设`7z/unrar`存在，也不得在各worktree重复解压。变量未设置或目录不完整时以`BLOCKED_PENDING_ABB_FAILURE_ROOT`停止。

回放工具输入固定为：

```text
ABB-zh/work/ABB-zh/checkpoint.03_layout_generator.xml
ABB-zh/work/ABB-zh/layout_generator.json
ABB-zh/work/ABB-zh/checkpoint.05_paragraph_finder.xml
ABB-zh/work/ABB-zh/checkpoint.08_chain_builder.xml
ABB-zh/work/ABB-zh/article_ir.json
```

执行前验证关键artifact hashes：

```text
checkpoint.03_layout_generator.xml ba5c433f2091c911600ac8f08ad36e4c67bb99f5aee0a74aba0d11bac4ace21f
layout_generator.json              eecf3e3ee792fb8fa6351d553f5232006937a105e3bf27eaf562973be404f14e
checkpoint.05_paragraph_finder.xml 30ec4744ded147c1201cd6d60008528d25c96d231769725cc3d558ef35467c1f
checkpoint.08_chain_builder.xml    1c3f88ef69950e8a8bac3c24e8347b1b69da2996b1f07f673d01499cf0e1800f
article_ir.json                    f522279e66d4bcd003c4cd05ca01a69f3a9ac0367c7d3a4ccd7fa1c437d9e440
```

legacy checkpoint 没有新 provenance。回放适配器只在此诊断工具内，通过 `layout_generator.json` 的 `(physical page, class_name, layout box)` 精确匹配旧 debug labels并投影到 overlay ledger；歧义或 unmatched item失败，生产代码不得使用文本 `title/plain text` 猜 provenance。

```bash
timeout 180s uv run python tools/replay_debug_geometry_checkpoint.py \
  --root "$ABB_FAILURE_ROOT/ABB-zh/work/ABB-zh" \
  --source-page 3 \
  --report "$PWD/.tmp/c17/replay/report.json"
```

必须断言：

- 原归档 page 3 paragraph 11 的 `[54,117.70305,82,117.41005]` 被报告为 legacy debug contamination；
- 回放从 layout→ParagraphFinder→classifier/chain→ArticleIR/RunTrace 的新路径不产生倒置框；
- semantic state中 legacy debug labels计数为0，overlay ledger保留对应 diagnostics；
- 不放宽 RunTrace；
- report记录归档和各 checkpoint hash，不写绝对用户路径。

## 12. 原始 PDF 全结构 parse-only（输入存在时）

本批发生在C20B的source-bound subset projection之前；当前legacy v2 loader会把full decisions中的未选页判为不存在。因此这里保留9页完整source/HITL scope，只跳过translation，不能提前裁成`--pages 3`。两次都使用仓库hash固定TOML，唯一差异是debug override：

```bash
timeout 720s uv run babeldoc \
  --config ./babeldoc.zh-en.toml \
  --magazine-mode hitl-apply \
  --magazine-reviews-dir ./reviews \
  --files ./examples/input/ABB-zh.pdf \
  --skip-translation \
  --no-debug \
  --working-dir ./.tmp/c17/parse-off/work \
  --output ./.tmp/c17/parse-off/output

timeout 720s uv run babeldoc \
  --config ./babeldoc.zh-en.toml \
  --magazine-mode hitl-apply \
  --magazine-reviews-dir ./reviews \
  --files ./examples/input/ABB-zh.pdf \
  --skip-translation \
  --debug \
  --working-dir ./.tmp/c17/parse-on/work \
  --output ./.tmp/c17/parse-on/output
```

当前legacy v2 decisions只在完整9页scope用于C17 parse regression；本批不迁移HITL。两次应exit 0、page count/physical identity均为9、越过ArticleIR/RunTrace/semantic Typesetting；全本semantic stage digests相同；debug PDF含overlay；第3页日志无原geometry/slate error。任何外部request count必须为0。若原始PDF缺失，将此项标为外部acceptance pending，由C22在同一两天窗口补跑，不能用failed work input替代；仓库config必须通过hash与`--validate-config`检查。

## 13. 必跑 fast gates

```bash
timeout 90s uv run python spec_checks/spec_check_debug_semantic_invariance.py
timeout 90s uv run python spec_checks/spec_check_debug_overlay_render.py
timeout 90s uv run python spec_checks/spec_check_geometry_write_guard.py
timeout 90s uv run python spec_checks/spec_check_run_trace.py
timeout 90s uv run python spec_checks/spec_check_fixed_asset_guard.py
timeout 90s uv run python spec_checks/spec_check_cli_credentials.py
timeout 90s uv run python spec_checks/spec_check_gate_registration.py
timeout 600s uv run python spec_checks/run_all.py --set fast
```

不得删除旧测试或以源码字符串检查替代行为断言。

## 14. 提交与交接

先检查实际变更，精确 stage 本批文件，不得 `git add -A`：

```bash
git status --short
git diff --check
git diff --stat
git add -- \
  babeldoc/main.py \
  babeldoc/format/pdf/high_level.py \
  babeldoc/format/pdf/new_parser/native_parse.py \
  babeldoc/format/pdf/document_il/frontend/il_creater_active.py \
  babeldoc/format/pdf/document_il/frontend/il_creater.py \
  babeldoc/format/pdf/document_il/midend/detect_scanned_file.py \
  babeldoc/format/pdf/document_il/midend/layout_parser.py \
  babeldoc/format/pdf/document_il/midend/table_parser.py \
  babeldoc/format/pdf/document_il/midend/paragraph_finder.py \
  babeldoc/format/pdf/document_il/midend/add_debug_information.py \
  babeldoc/format/pdf/document_il/midend/typesetting.py \
  babeldoc/format/pdf/document_il/backend/pdf_creater.py \
  babeldoc/magazine/debug_overlay.py \
  babeldoc/magazine/geometry_write.py \
  babeldoc/magazine/run_trace.py \
  babeldoc/magazine/fixed_assets.py \
  babeldoc/magazine/runtime_profile.py \
  tools/replay_debug_geometry_checkpoint.py \
  spec_checks/spec_check_debug_semantic_invariance.py \
  spec_checks/spec_check_debug_overlay_render.py \
  spec_checks/spec_check_geometry_write_guard.py \
  spec_checks/spec_check_cli_credentials.py
git diff --cached --check
git diff --cached --stat
git commit -m "fix(debug): isolate overlays from semantic geometry"
```

不存在或实际未修改的 path 从 `git add` 列表移除；新增的等价文件用精确 path加入。交接给 integration owner：commit、changed paths、overlay schema、fingerprint schema、fast gate exit codes、RAR replay report/hash、production parse状态和所有 blocker。

## 15. 完成与停止条件

完成必须同时满足：

- 已知 debug producers只写 overlay ledger；无 debug paragraph进入 semantic IL；
- AddDebugInformation 不在 semantic Typesetting/detectors 前注入对象；
- writer-level overlay在最终 debug PDF可见且不改正文/fixed assets；
- source `debug_info` assets未被误删；
- geometry candidate原子写入，RunTrace仍严格；
- `--debug/--no-debug` precedence可验证；
- 三阶段 semantic fingerprints debug on/off一致；
- 新 gates声明为fast、分支内直接运行全绿，且WT0合入后完成canonical注册验证；
- RAR page 3 exact replay通过；原始 PDF存在时两次 parse通过；
- 同页多文章策略未变。

遇到以下任一项立即停止并报告：

- 需要按 label文本或通用 `debug_info` 猜 production provenance；
- writer无法渲染 overlay且唯一方案会重入 semantic Typesetting；
- 合法 source asset因过滤消失；
- RunTrace必须放宽才能继续；
- RAR/checkpoint hash不符或 legacy匹配有歧义；
- 任何测试发起外部模型请求；
- 时间盒到 6 小时仍未完成核心不变量。此时交付最小复现、已通过 gates和明确剩余项，不提交伪修复。
