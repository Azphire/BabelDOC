# Codex Plan C20C：Non-contiguous page mapping、typeset/final HITL compliance 与 PDF validator

计划版本：2026-08-26 rev.3  
两天编排：WT3完成C20B接口seed并由WT0合入后，在同一seed branch继续执行；与C19/C20B remainder并行，预计5–7 agent-hours  
推荐执行模型：`gpt-5.6-sol`，reasoning `xhigh`  
网络/API：生成PDF/IL与fake expectations；禁止真实模型请求。  
目标提交序列：

1. `fix(pdf): map targeted output pages to physical source pages`
2. `feat(hitl): validate manual constraints in typeset and final pdf`

## 0. 任务

修复`--only-include-translated-page`对非连续页的内部页号/validator错误，并完成HITL expectation的typeset与final PDF阶段：

- output index 0..N-1显式映射到physical source pages；
- FinalPdfValidator、RunTrace、fixed assets、page labels/boxes/rotation、ArticleIR/manual refs全部按映射验证；
- 人工术语、page policy、drop cap在typeset state与final PDF分别给出可复核证据；
- 修复targeted output的TOC迁移异常；
- 提供通用自动验收与contact-sheet渲染入口，供C22直接使用。

本文件上下文自足。它只能在C20B Commit 1的canonical Expectation接口已合入后开始，直接导入该类型，不创建临时stub或adapter。它不实现同页多文章；unsupported/no-reflow继续生效。命令由Codex在Linux/WSL Bash worktree执行。

## 1. 权威、基线与已知故障

- 审计基线：`57a12552da7a13523ad5a2e27b45473f24183208`。
- 英文TeX SHA-256：`a3e7a6237085d3879ab98f53265d3fac7450d18ee8610f6eb62230c6ba67fd08`。
- TeX 638：rendered PDF上检查page count/dimensions、fixed assets、article attribution、chain conservation、untouched content。
- TeX 642：人工术语、page policies、initial-letter styles要在对应target paragraphs与final PDF核查。

当前代码已确认：

- `final_pdf_validator.py`先要求`source_labels == output_labels`，geometry从`len(source)==len(output)`开始；
- output page n与source page n直接比较，无法验证`2,3,8,9 -> output 1..4`；
- physical page 8/9的RunTrace/ref可能索引不到4页output；
- `high_level.py::migrate_toc`在targeted path含`for i in len(old_doc)`，有outline时会TypeError且外层可能只记录异常。

外置验收脚本不能替代pipeline内validator；必须先修`ComplianceExpectations`和生产mapping。

## 2. 并行接口冻结与前置行为

C20C只在C20B Commit 1 `refactor(hitl): define canonical manual expectation protocol`已合入WT0后创建分支。该canonical Expectation语义固定为：

```text
expectation_id
kind = term | page_policy | drop_cap
human_value
source_occurrence_refs[]
selected_occurrence_refs[]
source_binding_sha256
delivery_status/evidence
target_status/evidence
typeset_status/evidence
final_pdf_status/evidence
```

C20C直接导入该canonical类型；禁止创建本地protocol/dataclass stub，避免merge时才决定ownership。

```bash
git status --short --branch
git rev-parse HEAD
mkdir -p .tmp/c20c/fixtures .tmp/c20c/render
export UV_CACHE_DIR="$PWD/.tmp/c20c-uv-cache"
```

行为前置：physical page identity稳定、RunTrace terminal mapping存在、fixed asset inventory有physical page refs、debug overlay不在semantic PDF。若这些gate不存在/失败，`BLOCKED_BY_TARGETED_MAPPING_PREREQUISITE`。

## 3. Canonical PageSelectionMap v2

C18已定义唯一canonical `PageSelectionMap`及module。本批只把同一类型/schema升级到v2并贯穿result/manifest/validator；禁止新建`TargetedPageMap`、平行dict或从report反向重建第二份真相：

```text
PageSelectionMap v2:
  source_pdf_sha256
  source_page_count
  selected_physical_pages[]        # ordered, unique
  output_index_to_physical_page{}  # output 0-based -> source 1-based
  physical_page_to_output_index{}
  mapping_sha256
```

规则：

- 正常全本运行为identity map；
- `--only-include-translated-page`按用户selection order或canonical ascending规则生成，规则必须与CLI现有语义一致并测试；
- duplicate/reversed/invalid range在CLI parsing阶段拒绝，不让map歧义；
- 每个target fragment/fixed asset/article/ref/report同时保留physical source page与output index，不能覆盖其中之一；
- 未选physical page查询output index返回typed absent；
- mapping进入ComplianceExpectations/manifest/report digest；
- 本两天批次不支持一页拆多页或多页合一；出现page split/merge请求时typed `UNSUPPORTED_OUTPUT_CARDINALITY_CHANGE`，不得用当前单值双向dict猜映射。未来需要时另立multimap schema与计划。

## 4. ComplianceExpectations与validator迁移

扩展`ComplianceExpectations`：

```text
page_selection_map
expected_source_page_geometry_by_physical_page
expected_page_labels_by_physical_page
fixed_assets_by_physical_page
article/chain/runtrace refs by physical page
manual_constraint_expectations
```

Validator以不含diagnostic overlay的semantic target PDF为合规对象；debug copy另做overlay不变性检查。对semantic output的每个index：

1.通过map取得physical source page；
2.读取该source page的MediaBox/CropBox/rotation/label；
3.比较对应output page；
4.将final glyph/element证据写回physical refs；
5.检查selected pages恰好全覆盖一次，无多/少/重复；
6.未选source pages不要求出现在output，但其decisions在C20B报告为not_selected。

全本identity regression必须保持。Page label比较使用selected source labels按mapping投影，不再全source list直接相等。

RunTrace terminal lookup、fixed asset IoU、article attribution、untouched content、chain conservation和drop-cap refs全部使用map resolver。禁止在各validator各写一份`page-1`算术。

## 5. TOC/outline targeted regression

修复`migrate_toc`：

- 遍历使用合法`range(len(old_doc))`或document iterator；
- outline destination从physical source page通过canonical PageSelectionMap投影；
- 指向未选页的outline entry按明确policy删除或保留不可跳转文本，不得指错output page；
- selected destination页号重映射正确；
- 异常不能只warning后继续生成声称compliant的PDF；targeted TOC migration failure应使validation fail或typed residual。

增加source有outline、selected pages `2,3,8,9`的fixture，证明无TypeError且destinations正确。

## 6. Typeset/final manual compliance

### 6.1 通用状态机

Mandatory expectation只有C20B的delivery与target均pass，才评typeset/final；versioned policy声明的protected/fixed occurrence可在每stage保持带evidence的`not_applicable`并进入untouched验证。每个stage状态：

```text
pass | fail | pending | not_exercised | not_selected | not_applicable
```

`not_applicable`只来自versioned policy表，带rule ID；模型不能决定。`not_exercised`只用于配置明确跳过该stage的诊断运行（例如`skip_translation`），必须带scope/reason，不能在full translation acceptance中计pass。`pending`表示当前full pipeline尚未到达但最终必须完成；final report中pending失败。Final report不得从actual output生成expected value。

定义两个validation scopes：

- `parse_only`：要求source binding、page projection、semantic geometry、ArticleIR/RunTrace source registration、fixed assets和PDF mapping通过；delivery/target/typeset/final manual stages为`not_exercised`，整体只能是`parse_gate_pass`，不能叫full compliance；
- `full_translation`：所有selected mandatory manual stages必须pass，任何pending/not_exercised均使整体失败。

### 6.2 术语

C20B occurrence manifest先把selected occurrences分成`eligible`与`protected_fixed`。只有eligible是四stage mandatory；protected/fixed在typeset/final保持`not_applicable`，必须带versioned rule ID、fixed-asset fingerprint和untouched evidence，不能静默删除或用别处字符串补偿。

Typeset：

- 每个eligible selected occurrence的target span有RunTrace terminal fragment(s)；
- 按chain/fragment order拼合后，用C20B normalization version严格等于human target；
- repair generation未改写为其他词；
- glyph boxes合法并位于mapped article/page region。

Final PDF：

- 从对应output page/region的glyph mapping或同一稳定text extractor取得字符；
- 目标`ABB Review`在绑定occurrence处存在；
- 只在别页/别article出现不能补偿；
- 缺字、重复、乱码、被裁切或不可映射均fail；
- 避免纯page-wide substring：证据必须回连target span/RunTrace/final glyph range。
- protected/fixed occurrence的source asset fingerprint与位置不变；若被翻译、丢失或没有rule evidence则fail。

### 6.3 Page policy

读取C20B `page_policy_observables.json`，补全final observable：

- `translate`: selected translatable refs在final PDF有terminal glyph或明确protected passthrough；
- `chain_eligible=false`: final/trace中无跨该页chain；true仍不强制有chain；
- `starts_article/opens_article`: final content attribution不跨hard start/new owner；
- `preserve_line_structure`: record order/count和mapped line groups守恒；
- `indent_eligible`: typeset indent token与final first-line geometry相符；不eligible无新增body indent；
- `repair_profile`: accepted repair records属于profile且final geometry通过；
- 无法直接视觉观察的字段用上述trace/attribution evidence，不可只写“policy loaded”。

每个taxonomy page kind必须能解析到完整policy字段+observable规则；unknown缺规则startup失败。

### 6.4 Drop cap

Typeset：keep/flatten路径、target first character、role/owner、layout generation与geometry证据一致。  
Final：字符存在一次、无duplicate/loss；keep按中文two-line embedded或英文single-line enlarged的现有规则检查尺寸/基线/占位；flatten按普通body。判断用bound paragraph/ref，不按视觉上任意大字猜。

## 7. 通用自动验收器与contact sheet

新增`tools/verify_targeted_pdf_run.py`，输入：source PDF、由manifest唯一指定的semantic output PDF、可选debug copy、run dir/manifest、expectations、selected pages、report path。它调用生产validator/同一mapping，不复制规则。若只发现debug copy或两份候选无法判定，fail closed。输出：

```text
input/mapping/config/code hashes
page geometry/labels
semantic geometry legality
article/chain/RunTrace/fixed assets
repair transaction summaries
manual expectation stage statuses
residuals
formal metric status passthrough
overall pass/fail
```

新增`tools/render_targeted_contact_sheet.py`：PyMuPDF/Poppler 144dpi渲染，按canonical PageSelectionMap标physical source page，在页外margin标注，2×2排列；不覆盖正文，不联网。

两个工具不得硬编码ABB、page 3、debug ID或publication name。

## 8. 测试

### 8.1 `spec_check_targeted_page_compliance.py`

生成9-page source与4-page output fixture，map `2,3,8,9 -> 0,1,2,3`：

- page count/order/boxes/rotation/labels正例；
- wrong/repeated/missing page、dimension/rotation/label mismatch失败；
- physical ref 8/9正确映射，无index error；
- fixed assets/article/chain/RunTrace均按map；
- full identity map regression；
- page split/merge在本批typed unsupported且不得产出歧义map；
- source outline selected/unselected destinations正确，无`for i in len`错误。

### 8.2 `spec_check_manual_constraint_final.py`

- eligible term occurrences四stage全pass；protected/fixed occurrences显式not_applicable+asset evidence；
- 静默漏occurrence、把protected误算mandatory或用错误page字符串补偿均失败；
- model target错误、typeset改坏、final缺字/重复/错页/错article分别失败；
- page policy每个字段至少一正一负；
- policy只load未执行失败；
- English/Chinese drop-cap keep和flatten，duplicate/lost/wrong geometry负例；
- pending不能计pass，not_selected/not_applicable规则正确；
- parse_only把四个translation-dependent stages标not_exercised且只返回parse_gate_pass；full_translation遇到not_exercised失败；
- expectation始终来自human value。

另加debug copy正例：semantic PDF先通过final compliance；overlay copy与semantic PDF的正文glyph、page boxes和fixed assets相同，只多diagnostic drawing。Overlay文字不计term/page/drop-cap满足证据。

### 8.3 `spec_check_targeted_pdf_acceptance.py`

覆盖通用工具：合法2-page PDF、illegal geometry、missing terminal、fixed asset变化、manual term错页、report mapping错配、contact-sheet页序/label；并构造整个run tree中的普通translator cache error、provider retry/refusal、repair request log和report，确认simulated credential/raw prompt/full response/原文译文payload被检测且scanner从不回显内容。

所有新gate声明`GATE_SET="fast"`。本分支直接逐项运行并把准确文件名交给WT0；只有WT0 integration owner修改统一`run_all.py` registry/meta-test，合入后验证存在、唯一、依赖顺序正确。

## 9. 必跑回归

```bash
timeout 90s uv run python spec_checks/spec_check_physical_page_identity.py
timeout 90s uv run python spec_checks/spec_check_article_ir_contract.py
timeout 90s uv run python spec_checks/spec_check_chain_owner_scope.py
timeout 90s uv run python spec_checks/spec_check_article_state_checkpoints.py
timeout 90s uv run python spec_checks/spec_check_run_trace.py
timeout 90s uv run python spec_checks/spec_check_fixed_asset_guard.py
timeout 90s uv run python spec_checks/spec_check_pdf_compliance.py
timeout 90s uv run python spec_checks/spec_check_drop_cap_english.py
timeout 90s uv run python spec_checks/spec_check_drop_cap_chinese.py
timeout 90s uv run python spec_checks/spec_check_targeted_page_compliance.py
timeout 90s uv run python spec_checks/spec_check_manual_constraint_final.py
timeout 90s uv run python spec_checks/spec_check_targeted_pdf_acceptance.py
timeout 90s uv run python spec_checks/spec_check_gate_registration.py
timeout 600s uv run python spec_checks/run_all.py --set fast
```

与C20B合并后再跑：

```bash
timeout 90s uv run python spec_checks/spec_check_hitl_source_binding.py
timeout 90s uv run python spec_checks/spec_check_manual_constraint_delivery.py
timeout 90s uv run python spec_checks/spec_check_manual_constraint_final.py
```

## 10. 提交与交接

Commit 1：PageSelectionMap v2、ComplianceExpectations/FinalPdfValidator迁移、TOC fix和mapping gate。  
Commit 2：typeset/final expectation evaluator、通用validator/contact sheet和两项gates。

每次精确stage：

```bash
git status --short
git diff --check
git add -- <逐项审阅的high_level/final-validator/hitl/tool/spec_paths>
git diff --cached --check
git diff --cached --stat
git commit -m "<固定commit主题>"
```

禁止`git add -A`。交接：两个commit、mapping/schema versions、TOC policy、manual final observable表、测试exit codes、生成fixture/report/contact sheet paths。Integration owner验证分支始终只使用C20B的canonical Expectation类型，仓库中不存在第二份protocol/stub。

## 11. 完成与停止条件

完成：

- non-contiguous output有唯一显式physical↔output mapping；
- pipeline FinalPdfValidator自身支持mapping，非靠外部脚本掩盖；
- page geometry/labels/assets/article/chain/trace/manual refs都用同一resolver；
- targeted TOC无TypeError且destinations正确；
- term/page policy/drop-cap有typeset/final证据；
- wrong page/article substring不能伪pass；
- 通用acceptance/contact sheet工具和fast gates全绿；
- full-document regression通过；
- 同页多文章策略未变；
- 无API、无secret/raw prompt artifact。

停止：physical identity前置失败、C20B canonical interface seed尚未合入或发生语义冲突、现有PDF extractor无法回连glyph/RunTrace且只能page-wide substring、page policy无可验证consumer、targeted map需改source IDs、TOC异常只能被swallow、测试联网，或7小时到达仍不能让pipeline validator验证`2,3,8,9`。不得把失败推迟到C22唯一paid job。
