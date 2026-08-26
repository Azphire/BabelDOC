# Codex Plan C21：Formal evaluation readiness、代理指标改名与 fail-closed

计划版本：2026-08-26 rev.3  
两天编排：WT2在C20A transport commit后执行，预计 3–5 agent-hours  
推荐执行模型：`gpt-5.6-sol`，reasoning `high`  
网络/API：只读冻结报告与synthetic manifests；禁止模型调用、PDF重翻和corpus sweep。  
目标提交：`fix(eval): fail closed on non-methodology proxies`

## 0. 任务

让评测代码准确表达英文TeX：

- 当前publication replay不是formal LOPO，改名为descriptive matrix；
- 当前shared-substring grouping不是word-aligned LTCR，改名为proxy；
- 当前endpoint-window judge不是formal seam MQM，标为exploratory；
- formal LOPO/LTCR/seam-MQM只有在机器可验证的methodology evidence齐全时才计算，否则`computation_status=not_computed`、value null、精确reason codes、CLI退出3；
- 历史冻结结果原字节保留，用sidecar erratum说明语义。

两天内不伪造fold training、word alignment或adjudication。本文件上下文自足，不改翻译runtime，也不支持同页多文章。命令由Codex在Linux/WSL Bash worktree执行。

## 1. 权威、基线与真实现状

- 审计基线：`57a12552da7a13523ad5a2e27b45473f24183208`。
- 英文TeX SHA-256：`a3e7a6237085d3879ab98f53265d3fac7450d18ee8610f6eb62230c6ba67fd08`。

TeX合同：

- 626：每fold只用其他publications确定page policies、thresholds、prompt templates，冻结后处理held-out；
- 629：continuity points在运行前人工裁定boundary type、chain members、完整source sentence并跨conditions复用；missing member/mapping是completeness failure；seam使用accuracy/fluency MQM固定权重、frozen prompt/model/cache、human review；
- 636：preidentified proper names/terms，source-target word alignment取每次译法；unreliable alignment单独报告，common substring不作formal LTCR proxy。

当前：

- `tools/lopo.py`明确`refit_per_fold=false`，同一hand-tuned config接触过全corpus；
- `babeldoc/magazine/metrics/ltcr.py`明确无word alignment，以paragraph shared substring分组；
- `tools/splice_judge.py`有frozen model/prompt/cache，现有14/14 manual review已完成；主要formal缺口是endpoint未映射到pre-adjudicated members、5点中2点窗口错误并事后标invalid、arms/point mappings不完整，以及taxonomy/weights不是TeX规定的MQM contract。

上次失败原因：计划只检查“有脚本/数字/说明”，没有用readiness certificate控制formal metric ID；脚本注释承认deviation，上层报告仍可能沿用LOPO/LTCR/MQM标签；缺证据没有阻止formal numeric output。

## 2. 启动与冻结保护

```bash
git status --short --branch
git rev-parse HEAD
mkdir -p .tmp/c21
export UV_CACHE_DIR="$PWD/.tmp/c21-uv-cache"
```

先列出所有tracked frozen bytes：

```bash
git ls-files -z docs/eval/results_e1 docs/eval/results_e2 > .tmp/c21/tracked-results.paths0
```

新增/使用`tools/evaluation_readiness.py snapshot`生成NUL-safe manifest，覆盖上述列表中的JSON、MD、README及其他tracked文件：

```bash
uv run python tools/evaluation_readiness.py snapshot \
  --paths-from0 .tmp/c21/tracked-results.paths0 \
  --output .tmp/c21/frozen-results.before.json
```

在工具尚未实现前，可用只读`git hash-object --stdin-paths -z`等价诊断；最终必须由测试验证所有tracked bytes前后一致。发现用户已修改冻结目录时停止，不覆盖。

## 3. 无歧义 readiness 状态机

新增`babeldoc/magazine/metrics/readiness.py`和`tools/evaluation_readiness.py`。schema拆分两个状态：

```text
schema_version
metric_id
metric_class = formal | descriptive | proxy | exploratory
readiness_status = ready | not_ready
computation_status = computed | not_computed
compatibility = current | legacy_noncomparable
evidence_manifest_sha256
required_evidence[]
present_evidence[]
missing_reason_codes[]
data_provenance[]
value = number/object | null
coverage{}
```

合法状态：

- formal + ready可computed；
- formal + not_ready只能not_computed/value null；
- descriptive/proxy/exploratory可computed，但不能带formal alias/certificate；
- legacy兼容性是独立字段，不塞进`metric_class`；
- not_computed不能用0/NaN/空object代替；
- 未知schema/evidence/reason/status组合fail closed。

Formal CLI固定退出：

```text
0 = formal computed successfully
3 = methodology not ready，已写合法not_computed report
1 = implementation/input/schema error
2 = CLI usage error
124 = external timeout（永不当作not_ready成功）
```

Tests必须同时断言exit=3、JSON状态/value/reasons，不能用“任意非零都通过”。

## 4. Formal LOPO readiness

当前输出改名：

```text
metric_id = descriptive_publication_matrix
metric_class = descriptive
generalisation_claim = false
```

`tools/lopo.py`可保留兼容入口，但help/default/report使用新名；旧`lopo_v2`只发deprecation并标legacy，不进入formal汇总。

每fold formal evidence：

```text
held_out_publication
training_publications
tuning_publications
training/tuning row manifests + hashes
fitting/selection code hash
frozen search space/selection trace
fold-specific policy/threshold/prompt artifact hash
isolated cache namespace + accessed key manifest
heldout input/prediction hash
```

不强制“trained model artifact”；规则系统的fold-specific frozen policy/threshold/prompt artifact有效。Validator从manifests重算：heldout与training/tuning sets不相交；cache accesses不含heldout；所有publications恰好各held out一次；config artifact由该fold训练/选择trace产生。不能接受`proof: true`或自由文本声明。

当前formal预期：

```text
readiness_status=not_ready
computation_status=not_computed
value=null
reasons include LOPO_NO_FOLD_REFIT, LOPO_HELDOUT_TUNING_CONTACT
```

## 5. Formal LTCR readiness与unaligned语义

当前输出改名：

```text
metric_id = substring_consistency_proxy
metric_class = proxy
formal_ltcr_claim = false
```

禁止公开key/registry/报告把其映射为`LTCR`。Pairwise grouping算法仍可保留其proxy价值。

Formal source term manifest必须在读取system output前冻结：

```text
term_id
normalized preidentified proper name/term
document/article scope
expected source occurrence refs/spans
adjudication provenance
manifest hash
```

Alignment artifact为每个expected occurrence给：

```text
source occurrence ref/span
target segment ref/span
aligned rendering or null
alignment method/model/config/version
confidence
status = aligned | ambiguous | unaligned
artifact hash
```

Formal计算规则写死：

- 只有`aligned` occurrences进入该term的pairwise numerator/denominator；
- 一个term少于2个reliably aligned occurrences时该term为not-computable，不给0；
- ambiguous/unaligned occurrences始终单独报告数量、refs和coverage，不从报告消失；
- corpus值汇总所有可计算term的numerators/denominators，同时报告expected/aligned/ambiguous/unaligned counts和uncomputable terms；
- TeX未规定最低coverage，代码不能擅自用任意阈值否决全部formal结果；readiness要求每个expected occurrence都有alignment status/provenance，但允许status为unaligned；
- 当前仓库连这种alignment status artifact也不存在，因此formal整体not_computed，reason `LTCR_WORD_ALIGNMENT_MISSING`；
- glossary或common substring不构成alignment。

## 6. Formal seam MQM readiness

当前输出改名：

```text
metric_id = exploratory_endpoint_window_annotations
metric_class = exploratory
formal_seam_mqm_claim = false
```

保留现有judge/model/prompt/cache/raw annotation和14/14 human review历史价值，不把它们聚合进formal seam score。

### 6.1 Pre-run point/arm manifest

在任何system output读取前冻结：

```text
point_id
publication/document
boundary type
physical source boundary
adjudicated ordered chain member refs
complete source sentence refs/text hash
expected arms
per-arm artifact mapping contract
adjudicator/status
manifest hash/time ordering evidence
```

每个expected point×arm必须有source→target mapping。Missing member/arm/full sentence/mapping记completeness failure并留在denominator/report，不过滤后缩小集合。

### 6.2 TeX MQM contract

Versioned contract固定：

- human/automatic categories只取`accuracy`和`fluency`分支，加`non_translation` sentinel；
- severity严格`Major | Minor | Neutral`；
- weights：non-translation 25；其余Major 5；Minor punctuation 0.1；其他Minor 1；Neutral 0；
- segment可含完整跨界句，multi-annotator取平均；
- automatic protocol为GEMBA-MQM固定three-shot prompt，绑定prompt hash、model version、parameters、cache namespace/replies；
- human review绑定article context、error category/severity、paired system comparison和completion；
- aggregation/denominator/paired comparison在看输出前冻结。

当前12-category或`critical/major/minor`配置不得synthetic-ready。Test必须专门拒绝错误taxonomy/weights、非three-shot prompt和事后invalid point。

当前formal not-ready reasons至少反映真实缺口：

```text
SEAM_POINTS_NOT_BOUND_TO_ADJUDICATED_MEMBERS
SEAM_INVALID_POSTHOC_WINDOWS
SEAM_ARM_MAPPING_INCOMPLETE（若manifest复核确认）
MQM_TAXONOMY_OR_WEIGHTS_MISMATCH
```

不要错误写`MQM_HUMAN_REVIEW_INCOMPLETE`，除非新的检查确实发现不是14/14。

## 7. 统一reason codes

Closed enum至少：

```text
LOPO_NO_FOLD_REFIT
LOPO_HELDOUT_TUNING_CONTACT
LOPO_PROVENANCE_MISSING
LOPO_CACHE_NOT_ISOLATED
LOPO_FOLD_ARTIFACT_MISSING
LTCR_TERM_MANIFEST_NOT_FROZEN
LTCR_WORD_ALIGNMENT_MISSING
LTCR_ALIGNMENT_PROVENANCE_MISSING
SEAM_POINTS_NOT_FROZEN
SEAM_POINTS_NOT_BOUND_TO_ADJUDICATED_MEMBERS
SEAM_INVALID_POSTHOC_WINDOWS
SEAM_SOURCE_SENTENCE_INCOMPLETE
SEAM_ARM_MAPPING_INCOMPLETE
MQM_TAXONOMY_OR_WEIGHTS_MISMATCH
MQM_PROMPT_PROTOCOL_MISMATCH
MQM_HUMAN_REVIEW_INCOMPLETE
```

Report reason必须由validator证据产生，不由作者自由填。

## 8. 历史结果与文档

不编辑`docs/eval/results_e1/`、`results_e2/`已有tracked bytes。新增：

```text
docs/eval/methodology_status.v2.json
docs/eval/methodology_status.v2.md
```

逐artifact记录path/hash、旧label、准确新label、`compatibility=legacy_noncomparable`、formal status/reasons、TeX hash。Compatibility reader可读旧key，但返回formal value null；不得原地改旧文件。

同步更新：

- `docs/eval/metric_contract.md`；
- `docs/eval/gap_register.md`；
- `docs/eval/splice_protocol.md`；
- `tools/eval_report.py`和metric registry/README中的proxy→formal映射。

`not_computed`在table渲染为文字，不参与mean/ranking，不能转0。

## 9. 测试

新增两个fast gates并声明`GATE_SET="fast"`。本分支直接逐项运行并把准确文件名交给WT0；只有WT0 integration owner修改统一`run_all.py` registry/meta-test，合入后验证存在、唯一、依赖顺序正确。

### 9.1 `spec_check_evaluation_readiness.py`

- LOPO完整fold-specific rule artifacts/sets/cache disjointness synthetic-ready；
- no refit、heldout contact、shared cache、missing fold/hash分别exit3+正确reason；
- 不能用proof string蒙混；
- LTCR frozen terms + aligned/ambiguous/unaligned status artifact可ready并按aligned pairs算，unaligned单列；
- 少于2 aligned term不写0；substring proxy不可ready；
- seam预裁定members/full sentence/all arms/mapping+正确MQM contract可ready；
- wrong taxonomy/severity/weight/non-three-shot/posthoc invalid/missing arm分别失败；
- not-ready JSON value null，implementation crash退出1，timeout不被当pass。

### 9.2 `spec_check_eval_labels.py`

- 三个current public IDs只能是descriptive/proxy/exploratory新名；
- formal value必须带valid readiness certificate；
- 禁止proxy alias到formal；
- legacy reader不改原文件且compatibility字段合法；
- formal not-computed不进入aggregation；
- methodology status reason与实际current evidence一致。

## 10. 必跑命令

```bash
timeout 90s uv run python spec_checks/spec_check_evaluation_readiness.py
timeout 90s uv run python spec_checks/spec_check_eval_labels.py

# 精确exit=3与JSON内容由spec断言；手工smoke保存report
uv run python tools/evaluation_readiness.py check --metric lopo --mode formal --output .tmp/c21/lopo.json; test $? -eq 3
uv run python tools/evaluation_readiness.py check --metric ltcr --mode formal --output .tmp/c21/ltcr.json; test $? -eq 3
uv run python tools/evaluation_readiness.py check --metric seam-mqm --mode formal --output .tmp/c21/seam.json; test $? -eq 3

# 当前真实相关gate
timeout 90s uv run python spec_checks/spec_check_e1.py
timeout 90s uv run python spec_checks/spec_check_e2.py
timeout 90s uv run python spec_checks/spec_check_b7_3.py
timeout 90s uv run python spec_checks/spec_check_b9_2r.py
timeout 90s uv run python spec_checks/spec_check_gate_registration.py

# frozen bytes after-check
uv run python tools/evaluation_readiness.py snapshot \
  --paths-from0 .tmp/c21/tracked-results.paths0 \
  --output .tmp/c21/frozen-results.after.json
uv run python tools/evaluation_readiness.py compare-snapshots \
  .tmp/c21/frozen-results.before.json .tmp/c21/frozen-results.after.json
```

注意三条formal手工smoke在`set -e` shell中需显式捕获exit再断言；CI以Python gate为准，不能让timeout/import/usage error被`test nonzero`误收。

## 11. 提交与交接

精确stage本批metrics/tools/docs/spec files，不用`git add -A`：

```bash
git status --short
git diff --check
git add -- <逐项审阅的readiness/metric/tool/docs/spec pathspec>
git diff --cached --check
git diff --cached --stat
git commit -m "fix(eval): fail closed on non-methodology proxies"
```

交接：commit、三个old→new映射、state schema/exit codes/reasons、LOPO set-disjoint evidence逻辑、LTCR unaligned规则、exact MQM contract、测试退出码、frozen before/after一致性。不得把formal结果写成已完成。

## 12. 完成与停止条件

完成：

- publication matrix明确descriptive，无held-out claim；
- substring metric明确proxy，无formal LTCR key；
- endpoint annotations明确exploratory，无formal MQM score；
- formal当前均not_ready/not_computed/value null/精确reasons/exit3；
- readiness synthetic正例可达，不是永远失败；
- LOPO validator重算train/tune/cache disjoint，不信proof字符串；
- LTCR aligned pairs与unaligned单独报告符合TeX；
- MQM categories/severity/weights/three-shot contract精确；
- 历史tracked bytes全部不变；
- 新gates及现有E1/E2/B7.3/B9.2R通过；
- 无网络、无runtime翻译改动。

停止：冻结目录已有用户改动、TeX metric定义需作者新判断、旧artifact无法确认语义、任何工具试图联网/重翻、formal value仍可绕过certificate，或5小时到达仍有proxy→formal映射。时间盒到达优先提交fail-closed registry/readiness和erratum，不制造formal数字。
