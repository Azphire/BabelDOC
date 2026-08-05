# PLAN B1 — 分页分段 IR:IL schema 扩展(1–2 会话)

前置:B0 全绿。本批次只扩展数据模型,**不引入任何设置这些字段的逻辑**;所有新属性在本批次结束时于真实流水线中恒为 None/未出现。

## 目标

1. `il_version_1` schema(`.rnc/.rng/.xsd` 三份同步)新增页面级与段落级可选属性。
2. 重生成(或按豁免流程手工同步)`il_version_1.py`。
3. 序列化往返、后向兼容、零行为变化三类门禁全绿。

## 需复核的代码事实

- `il_version_1.py` 为 xsdata 生成的 `@dataclass(slots=True)` 模块;属性经 `field(metadata={"name": ..., "type": "Attribute"})` 映射 XML camelCase 属性名到 Python snake_case 字段。
- `.rnc` 中 `PdfParagraph` 已有可选属性先例(如 `attribute layout_label { xsd:string }?`),`Page` 属性为 `pageNumber`、`Unit`。命名风格混杂(camelCase 与 snake_case 并存),新增属性统一用 camelCase(与 `pageNumber` 一致),Python 侧由 metadata 映射为 snake_case。
- `XMLConverter.read_xml/from_xml` 基于 xsdata parser,未知属性会报错还是忽略——**现场验证**并把结论写进交付报告(影响断言 B1-G6 的写法)。
- 仓库内可能没有 xsdata 生成命令的记录:先搜索(Makefile、docs、pyproject scripts、git log);找不到则按 CLAUDE.md §4.6 走手工同步 + WAIVERS 登记。

## Schema 增量(三份 schema 文件等价表达)

Page 新增(全部 optional attribute):

| XML 属性 | 类型 | 语义 |
|---|---|---|
| `pageKind` | string | 页面类型名,取值域由 configs/page_types.json 定义,schema 不枚举 |
| `pageKindConf` | float | 分类置信度 [0,1] |
| `pageKindSource` | string | `deterministic` \| `vlm` \| `human`(schema 不枚举,文档化约定) |

PdfParagraph 新增(全部 optional attribute):

| XML 属性 | 类型 | 语义 |
|---|---|---|
| `chainId` | string | 文章链 ID(base58,与 debug_id 生成方式同族) |
| `chainIndex` | int | 段落在链内序号,0 起 |
| `dropCapCandidate` | boolean | 机器标记的下沉字候选 |
| `dropCapDecision` | string | `keep` \| `flatten` \| 空(未裁决) |
| `segmentSentenceStart` | int | 回填译文来自链级译文的句区间起(含),0 起 |
| `segmentSentenceEnd` | int | 句区间止(不含) |

RNC 示例(XSD/RNG 同步等价改写):

```
PDFParagraph =
  element pdfParagraph {
    ...existing...,
    attribute chainId { xsd:string }?,
    attribute chainIndex { xsd:int }?,
    attribute dropCapCandidate { xsd:boolean }?,
    attribute dropCapDecision { xsd:string }?,
    attribute segmentSentenceStart { xsd:int }?,
    attribute segmentSentenceEnd { xsd:int }?
  }
```

## 任务

### T1.1 三份 schema 同步修改

按上表修改 `.rnc`、`.rng`、`.xsd`。若发现三份文件在改动前已互不一致,停止并报告(这是 PLAN 前提破坏)。

### T1.2 重生成 il_version_1.py

优先路径:找到/复原 xsdata 生成命令,重生成后 diff 检查——**除新增字段外不得有任何其他差异**(格式化噪声也算差异,出现则改走手工路径)。手工路径:按既有字段的 field/metadata 风格逐一添加,WAIVERS.md 登记"手工同步生成物"及解除条件(找到可复现的生成配置后重生成验证)。

### T1.3 往返与兼容验证工具

`babeldoc/magazine/ir_compat.py`:

- `roundtrip_equal(docs) -> bool`:to_xml → from_xml → 再 to_xml,两次 XML 字符串相等。
- `assert_new_fields_roundtrip()`:构造最小 Document(1 页 1 段),把六个新字段全部置非默认值,roundtrip 后逐字段相等。
- `assert_backward_compat(old_xml_path)`:读入 B0 基线 checkpoint(位于 `examples/output/baseline/<name>.checkpoints/`,不含新属性),解析成功且所有新字段为 None。

## 门禁 `spec_checks/spec_check_b1.py`

正向断言:

1. 三份 schema 文件都包含全部 9 个新属性名;`.rnc` 与 `.xsd` 中新属性均为 optional。
2. `il_version_1.Page` 与 `PdfParagraph` dataclass 含对应 snake_case 字段,默认值 None,metadata name 为 camelCase 原名。
3. `assert_new_fields_roundtrip()` 通过(XML 路径)。
4. 新字段置值后 `to_json` 输出包含对应键;未置值时(见负向 7)不影响既有键集合。
5. `assert_backward_compat` 对 B0 基线的每一个 checkpoint XML 通过。

负向断言:

6. 全库 grep:除 `il_version_1.py`、schema 三件套、`ir_compat.py`、spec_check 外,**没有任何代码引用新字段名**(本批次禁止出现消费方)。
7. 对 `corpus/manifest.json` 登记的全量样张(`examples/input/`)重跑 B0 干跑流程,产物写 `examples/output/b1/`:所有 checkpoint 中新属性均不出现(XML 中 grep 属性名零命中)——证明现有 stage 不会意外置值。
8. 干跑产出 PDF 与 B0 基线 `render_diff` 退出码 0(schema 扩展零行为变化)。
9. `git diff` 上游改动集合 ⊆ {schema 三件套, `il_version_1.py`},已登记 UPSTREAM_DIFF.md;注释无中文。

## 明确不做

- 不实现 PageClassifier、链检测、HITL 写回(分别属 B2/B9/B5)。
- 不给 XMLConverter 加 `read_json`;若 T1.3 过程中发现 XML 路径不足以支撑往返验证,停止并报告,不自行加 JSON 读取。
- schema 不做枚举约束(取值域由 configs 与文档约定管理,保持词表可扩展)。
