# PLAN B2.1 — 特征机制修复 + 评分判别力(1 会话)

前置:B2 全绿。本批次修复 B2 交付报告 d 项揭示的三个特征定义缺陷,并给评分机制加负权惩罚;不动流水线挂接,不调 JSON 阈值(惩罚规则的初始条目除外,见 T2.1d)。

## 需复核的代码事实

- IL `PDFXobject` 含 `Box`(schema 已确认);B2 报告实测 basic-en 的图以 `page.pdf_xobject` 进入(计数 2),`page.pdf_figure` 为空。
- `Page.page_number` 为 0-based(B2 报告实测:6 页文档末页 `page_relative_position = 0.833`)。现场复核 `il_creater` 写入逻辑确认。
- `taxonomy.py` 当前校验 `weight <= 0` 报错;评分 = 满足谓词 weight 和 / 全部 weight 和。

## 任务

### T2.1a `image_area_ratio` 修复

占用目标改为 `pdf_figure ∪ pdf_xobject` 的 box。排除退化 box(宽或高 < cropbox 对应边 × `min_image_side_ratio`,新参数默认 0.02,带 allowed_range)以滤掉装饰性小 XObject。`configs/page_features.json` 同步。

### T2.1b `column_count_estimate` 修复

参与聚类的段落改为:`layout_label` 属于 `configs/page_features.json` 新增的 `column_estimate_labels`(默认 `["text", "plain text", "paragraph_hybrid"]`)**且** box 宽 ≥ cropbox 宽 × `column_min_width_ratio`(默认 0.12,带 allowed_range)。无合格段落时记 0。

### T2.1c `page_relative_position` 修复

公式改为 `(page_number + 1) / total_pages`(若复核确认 0-based),末页恒为 1.0。

### T2.1d 评分负权惩罚

`taxonomy.py`:允许 `weight < 0`(禁止 0)。得分 = max(0, 满足谓词的 weight 代数和) / 正权重之和;上限截 1。校验器同步(每型正权重之和必须 > 0)。`page_types.json` 中为 B2 报告点名的并列冲突加最小惩罚条目(仅结构示范,例如 `interview` 对低 `title_label_ratio` 的惩罚、`sidebar_heavy` 对高 `mean_paragraph_chars` 的惩罚,各型至多 2 条),其余阈值一律不动。

### T2.1e 历史门禁修订(授权)

`spec_check_b1.py` 断言 06:`page_classifier.py`、`spec_check_b2.py` 加入 allowlist,注明语义为 "consumers must stay within the authorized writer list"。

### T2.1f 重出报告

全量样张重跑 `tools/page_classify_report.py` 至 `examples/output/b2_1/`;交付报告附修复前后逐页判定对比表(basic-en 6 页)。

## 门禁 `spec_checks/spec_check_b2_1.py`

正向:1) manifest 中 notes 含 magazine 的样张,存在至少一页 `image_area_ratio > 0`;2) `column_count_estimate` 在全量样张上不再恒为上限(存在取值 < 4 的正文页);3) 末页 `page_relative_position == 1.0`;4) 负权重词表通过校验且评分 ∈ [0,1];特征纯函数断言(B2 门禁 2)在新定义下复跑通过;5) `spec_check_b0/b1/b2` 全部复跑全绿(b1 为修订后)。

负向:6) 开关默认 False 下产物与基线 `render_diff` 退出 0;7) 本批次改动 ⊆ {`page_features.py`, `taxonomy.py`, 两个 configs, `page_types.json`, `spec_check_b1.py`, 报告产物},上游零改动;8) 词表页型名代码零命中(B2 门禁 8 复跑);注释无中文。

## 明确不做

- 不调既有阈值数值(T2.1d 的新增惩罚条目除外);不改 12 特征之外的任何机制;不动流水线挂接与 IL;不填 `page_labels.json`(人工职责)。
