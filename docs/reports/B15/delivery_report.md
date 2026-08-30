# B15 交付报告 — 样式孤岛、缩进闸门与分类审计、页脚家具治理

分支 `migration/minimal-v0.6.4`,起点 `1123888`(b14)。
执行顺序 T0 → T1 → T2 → T3 → T4,各任务独立 commit。

## T0 前提复核(逐条,不符即停并经用户重定范围)

| # | 结论 | 实测 |
|---|---|---|
| P1 | ✓ | 封面 `<style id='1'>Courier</style>` 壳内原文保留;`The UNESCO Courier` p2/p4/p6/p7 四处译出;p1 恰 1 条 residue(`照片：Fotohane DARKROOM`) |
| P2 | 现象✓,机制反转 | 实况 `<style id='1'>V </style><style id='3'>o l u m e </style>… J <style id='13'>u l y </style>`:首字母 J/A 在壳外、被译的 `uly/ugust` 在壳内,且整单元字距拉开(IL 实测:词内字母间**无**空格字符、纯几何字距,词界才有真实空格)。原 T1a 条件"后随小写字母序列无空格"在真实数据上永不命中 |
| P3 | ✓ | `Aqib Aslam→阿基布·阿斯拉姆` 已进成品;p5#34(152 字符)`echo_retry=null` 因长度上限未获资格 |
| P4 | ✗ 不符 | 页面资格闸门早已实装:[page_types.json](../../../configs/page_types.json) 仅 article_opener/article_body 声明 `indent_eligible: true`(恰为计划默认闭表);`indent_policy.py:118` `PAGE_ELIGIBILITY_POLICY_FLAG` 为活跃机制,`page_is_eligible`(:432)读 HITL 覆盖后的 `page.page_kind`。B14 全部工件中 advertisement 页 `after:True` 计 0;FD 的广告页是 canonical p4,p2 是 article_opener |
| P5 | ✓ | 分类报告每页并存确定性判定(kind/conf/scores)与 VLM 判定,`source` 如实标注 |
| P6 | ✓ | 四页报头四种译法、slug 半译交织、`CERN快报.COM` 全数在案;经内容流实查,slug 在源里画两份(一份 `1 Tr` 仅描边、一份被 `re W n` 剪裁掉),两份共用同一文本矩阵——"交织"生于重合字符按 x 排序的段落形成期,fragment_stitch 计 0 缝合,与 T3c 原表述不符 |
| P7 | ✓ 带口径注 | `examples/output/fix0829/` 曾于 50 个 commit 前(aa323f2,无 VLM)批跑全部 12 样本;"未跑"作"未经当前杂志管线"解;冷跑预估已计入旧缓存部分命中 |

P4 与 P2 的偏差经用户裁定重定范围:T1a 按实况泛化(短侧 1–2 字母、
任一朝向、几何判词界)并加首字尺寸门槛排除;T2a 改验证型 + FD p2
可见缩进溯源(不可豁免);T2b 收窄为来源开关 + 离线重放审计表。

## T1 — 样式孤岛与回显重试(commit `8138a19`,修正 `3c87bab`/`a0d890a`)

**T1a** 新 pass `babeldoc/magazine/span_merge.py`(switch
`magazine_span_merge`,config `configs/span_merge.json`):样式边界劈开
同一单词(几何判定:边界字距 ≤ 跑内最大字距 × `span_merge_gap_tolerance`,
或 ≤ `span_merge_abs_gap_em` × 字号;延续侧小写起头)且短侧 ≤
`span_merge_max_chars`(默认 2,range 1..4)时,短侧连同边界字符保序并入
长侧容器、取长侧样式。首字排除:短侧字号比 ≥ drop_cap 的
`min_first_run_size_ratio`(单源读取 `configs/drop_cap.json`,不设第二个数)
即拒绝并记 `size_ratio_gate`,首字母留给 drop-cap 机制。守恒:并入前后
可见字符序列逐字相等,违者抛错。真实样本重跑暴露两轮判定缺陷并各自修正:
①Courier p2#5 `andtheza` 误并(跑内字间空格跨词);②改纯字母跑后
CERN 颗粒又全灭——管线会为字距拉开的每个字距**物化真实空格字符**
(`V ` / `o l u m e `),纯字母规则一碰尾空格即弃。最终规则(`a0d890a`):
跑容许字间空格,同词判定以**跑内最小字母间距**为参照(字距拉开的词
均匀、最小≈边界,吞了词界的跑最小≈0、宽边界被拒),配合绝对下限;
两个反例均有回归夹具钉住。

**T1b** 词表匹配改在去占位符标记文本上进行
(`il_translator_llm_only.py`),封面 `CourierT H E UNESCO` 的既有 HITL
词条(`联合国教科文组织《信使》`)由此可命中;结构标签保留、内容可变
的行为本就存在,未改。CERN 报头字标另经 HITL 裁定为 wordmark 保留
(identity 词条 `CERNCOURIER`/`ERNCOURIER`,走 decisions 正规通道,代批)。

**T1c** `echo_retry.attempt` 增加 `line_lengths`:单元总长超限但**多行且
每行 ≤ 上限**时仍获重试资格(行长由源段落 pdf_line 组成读出);单行超限
照旧拒绝。预算、提示词、上限数值未动。

门禁:`tests/minimal/test_span_merge.py` 7 夹具全绿(V|olume 正向、
编号反向、字距拉开 J|uly、首字尺寸门槛、真实空格词界回归、行判长)。

## T2 — 缩进闸门验证与分类审计(commits `dba9f93`/`c650554`)

**T2a(验证型 + 溯源收口)**:闸门无缺陷——缺陷在其输入。FD p2
"国防支出"三段可见缩进(body_rank 1..3, after:True)成因全链:
确定性层判 `advertisement`(score 1.0,无歧义,正确)→ VLM 仲裁改判
`article_opener`(0.9)被整体采纳(`page_classifier.py::_adjudicate`)→
HITL 无覆盖(`hitl.py:658`)→ `indent_policy.py:432` 依 article_opener
合法放行 → `:518 decide` 记 after:True ×3。修正走正规 HITL 通道:
`reviews/FD-en-v2.decisions.json` `page_kinds: {"2": "advertisement"}`。
重跑实证:p2 九段全部 `after:False`(`page_ineligible`),源页(WEO 出版物
广告页,章节导语齐头无缩进)与渲染一致。夹具
`tests/minimal/test_indent_gate.py` 钉住闭表(恰 article_opener/article_body)、
未声明类型不合格、广告页先于一切窄条件被清。

**T2b(来源开关 + 离线审计)**:`configs/vlm.json` 新键
`page_classify_source ∈ {vlm, local}`(代码内闭表校验,同 token_parameter
惯例);`local` 下确定性判定即终局,零渲染零凭据零调用。离线重放纯靠
既有报告(两层判定并存),覆盖全部 5 份带 VLM 判定的文档共 36 页,
分歧 17 页逐页代批裁定:**VLM 对 12、确定性对 3、双错 2**。默认值据此
定为 `vlm`,理由与逐页表见
[page_classify_audit.md](page_classify_audit.md)。确定性层错误多为高置信
错判(1.00 共 9 例),置信度门槛救不了。夹具
`tests/minimal/test_page_classify_source.py` 钉开关机制。

## T3 — 页脚家具治理(commit `9b1d7fc`,修正 `3c87bab`/`a0d890a`)

新 pass `babeldoc/magazine/furniture.py`(switch `magazine_furniture`,
config `configs/furniture.json`),结构期(fragment_stitch 之前)定计划、
译期跳过、译后统一:

- **T3a 重复家具单译复用**:归一化同串在 ≥`furniture_repeat_min_pages`
  (2,range 2..8)个物理页出现、每次均距页缘 ≤`furniture_edge_band_pt`
  时判为运行家具;文档序首例为 leader 正常翻译,余例跳过翻译、译后取
  leader 译文按各自段落主导样式排版。**偏差登记**:band 默认取 120
  (计划建议 60;range 20..150 未动)——实证依据是手头最深的重复家具
  CERN folio 行距页缘 108pt,60 收不进;重复+同串双条件挡住正文误伤。
- **T3b 生产标记直通**:计划的 TrimBox 判据经实查不可用(CERN 四箱同
  尺寸、无独立 TrimBox;slug 藏于剪裁与描边而非出血区,且 render mode
  不进 IL)。实装为三条几何判据(均无内容特判):①段内字符
  ≥`production_dupe_min_fraction` 与孪生重合(`production_dupe_tolerance_em`);
  ②同页带内两段归一化同文且箱体互叠 ≥`production_overlap_min_fraction`;
  ③已标记 seed 的簇传染(叠上即染,迭代至不动点)。命中者整段直通:
  不翻译、不缝合、不重排,字符逐字节不变(夹具断言)。
- **T3c 缝合边界**:P6 所称"缝合记录"证伪——CERN fragment_stitch 计 0,
  交织生于段落形成期。按实况改为防御性守卫:被直通的段对缝合不合格
  且仍作 barrier(`fragment_stitch.process_page` 的 `withheld` 参数),
  slug+date 形态回归夹具钉住。"仅缝同一文章成员"的正向约束不可实装
  (缝合在 ArticleBuilder 之前运行,文章成员关系尚不存在),登记为偏差。
- **T3d 报头收容**:复用文本走既有有界重排与 min_scale fail-open,无新
  机制;p3 字标重叠由 wordmark identity 裁定消解(源版式原样保留)。

门禁:`tests/minimal/test_furniture.py` 6 夹具全绿(三页同串单译复用、
带外出现取消资格、leader 保源全员保源、双份 slug 标记且逐字节不变、
孪生段+簇传染、缝合拒入)。

## T4 — 重跑与冷跑

### 受影响重跑(Courier-en / FD-en-v2 / CERNCourier-en)

工件:`examples/output/B15/T4/<stem>/`。重跑即真实对抗测试,共暴露并
修正四处实现缺陷(`3c87bab`/`a0d890a`/`f1f5de2`/`a43c3f8`),最终态:

**实样断言逐条**:

- Courier p1 residue:恰 1 条(`照片：Fotohane DARKROOM`,摄影署名,
  拉丁人名+暗房工作室名,应保留类)。全文 residue 5 条均为 ©/摄影署名,
  逐条归因见 issues.after.json。封面标题按既有 HITL 裁定译出:
  `信使` 大字 + `THE 联合国教科文组织` 小字,层级如源(词表去标签匹配
  使 `CourierT H E UNESCO` 词条命中;`T H E` 为字距拉开大写,按规则
  不并入,余于小字行,已见渲染图)。
- CERN 页脚 `J七月` 形态:**四页全零**。span_merge 共回接 16 词
  (Volume/Number/July/August ×4 页),卷期行四页统一译作
  `卷66号4 七月/八月 2026`(p1/p2/p4 经家具复用同源,p3 独立同文)。
- CERN `.indd` slug:**零翻译、零搅碎**——30 个生产标记
  (重合双份 6 + 孪生段/簇传染 24)全部直通,成品中 slug 以源字符原样
  出现(`CCJulAug26_Cover_v2.indd` 等)。已知限制:源中 slug 经描边/
  剪裁不可见,IL 不保留该状态,直通后以细小灰字可见——相比 B14 的
  半译交织是净改善,登记不追。
- CERN 四页页脚报头:folio 行 `CERN快报2026年7月/8月` p2/p3/p4 全同
  (家具复用,leader p2#29);域名 `CERNCOURIER.COM` 四处保留原文全同
  (leader 保源,全员保源);卷期行四页同文;巨型字标按 HITL 裁定为
  wordmark(identity 词条),p3/p4 全同。残余:模型在 wordmark 前加注
  译名(`欧洲核子研究组织CERNCOURIER` / `C欧洲核子研究组织快报`),
  组内一致、组间因源串不同(CERNCOURIER vs C+ERNCOURIER)而异,列为
  余项 R1。
- CERN p3 报头重叠:**视觉消除**(B14 巨字与卷期行墨迹互叠 vs B15
  分行清晰,渲染对照图 `cern-p3-footer-{src,b14,b15}.png`)。bbox 相交
  法在源版式即有设计性箱体重叠(字标框与卷期行框在源 PDF 中本就相交
  744.7>736.8),故以渲染对照为准并记此口径。
- FD p2:九段全部 `after:False`(`page_ineligible`),渲染无首行缩进
  (T2a 收口达成)。
- FD p5 顾问右栏:echo_retry 按行判长触发(`accepted`),全员音译进
  成品(`苏比尔·拉尔 帕帕·恩迪亚耶 …`)。非拉丁化余项:**零**。FD 全文
  residue 7 条均为设计/摄影署名、URL、邮箱(应保留类),列清单归因。

**栏尾指标(沿 B14 T2a)**:Courier-en 18 边界 fill_ratio 中位 0.885 /
满行率 0.556;FD-en-v2 3 边界中位 0.963 / 满行率 1.0;CERNCourier-en
3 边界中位 0.473 / 满行率 0(链数 0,B14 N4 之延续,只记录不修)。
回路 termination 三样本均 1 轮收敛。缩进决策:Courier 7/8 页合格
42 段加缩进;FD 3/9 页合格 19 段;CERN 2/4 页合格 40 段;
带内不合格页加缩进计数三样本均为 0。

### 新冷跑(Vogue-en / ITU-zh)

选样理由:en 侧仅余 Vogue-en;zh 侧在 ABB-zh / Courier-zh / ITU-zh 中
选 **ITU-zh**——其合刊目录+版权栏复合页、旋转书脊家具、ISSN 信息栏对
已跑 zh 样本(HuaweiTech 企业横排跨页、bull-zh 公报单栏)版式对比度
最高;ABB-zh 与 HuaweiTech 同为企业刊族,Courier-zh 与已跑两轮的
Courier-en 同族,均排除。

预估(开跑前录于会话):Vogue ≈$0.04–0.08 / 3–8 分钟,ITU ≈$0.07–0.15 /
5–12 分钟,总预算上限 $0.5。实际:Vogue 58s、ITU 98s,fix0829 旧缓存
部分命中,花费低于预算(重跑三样本 5 轮合计亦在预算内)。

结果摘要:两份均 rc=0 产出成品。Vogue residue 2(FENDI 广告行应保留 +
旋转署名交织 M1);ITU residue 7(旋转书脊刊名家具 ×7,家具分组一致
保源,M2)。ITU 的 8 页 HITL page_kinds 覆盖与 9 词条、Vogue 6 词条均
自动应用;代批复核维持既有裁定,无新增。新问题 M1/M2 及次级观察只
记录不修,清单见 [_cold_run_findings.md](_cold_run_findings.md)。

### 交付面收口

- tests/minimal:390 过 / 9 败,败名与基线逐名一致
  (`minimal-suite-baseline-failures` 口径)。
- spec_check:除 `spec_check_expectations_scope.py`(基线即败 3/5)外
  全绿;`spec_check_b14_t2.py` 以 B15 三重跑工作目录复验通过。
- 运行工件:`examples/output/B15/T4/`(不入库,按仓库惯例);证据图与
  报告入 `docs/reports/B15/`。

## 红线核对

- 守恒:T1a 并入不增删可见字符(pass 内断言 + 夹具);T3b 直通段字符
  逐字节不变(夹具断言);两处均在真实样本重跑中未触发守恒报错。
- config 单源带 range:新增数值全部入 `configs/*.json` 带
  `_allowed_range`;首字尺寸阈值只读 drop_cap.json 不复制。
- 闭词表:页类型资格走 taxonomy 声明;`page_classify_source` 代码内闭表。
- 无出版物/文件名/页码字面量进决策逻辑:span_merge 全几何;furniture
  三判据全几何;`.indd` 等字符串仅出现于报告与测试断言。
- 报告只写实测:各 pass 报告含拒绝清单与 outcome 逐行。
