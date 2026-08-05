# PLAN B2 — 页面特征提取 + 声明式页型词表 + 确定性 PageClassifier(2 会话)

前置:B0、B1 全绿。本批次是 B1 新增 IL 字段的**第一个写入方**(且只写 `pageKind/pageKindConf/pageKindSource` 三个页面级字段;段落级字段仍无人触碰)。不引入任何 LLM/VLM 调用(VLM 兜底属 B3)。

## 目标

1. `babeldoc/magazine/page_features.py`:从 IL 逐页计算确定性特征向量。
2. `configs/page_types.json`:杂志页型词表 + 有界谓词评分规则 + policy 标志,分类逻辑零代码化。
3. `babeldoc/magazine/page_classifier.py`:PageClassifier stage,写入三个页面级 IL 字段;默认关闭,零行为变化。
4. `tools/page_classify_report.py`:人工审阅报告(特征 + 得分 + 判定),支撑词表阈值的离线调参。
5. 门禁 `spec_checks/spec_check_b2.py` 全绿。

## 需复核的代码事实

- B1 已使 `il_version_1.Page` 含 `page_kind / page_kind_conf / page_kind_source`(metadata 名 `pageKind/pageKindConf/pageKindSource`),默认 None。
- `_do_translate_single` 中 `StylesAndFormulas(...).process(docs)` 之后、`AutomaticTermExtractor` 之前存在插入点;`magazine_checkpoint` 开关与 `dump_checkpoint` 可用,现有序号占用为 [1,2,3,5,6,7,9](现场复核 `configs/checkpoint_stages.json`)。
- `PdfParagraph` 可用信号:`unicode`、`layout_label`、`box`、`pdf_style.font_size`、`pdf_paragraph_composition`(内含 `pdf_line`);`Page` 有 `cropbox`、`pdf_figure`、`page_number`;`Document` 有 `total_pages`。
- `skip_translation=True` 全 stage 干跑可无 API key 走到 Typesetting(B0 门禁已用)。

## 特征定义(全部确定性,逐条实现;名称即 JSON 中引用名)

栅格占用类(64×64 网格覆盖 cropbox,格与任一目标 box 相交即占用):

1. `text_coverage_ratio` — pdf_paragraph 占用格比例
2. `image_area_ratio` — pdf_figure 占用格比例

计数统计类:

3. `paragraph_count` — 段落数
4. `mean_paragraph_chars` — 段均 unicode 长度
5. `short_paragraph_ratio` — unicode 长度 ≤ `short_char_limit` 的段落占比
6. `numeric_token_density` — 全页段落文本中数字字符 / 非空白字符
7. `leader_dot_line_ratio` — 含 ≥ `leader_dot_min_run` 个连续 `.` 或 `…` 的段落占比
8. `title_label_ratio` — `layout_label` 含子串 `title` 的段落占比
9. `distinct_font_size_count` — 段落字号按 0.5 取整后的去重数
10. `max_font_size_ratio` — 最大段落字号 / 中位段落字号
11. `column_count_estimate` — 段落 box 横向中心一维聚类数(相邻间隙 ≥ cropbox 宽度 × `column_gap_ratio` 即分簇),上限 4
12. `page_relative_position` — page_number / total_pages,取 [0,1]

辅助参数 `short_char_limit`(默认 80)、`leader_dot_min_run`(默认 4)、`column_gap_ratio`(默认 0.05)与栅格分辨率一并放入 `configs/page_features.json`,各带 `_allowed_range`。空页(零段落)所有比率型特征记 0,`distinct_font_size_count`/`column_count_estimate` 记 0。

`extract_page_features(page, document) -> dict[str, float]` 必须纯函数、无副作用;同一 IL 输入两次调用结果逐位相等(门禁断言)。

## `configs/page_types.json` 结构

```json
{
  "taxonomy_version": "1.0",
  "ambiguity_margin": 0.15,
  "default_type": "article_body",
  "page_types": [
    {
      "name": "toc",
      "description": "Table of contents: entry titles with page numbers, often leader dots.",
      "rules": [
        {"feature": "numeric_token_density", "op": "ge", "threshold": 0.06, "weight": 2.0},
        {"feature": "short_paragraph_ratio", "op": "ge", "threshold": 0.55, "weight": 1.5},
        {"feature": "leader_dot_line_ratio", "op": "ge", "threshold": 0.08, "weight": 3.0},
        {"feature": "page_relative_position", "op": "le", "threshold": 0.15, "weight": 1.0}
      ],
      "policy": {"chain_eligible": false, "translate": true, "repair_profile": "grid"}
    }
  ]
}
```

- `op` ∈ {`ge`,`le`,`gt`,`lt`};type 得分 = 满足谓词的 weight 和 / 该 type 全部 weight 和 ∈ [0,1]。
- 判定:取最高分 type;top1 − top2 < `ambiguity_margin` 时仍取 top1,但该页记为 ambiguous(见写回规则)。零规则命中所有 type 得 0 时取 `default_type`。
- `description` 字段本批次不消费,为 B3 的 VLM prompt 注入预留。
- **种子词表**至少含:`cover`、`back_cover`、`toc`、`masthead`(刊头/版权)、`editorial`(卷首语)、`article_opener`(大标题+主图)、`article_body`、`photo_spread`(整版图版)、`infographic`、`interview`(Q&A)、`sidebar_heavy`、`contributors`、`letters`、`advertisement`、`section_divider`。每型给出基于上述 12 特征的合理初始规则(阈值是待调参数,合理即可,后续凭报告工具人工调 JSON)。
- 每型 `policy` 三键必填。`chain_eligible` 初值:仅 `article_body`、`interview`、`editorial` 为 true。

加载器 `babeldoc/magazine/taxonomy.py`:JSON schema 校验(未知 feature 名、非法 op、weight ≤ 0、policy 缺键、type 名重复均报错),加载时把文件 SHA-256 记入 working_dir 运行清单(与 CLAUDE.md §4.3 同一机制,可先以最小实现落地,B3 统一)。

## 任务

### T2.1 特征提取器 + `configs/page_features.json`
### T2.2 词表 + 加载校验器(taxonomy.py + page_types.json 种子词表)
### T2.3 PageClassifier stage

`page_classifier.py`:`PageClassifier(translation_config).process(docs)`——逐页提取特征、评分、写回:`page_kind = 判定名`,`page_kind_conf = top1 得分`(ambiguous 页 conf 照实记低分,不额外标记字段),`page_kind_source = "deterministic"`。同时把逐页 `{page_number, features, scores, kind, conf, ambiguous}` 写 working_dir sidecar `page_classify.report.json`(schema 冻结令下的运行期数据出口)。

挂接 `_do_translate_single`:StylesAndFormulas 之后,新增配置开关 `magazine_page_classify: bool = False` 门控;开启且 `magazine_checkpoint` 开启时,以未占用序号(如 04)落 `checkpoint.04_page_classifier.xml` 并更新 `configs/checkpoint_stages.json`。上游改动仅 `high_level.py` + `translation_config.py`,登记 UPSTREAM_DIFF.md。

### T2.4 审阅报告工具

`tools/page_classify_report.py`:输入样张(或其 checkpoint),对每页输出特征表、各型得分排序、判定与 ambiguous 标记,渲染该页缩略图(pymupdf),合成单文件 HTML 到 `examples/output/b2/<name>.classify.html`。这是人工调参词表阈值的界面:改 `page_types.json` → 重跑报告,不改代码。

### T2.5 真值机制(可选真值,门禁按需生效)

`corpus/page_labels.json`:`{"<file>": {"<page_number>": "<expected_kind>"}}`,由用户人工填写,允许为空对象。门禁:文件非空时,对已标注页计算判定一致率,断言 ≥ `configs/page_features.json` 中 `label_agreement_min`(默认 0.7,带 allowed_range);为空时跳过并在输出中注明 SKIPPED。

## 门禁 `spec_checks/spec_check_b2.py`

正向:

1. `page_features.json`/`page_types.json` 通过 taxonomy 校验;种子词表 ≥ 15 型,policy 三键齐全。
2. 特征纯函数:对基线 checkpoint 任一页连续两次提取,结果逐位相等;全部比率型特征 ∈ [0,1]。
3. 开启 `magazine_page_classify` 对全量样张干跑:每页 `pageKind` 非空、`pageKindConf` ∈ [0,1]、`pageKindSource == "deterministic"`;`page_classify.report.json` 存在且页数一致。
4. checkpoint 序号仍严格递增且与 `checkpoint_stages.json` 一致。
5. 报告工具对至少一份杂志样张产出 HTML,页数与 PDF 一致。
6. 真值门禁(见 T2.5,可 SKIPPED)。

负向:

7. 开关默认 False 时:checkpoint 中三个新属性零命中;产物与 B1/B0 基线 `render_diff` 退出码 0。
8. **词表名不进代码**:对 `page_types.json` 中全部 type 名,grep `babeldoc/`(排除 configs、prompts、测试与 spec_checks),零命中——CLAUDE.md §4.2 的机械执行。
9. 段落级 B1 字段(`chainId` 等六个)在全部产物 checkpoint 中零命中(本批次只写页面级)。
10. `babeldoc/magazine/` 无任何网络/LLM 调用(grep `openai|requests|httpx`);全程无 API key。
11. 本批次上游增量 ⊆ {`high_level.py`, `translation_config.py`}(对 HEAD 增量判定),登记齐全;注释无中文。

## 明确不做

- 不做 VLM 兜底(B3)、不消费 policy 标志(B6/B9 消费)、不写段落级字段。
- 不为提升某具体样张的分类准确率在代码中加特判;准确率问题一律通过改 JSON 阈值解决,改不动就记录进交付报告留给 B3 的 VLM 兜底。
- 不改 IL schema(冻结令,见 CLAUDE.md)。
