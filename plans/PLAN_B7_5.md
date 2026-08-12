# PLAN B7.5 — 语料刷新:v2 换血、Courier-zh 入列、真值迁移与刊名裁决闭环(2 会话)

前置:batch-b7.3;用户已定稿三份真值文件(registry 退役 2 增 3、page_labels 迁移、chain_labels 迁移),已将 AramcoWorld-en-v2.pdf / FD-en-v2.pdf / Courier-zh.pdf 置入 examples/input/ 并移除两份退役 PDF。链正样本账面 2→5(en 正文 2、zh 词中 1、标题 2)。

## 原则

1. **角色驱动约束域**:约束性一致率断言(页型 06c、边界 boundary_agreement)只对 `corpus_role` 含 `layout_generalization` 的样张生效;Courier-zh(仅 translation_eval)的两项一致率单独测量、入报告不入约束——中文分布未经调参,其数字是未来 zh 校准的基线而非当前门禁。
2. **换血重调参协议**:v2 页数变化移动 page_relative_position 与 pctl 分布,门禁失守时批次内授权一轮 configs-only 重调参(LOPO 纪律、逐轮日志),硬守卫:原英文样张上先前正确的判定零回归;仍不达标则停止报告,不弱化阈值。

## 任务

### T7.5.1(会话一):注册与重建

- 一致性校验:registry ↔ examples/input 双向覆盖(退役文件不在、新文件已登记);三份真值文件通过各自校验器(page_labels 页号落新页数域、chain_labels 页对相邻性、含 `_semantics` 键)。
- manifest 重建:退役条目移除,新条目语义字段逐字复制、机械字段现场计算。
- 基线:三份新样张 build_baseline(<name>.b7_5 命名);退役样张基线目录删除;既有三样张基线不动。
- corpus_check 升级:角色约束域的声明落进检查器(报告分组按 role)。
- 历史门禁语料适配:遍历 manifest 的门禁自然吸收新语料;凡硬编码退役文件名处改为 manifest 驱动(现场盘点,预计极少)。全量 run_all:约束域内断言全绿;Courier-zh 的页型/边界一致率首测数字入交付报告(仅观察)。
- 若约束域内 06c 或 boundary_agreement 失守 → 转入换血重调参协议(会话一内完成或明确移交会话二)。

### T7.5.2(会话二):迁移验证与刊名裁决闭环

- 迁移守恒抽验:v2 文件与 v1 共有页(AW 1–6、FD 1–6)的判定对照表——因 page_relative_position/pctl 移动而漂移的页逐页列出并归因;新增页(AW p7、FD p7)与 Courier-zh 全页的判定、链边界判定对照真值逐条呈报。
- 链检测复验:6 个正样本的判定表(重点:AW 6→7 新正样本、Courier-zh 7→8 词中正样本、7→8/5→6 新陷阱);零假阳性硬线维持。
- **刊名裁决闭环(用户参与)**:用户在 reviews/Courier-en.decisions.json 增补刊名词条(建议跟官方:The UNESCO Courier → 联合国教科文组织《信使》,以用户定稿为准);hitl 两遍重跑(缓存冻结):5/6 可达刊名位点统一的证据、第 6 处 fallback_line 不可达如实记录(B8 需求清单首条的活证据);b6.2 缺口闭合正式入账。
- 报告:examples/output/b7_5/refresh.report.md——语料账面(角色 × 正负样本 × 页型覆盖)、Courier-zh 基线数字、迁移漂移表、刊名闭环证据。

## 门禁要点(spec_check_b7_5)

正向:registry/manifest/真值三方一致;基线齐备且退役目录不存在;约束域内 06c ≥ 0.7、boundary_agreement ≥ 0.8、链负样本零误连;Courier-zh 两项一致率已测量并落报告(数值不约束);两遍恒等在新语料复跑;run_all 全绿。
负向:真值文件机器零改动(用户定稿后哈希锁定,会话开始记录、结束比对);重调参若发生,diff 仅限两个 configs JSON 且逐轮日志齐全、英文样张零回归断言通过;退役文件名在代码/配置零残留(grep);上游零改动;注释无中文。

## 明确不做

zh 方向的分类/链调参(仅测量基线);FD-zh(搁置,registry 不留占位);拼版切分;B8 内容。
