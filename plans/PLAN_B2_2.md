# PLAN B2.2 — 特征分位数化 + 语料角色元数据(1 会话)

前置:B2.1 全绿并已提交打标(batch-b2.1)。动机:词表阈值若绑定绝对量纲,会拟合具体刊物的设计规范;文档内分位数使规则语义变为"该页在本刊中的相对位置",跨刊可迁移。本批次只添加能力,**不迁移词表规则、不调任何阈值**(迁移属调参会话职责)。

## 需复核的代码事实

- `page_features.py` 的 `extract_page_features(page, document)` 为逐页纯函数(B2 门禁 02a 断言 128 页次逐位相等)。
- `taxonomy.py` 校验器拒绝未知 feature 名(B2 门禁 01d)。
- `PageClassifier.process(docs)` 逐页提取→评分→写回;sidecar `page_classify.report.json` 逐页含 features/scores。
- `corpus/manifest.json` 现有字段 `{file, sha256, pages, notes}`;`tools/corpus_check.py` 做存在/哈希/页数校验。

## 任务

### T2.2a 分位数特征

`page_features.py` 新增文档级入口 `extract_document_features(document) -> list[dict]`:先逐页调用既有纯函数取原始特征,再对 `configs/page_features.json` 新增的 `percentile_features` 列表(种子:`numeric_token_density`, `short_paragraph_ratio`, `mean_paragraph_chars`, `title_label_ratio`, `image_area_ratio`, `text_coverage_ratio`, `leader_dot_line_ratio`, `max_font_size_ratio`)中每个特征,计算跨页 midrank 分位数并以 `<name>_pctl` 键并入:

    pctl(v_i) = (count(v < v_i) + 0.5 * count(v == v_i)) / n

性质(即门禁断言):值域 (0,1);单页文档恒 0.5;全文档常值特征恒 0.5(自动失去判别力,行为正确);逐页原始键不变。逐页纯函数签名与行为不动,文档级函数确定性(同一 IL 两次调用逐位相等)。

### T2.2b 消费侧接线

`PageClassifier` 改用 `extract_document_features`;`taxonomy.py` 校验器接受 `<name>_pctl` 形式的 feature 引用(仅限 percentile_features 列表内的名字加 `_pctl` 后缀);sidecar 报告与 `tools/page_classify_report.py` 的 HTML 特征表同时展示 raw 与 pctl 两列。`page_types.json` 本批次不动。

### T2.2c 语料角色元数据

`corpus/manifest.json` 每条记录新增:`publication`(字符串,刊物族标识,必填)、`corpus_role`(列表,元素 ∈ {`translation_eval`, `layout_generalization`},必填)。现有两条记录现场补填(basic-en/passage-en 按实际来源)。`tools/corpus_check.py` 增加两字段的存在与取值校验,并输出按 publication 分组的样张统计(为 LOPO 调参会话提供分组视图)。

## 门禁 `spec_checks/spec_check_b2_2.py`

正向:1) 全量样张的文档级特征含全部 `_pctl` 键且值域 (0,1),midrank 三性质(单页 0.5、常值 0.5、原始键不变)以构造用例断言;2) 文档级确定性两次逐位相等;3) 校验器接受合法 `_pctl` 引用、拒绝非列表内特征的 `_pctl` 引用;4) sidecar 与 HTML 报告含双列;5) manifest 两新字段校验通过,corpus_check 输出分组统计;6) 历史门禁 b0/b1/b2/b2.1 复跑全绿。

负向:7) `page_types.json` 与全部既有阈值零改动(git diff 检查);8) 逐页纯函数 `extract_page_features` 的输出与 batch-b2.1 时逐位相同(原始特征定义未被触碰);9) 上游零改动;词表页型名代码零命中;注释无中文。

## 明确不做

- 不把任何词表规则从 raw 迁到 pctl(调参会话按 LOPO 协议做);不调阈值;不动上游;不引入 LLM。
