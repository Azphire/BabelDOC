# B17 T0 前提复核记录

复核于 2026-08-31,HEAD `9d9d59e`(b16)。逐条实测,证据为 B16/T6 工件(`examples/output/B16/T6/`)、源码 file:line、运行史目录实查。

## 结论:P3 不符(T1d 在任务边界停下,改为证伪归档 + 离线重放交付);其余成立,继续执行

| # | 判定 | 实测证据 |
|---|---|---|
| P1 | ✓,机制细化 | tracking `page[6]/paragraph[9]` = `p2#15`,input 恰为 `要复兴全球生产力，就要从处理金融危机的后`(止于`的后`),output 为模型补全完整句 "To revive global productivity, we must address the aftermath of the financial crisis."。**细化:截断不在入队处**——p2#15 单元文本与其自身字符逐字节一致(box x 193.6→423.2 与 20 字吻合);上游段落切分把一条视觉行切成 p2#15 + p2#16(`遗症开始`,box x 424.5→463.2,间隙约 1.3pt),p2#16 从未入队(tracking 全文无 p2 侧 `遗症` 单元;p4#7 为 p4 上另一次完整出现)。成品 p2 span bbox [424.1, 260.0, 463.8, 269.8] 9.8pt `遗症开始`,坐标与前提逐字吻合。**T1a 计划中的"入队截断守卫"抓不住本例**(单元与字符本就一致);抓住它的是覆盖账单里 p2#16 的无主未译 |
| P2 | ✓,排除点已 pin | tracking 无 `编者的话` 任何单元(0 命中);`年`/`低`/`高` 无 exact-input 单元。排除链条:主地板 [il_translator_llm_only.py:369](../../babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py#L369)(`len < min_text_length=5`);补救通道 short_unit 的三处拒绝——`年低高`(1 字)死于 [short_unit.py:302](../../babeldoc/magazine/short_unit.py#L302) `shape_exception_floor=2` 下界;`遗症开始` 与 `编者的话` 死于 [short_unit.py:319](../../babeldoc/magazine/short_unit.py#L319) solitary 测试(前者与 p2#15 间隙 1.3pt ≤ 9.8pt reach;后者与 p3#0 `FROM THE` 间隙 4.5pt ≤ 18pt reach 且 p3#1 `EDITOR` 框与其重叠)。**新事实:p3 报头为双语设计**——源页同时印 `FROM THE EDITOR`(22pt)与 `编者的话`(18pt SimHei),译出将与既印英文语义重复,T1c 处置须考虑 |
| P3 | **不符** | issues.after.json 有 **6 条 `untranslated_residue`**(非零):`p2#16 遗症开始`、`p3#4 编者的话`、`p5#55 年`、`p5#7 The条毫无二致。`、`p6#33 低`、`p6#34 高`,全部 severity high、`min_script_chars=1`。**检测端没有 12 字地板,短带已存在且全命中**。12 字地板真身在修复准入:termination.json untranslated_residue 决策 no_op,理由 "none have at least 12 source characters with a residue ratio of at least 0.9"(`translate_orphan_text` 条件,[minimal_repair.py:787](../../babeldoc/magazine/minimal_repair.py#L787) `orphan_min_source_chars`)。T1d"检测器增加短带"无事可做——停在任务边界,改交付:证伪归档 + 全样本缓存工件离线重放确认现有短带假阳性负担 |
| P4 | 部分✓ | 输出 8:52pt @ bbox(176.5, 71.2, 202.0, 127.5),与署名行 `作者`(170.1..179.0)/`班宁·艾尔`(179.0..206.2, y 98.0..107.2)框相交 ✓。源 8:65pt @ **x0=78.0**(前提写 x=102,实测 bbox 78.0..109.9,origin x=78.0)。熔合机制确认:AW tracking p3#0 单元 = 标题+署名+导语+`<style id='5'>8</style>` 一体入队。**14/20/32 非"同构"**:三枚是独立段落(p3#1 只有标题文本),B16 输出中三枚保持源坐标源字号丝毫未动(38pt, bbox 逐点一致)——源结构不同,成品无缺陷。T2 门禁对三枚的意义是防回归,对 8 是治缺陷 |
| P5 | ✓(经验层) | fragment_stitch.report.json 与 chain_report.json/chain_translation.report.json 全文均无 p2#15/p2#16(stitch by_rule inline=0);两机制确未覆盖。**注意:stitch 真实守卫是 style/unit/geometry + `stitch_layout_labels` 闭表(configs/fragment_stitch.json),文档未见"同文章成员"条款**——计划中"B13 缝合限同文章成员"的理由描述与代码不符,T1b 溯源以实证 file:line 为准 |
| P6 | ✓ | 运行史 union(B12–B16 当前管线):Courier-en, bull-zh, FD-en-v2, CERNCourier-en, HuaweiTech-zh(B14/T4), ITU-zh, Vogue-en, AramcoWorld-en-v2, fd-zh = 9。未经当前管线恰为 **ABB-zh、Courier-zh、WIPO-zh**(仅存 b11.x 旧管线与 fix0829 旧 commit 运行,后者作翻译缓存) |

## 计划外新发现(记入 T1 处置范围)

1. **p5#7 `条毫无二致。` 第五处漏译,且形态独特**:它*入队了*(tracking `page[9]/paragraph[4]`,input=`条毫无二致。`),模型输出 `The条毫无二致。`——echo 前缀加了 "The",而 echo-retry 是精确匹配,被这个前缀击穿(echo_retry=None,未触发)。同为切分尾段,但走到了另一条失败路径:入队 → 模型拒译回显 → 回显检测漏判。成品 p5 (311.4, 288.5) 6.4pt 残留。T1b 若把尾段并入主链则此单元不再单独入队,此路径自然消失;否则 echo-retry 需要前缀鲁棒化(T1c 范围内定夺)。
2. **覆盖账单骨架已存在**:`demo_coverage.py` 已产 `demo_coverage.report.json`(fd-zh: 232 sources,per-paragraph final_status/owner,状态 complete)。T1a 是在其上补"未译原因闭表"与三不管清单,不是新建(红线"复用,不建第三机制"适用)。fd-zh 现状:52 条 untranslated+owner=none,其中良性(纯数字/拉丁 fallback_line)与缺陷(上述五处)不可区分——这正是 T1a 要补的分类。

## 对任务设计的影响

1. **T1d 停在任务边界**:检测短带已存在(min_script_chars=1)且在 fd-zh 上 6/6 全命中零漏报。替代交付:对全部已跑样本的 issues 工件离线重放,量化现有短带的假阳性负担(先测量,不动闭表、不加检测器)。
2. **T1a 截断守卫照加但归因诚实**:守卫防的是"单元文本 ≠ 其源字符集"类,P1 本例它抓不住;P1 类由覆盖账单的无主未译暴露。两者都写,报告分开归因。
3. **T1b 的机制选择**待溯源:solitary 拒绝是 short_unit 的设计意图(贴邻=断词候选归缝合管),暗示正解是让 stitch 的 inline 规则接住 p2#15+p2#16——为何现在没接住(候选都没进)是 T1b 第一问。
4. **T1c 对 `编者的话` 须处理双语报头重复**:译出 "From the Editor" 会与既印 "FROM THE EDITOR" 语义重复(18pt 叠 22pt 邻位)。归因出口("显式跳过:双语既印")比硬译可能更诚实,T1c 实现时定夺并写报告。
5. **T2 门禁坐标修正**:源 8 用 x0=78.0(非 102);14/20/32 断言为防回归断言(B16 已在位)。
