# PLAN B11.9 — 新增中文语料的基线与用户裁决表（无翻译跑）

前置：HEAD `3b163e9`（"pagelabel change"）。规格即当次 prompt。单臂默认适用。
**本批只做两件事**：为缺基线的样张建基线、为六份新中文样张建立用户裁决表。
不做修法、不改机制、不跑翻译、不跑 sweep。

## 零、一处结构性事实（核实在案，决定本批形状）

裁决表的 `drop_caps` 段以 **`pN#k` 段落引用**为键（`reviews/FD-en-v2.
decisions.json` 为 `{"p8#9": "keep"}`；`Courier-en` 为 `{"p4#3": "keep",
"p5#5": "keep", "p7#8": "keep"}`），而 `hitl._validate_drop_caps` 在已知文档
时**拒绝不存在的引用**（"no such paragraph in this document"）。

段落引用只在流水线跑到 `hitl.after_page_classify`（`high_level.py:1017`）之后
才存在，而 `build_baseline.py` 用的 `only_parse_generate_pdf` 在
`high_level.py:939` **提前返回**——早于分段（stage 05）、早于页分类（stage
07）、早于 `drop_cap.mark`。

**结论**：基线跑给不出 drop_cap 候选，裁决表的 `drop_caps` 段**无法凭空撰
写**。因此本批的"不实际跑"落实为**零 API**，而非零流水线：用
`skip_translation`（仅摘除 `ILTranslator` 阶段，`high_level.py:303`）跑一次
草案导出，它到达页分类与 `drop_cap.mark`、写出含候选引用的 review 草案
（`hitl.py:858-861`）。翻译零调用；术语抽取器另需按 T2 关闭以保零 API。

## 一、前提校验（任一不符即停，逐条记行号）

1. `corpus/registry.user.json` 有 12 条 entry，其中六条 zh→en 新样张：
   `HuaweiTech-zh`、`ABB-zh`、`bull-zh`、`fd-zh`、`ITU-zh`、`WIPO-zh`；文件头
   声明 `owner = "user-only; machine sessions must never edit this file"`
   ——**本批不得改动该文件**。
2. `corpus/manifest.json`：前七条含 `baseline`，后五条（ABB / bull / fd /
   ITU / WIPO）**只有 sha256、无 baseline**。
3. `corpus/page_labels.json` 已含全部十二样张；`HuaweiTech-zh.pdf` 为六页
   （GAP-52 的页码错位已由用户在 `3b163e9` 修正，CHANGELOG 末条在案）
   ——**本批不得改动真值文件**，仅在 T4 报告差异。
4. `reviews/` 现存裁决表三份（`Courier-en`、`Courier-zh`、`FD-en-v2`），六份
   新样张**均无**。
5. 裁决表 schema（以现存三份为准）：顶层为 `terms` / `page_kinds` /
   `drop_caps` 三段 + 元数据键；`terms` 是 **object（source → target）**、
   `page_kinds` 是 object（十进制页号字符串 → **单一** kind）、`drop_caps` 是
   object（`pN#k` → verdict）。keep 语义以 `target == source` 表达
   （`"F&D": "F&D"` 在案），**无独立 keep 数组**。
6. `configs/page_types.json` 的合法 kind 共 15 个：front_cover、back_cover、
   toc、masthead、editorial、article_opener、article_body、photo_spread、
   infographic、interview、sidebar_heavy、contributors、letters_page、
   advertisement、section_divider。`_validate_page_kinds` 拒绝表外值。
7. `hitl._validate_terms`：source/target 均须非空、不得有首尾空白、
   **规范化后不得碰撞**（大小写与空白不敏感），任一违规**整份拒收**。

## 二、T1 — 五份样张的基线

对 `ABB-zh`、`bull-zh`、`fd-zh`、`ITU-zh`、`WIPO-zh` 跑
`tools/build_baseline.py --sample <name>`（零 API，parse-only），产出冻结件与
checkpoint 归档，`corpus/manifest.json` 就地更新基线路径与哈希。

- suffix 用本批号（`.b11_9.pdf` 一类），与 CLI 现行 `BASELINE_SUFFIX` 惯例
  一致；实际取值由执行方按工具现状定并记入报告。
- **HuaweiTech-zh 已有基线，不重建**（manifest 在案）。
- 逐样张记录：页数、基线 sha256、耗时；`api_calls = 0` 逐条对账。
- 若某样张 parse 阶段报错（ToUnicode / CID 一类，Vogue-zh 前例），**停在该
  样张并报告**，其余继续；报错样张按 GAP-50 同款登记，不撤 registry（
  registry 归用户）。

## 三、T2 — 零 API 草案导出（六份新样张）

以 `skip_translation` + `magazine_hitl_export` 跑六份，产出
`reviews/<sample>.review.json`（与 `.review.html`）。

- **零 API 是硬约束**：自动术语抽取器会发请求，故本跑须
  `auto_extract_glossary` 关闭（`high_level.py:301-302` 据此摘除
  `AutomaticTermExtractor` 阶段）。人名收割若含批量音译请求，同样关闭或以
  离线档跑——执行方先判定该路径是否发请求并记入报告，**判定为发请求即关
  闭该路径，不得为凑草案而付费**。
- 草案的用途界定清楚：`page_kinds` 段给**机器判定 + 置信度**（供 T3 对照，
  非真值）；`drop_caps` 段给**候选引用 `pN#k` 与首字字形**（T3 唯一可用的引
  用来源）；`terms` 段在抽取器关闭下多半稀疏或为空，属预期，不视为缺陷。
- 逐样张记录 `api_calls = 0` 与草案候选计数。

## 四、T4 — 撰写六份裁决表

为六份样张各写 `reviews/<sample>.decisions.json`，三段各有其撰写来源：

**page_kinds（人工，全页覆盖）**
- 值域限前提 6 的十五名词表；**每页单值**——真值文件是多标签数组，裁决表是
  单值，多标签页须择一。择一规则（写入报告，逐页给理由）：取**决定下游策略
  的那个语义**——`indent_eligible` 只认 article_opener / article_body，
  `preserve_line_structure` 认 toc / masthead，故 `["masthead",
  "article_opener"]` 一类须判断该页正文占比后择一，不得机械取首元素。
- 与真值的每一处不一致，在报告里列为一行（页、真值多标签、裁决单值、理
  由）。真值文件本身不动。

**drop_caps（自草案候选，人工裁定）**
- 逐候选给 verdict，值域取 `configs` 现行 drop-cap verdict 词表（b11.8 后为
  `{flatten, keep}`，`keep` 已是"按目标语言重现放大"）。
- 默认档已是 keep（b11.8），因此**只对需要偏离默认的候选出裁定**；全部随默
  认时该段可为空对象，并在报告写明"候选 N 条、零偏离"——空段与漏写不同，
  须显式。
- 引用一律抄自草案，禁止手写页段号。

**terms（人工，自源文本）**
- 六份均为 zh→en，`translate` 档下纯中文人名的拼音输出即正确，**不逐条钉人
  名**；只钉三类例外：
  a. **源刊自给英文名**（刊物自己印出的英文署名，拼音化即与刊物自身冲突）；
  b. **非中文人名的中文转写**（日、法、德等名的回写，拼音化产出不存在的
     名字）；
  c. **机构 / 品牌 / 刊名的既有官方英文名**，以及需保持原样者（以
     `target == source` 表达）。
- 术语一致性条目（全刊高频行业词）按样张酌情，宁少勿滥：**词表是强执行
  面，钉错的代价高于不钉**。
- 撰写后须过 `_validate_terms` 的三条：非空、无首尾空白、规范化无碰撞。

**元数据**：`sample` 与 `format_version` 按现存三份的写法 conform。

**已有起草件的处置**：先前会话交付的 Vogue/HuaweiTech 起草稿**格式不合**
（terms 写成了 list、另立了 keep 数组）——本批以本节规则重写，起草稿仅作内
容素材，不得直接 conform 落库。

## 五、T5 — 验收（本批无新门禁，用既有装置）

1. **可加载性**：六份裁决表逐份经 `hitl.parse_decisions` 校验通过；drop_cap
   引用在对应文档中存在（以 T2 草案为参照集）。这是本批的核心验收——上一
   批"两份草稿裁决单格式不可加载"正是此项缺失所致。
2. **零 API**：T1 + T2 全部运行的 `api_calls` 合计为 0，逐样张归因行在案。
3. **manifest 完整性**：十二样张全部有 baseline（除 T1 中报错者，须列名）。
4. **不越权**：`corpus/registry.user.json` 与 `corpus/page_labels.json`
   `git diff` 为空（两份归用户所有的直接证明）。
5. `run_all --set fast` 全绿。**不跑 sweep**（W-B11-23 仍挂性能批）。

## 六、负向范围

改动 ⊆ {`reviews/<六份新样张>.decisions.json`(新)、
`reviews/<六份新样张>.review.{json,html}`(新，机器草案)、
`corpus/manifest.json`（仅 T1 的基线路径与哈希）、
`examples/output/baseline/`、`docs/reports/`、`WAIVERS.md`、
`docs/eval/gap_register.md`、本文件}。

**不得改动**：`corpus/registry.user.json`、`corpus/page_labels.json`、
`corpus/chain_labels.user.json`、`babeldoc/` 下任何文件、`configs/`、
`prompts/`、`spec_checks/`（除非 T5.1 需要新增一条可加载性断言，则限该条）。

## 七、明确不做

链真值（chain_labels）扩充；五份新样张的历史验收维度补齐（GAP-53，另开语料
验收批）；任何修法与机制变更；翻译跑；全量 sweep；性能批；b11.8 遗留的其余
缺口。

执行序：前提校验 → T1（五份基线）→ T2（六份零 API 草案）→ T4（六份裁决表撰
写，逐份即时过 parse 校验）→ T5 验收。单 commit，tag `b11.9`（裁决后打）。

交付报告须含：T1 逐样张基线表（页数、sha、耗时、报错者）、T2 逐样张草案候选
计数与零 API 归因、T4 三段的撰写来源与逐页 page_kinds 择一理由、裁决表与真值
的不一致清单、T5 五条验收证据、起草稿重写说明。
