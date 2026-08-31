# B17 交付报告:翻译覆盖守恒、短标签漏译、展示字形锚定,语料十二份全覆盖

分支 `migration/minimal-v0.6.4`,起点 `9d9d59e`(b16)。T0 复核见 [_t0_premise_findings.md](_t0_premise_findings.md)(P3 不符:检测地板分方向;T1d 转为测量交付)。T1d 测量见 [t1d_short_band_replay.md](t1d_short_band_replay.md)。运行预估见 [t3_run_estimates.md](t3_run_estimates.md)。

## T1 翻译覆盖守恒 + 漏译治因(fd 组)

### T1a 覆盖守恒不变量(`8430e37`)

在既有 `demo_coverage`(B14 起的段落级账单)上补齐守恒:每个冻结源恰入四类之一——已入队(owner ordinary/joint)/ 保护直通(preserve)/ 显式跳过(闭表 `SKIP_REASONS`:furniture_withheld、vertical、cid_encoding、placeholder_only、bilingual_companion、no_source_script、below_length_floor)/ **三不管 `unowned_sources`**(非空即缺陷信号,记录不阻断)。文种计数复用 detectors.base.script_counts(单源);方向判断(哪个文种算"源")推迟到 finalize,镜像 configs/detectors.json `residue_directions`。

**截断守卫**:freeze 时存每段 `unicode` 的 sha256,两个入队口(批路径 `pre_translate_paragraph`、short_unit.prepare)在建请求前比对,漂移即 ValueError fail-closed。诚实归因:P1 的 p2#16 类它抓不住(切分在冻结前),抓它的是账单的无主未译;守卫防的是冻结后的文本变异——**且在 T3 实跑中真的抓到了一个八年陈酿**(见下)。

### T1b 切分尾段配对(`42f9cd2`)

溯源:fd p2 是 declared(preserve_line_structure)页,stitch 整页豁免(`exempt: true`),而 line_split 只在单个 finder 段落内组行记录,拼不回被照片切成两个 finder 段落的一条视觉行(PaseF + vGVf8,间隙 1.3pt)。**修法 = 翻开关**:`magazine_stitch_declared` 移入 fixed-true——declared 页只跑 inline 规则、只在独立 source audit 把成员放进 `true_fracture` 类时缝合。B13 建成的通道,B17 点亮。机制选择理由:预翻译合并使整句一次译出,无补全幻觉、无重复表意;链(intra-column)对此对不可达(行内相邻非叠置)。

实证(fd-zh p2):缝合 1 处 32 字,`10 停滞不前 要复兴全球生产力,就要从处理金融危机的后遗症开始` 一体入队 → "10 Stagnation To revive global productivity, we must start by addressing the aftermath of the financial crisis"。尾段与主句同单元,门禁达成。

### T1c 短标签入队(`91d0d26`)

三判据同乘一份文种测量:

1. **表意地板** `ideographic_exception_floor=1`(range 1..5):全汉字候选降到 1 字地板——一个汉字是一个词,一个拉丁字母不是。放行图表轴标(年/低/高 → Year/Low/High)。
2. **跨文种邻居不破 solitary**:solitary 测试的目的是拦断词碎片,而词不会跨文种断开;汉字标签贴着英文报头仍是标签。
3. **双语孪生拒绝** `bilingual_companion`:候选框与其异文种孪生相交(fd p3 `编者的话` 叠在 `FROM THE EDITOR` 上)= 版面故意印的双语对,译出会在同一块墨上把同一句话说两遍——拒绝并记录;coverage 在 freeze 时用同一几何+文种事实(trait `cross_script_twin`)独立命名同一原因,两份报告不可能不一致。

实证(fd-zh):年/低/高全部译出;`编者的话` 双向归因(short_unit refused_units + coverage skip_reason);残留检出 6 → 3(详 T3)。

### T1d 短残留带:测完不加(`480e343`)

见 [t1d_short_band_replay.md](t1d_short_band_replay.md)。拟议 into_zh 短带 [2,12) 在 7 个缓存运行上重放:42 条新增检出全为制版残片/品牌页脚/断词碎片,**零真实漏译**,2/5 样本超每样本预算 10。into_zh 的 12 字地板是对杂志 furniture 生态的正确校准。闭表未动,config 未动。

## T2 展示字形锚定(AW 组,`324e948` + `bf774cc`)

新 pass `display_glyph`(switch `magazine_display_glyph`,fixed-true):段落内连续非空字符跑,长度 ≤ `display_glyph_max_chars=4`(range 1..8),字号 ≥ `min_first_run_size_ratio`(**单源引用 configs/drop_cap.json 的 2.0**,与 span_merge 同源)× 段落自身中位字号——对自身中位数量比让全大段落(标题)天然出局。拆出为独立段落,label `display_glyph`,钉在源坐标源字号;fixed 资产新类 `display_glyph`(FURNITURE_TYPE + asset_class),清除区捕获与 tfo 检测通过唯一枚举器 `fixed_assets.display_glyph_paragraphs` 共读(单源)。两条翻译路径、short_unit、缝合、coverage 全部按 label 放行/保护。

**辖区边界(判定顺序固定)**:display_glyph 按管线顺序先行;段落首个可见字符起步的合格跑=首字形态,让给 drop-cap 通道(记 refused:opening_position_drop_cap_lane)。WIPO 冷跑实证:两处真首字(格/没)正确让渡。

**冷跑当场收紧(`bf774cc`)**:ABB-zh p5 把 30pt 双字题词 `创新`(叠在栏目标签 `编者按` 上)按形状钉住——钉住即静默豁免了一次真实翻译(preserve 角色还让 residue 检测器闭嘴)。修正:**钉住必须翻译不变**——只许数字与符号,任何文种的字母把跑送回排版流(记 refused:lettered_run_translates)。`8` 是任何语言的 `8`;`创新` 不是。

**门禁(AW 全量温跑)**:p3 四枚 8/14/20/32 全部立在源 bbox(最大偏差 **0.00pt**)、源字号,译文墨迹与 8 零相交;全 9 页仅 1 钉(p3 的 8),fd-zh 全量零钉;**AW 检出集合与 B16 基线逐条一致(20 → 20,零增零减)**。

## 守卫的第一个战果:批恢复损坏 bug(`0a56d31`)

fd-zh 温跑中一个批次的模型回复 JSON 畸形,批级异常路径把**整个批次 unicode 列表**赋给了每个段落(`input_[2].unicode = input_[5]`,少了下标)——段落的 unicode 变成 Python list。此前 per-paragraph fallback 从组成重译、译文覆写 unicode,损坏一直被掩盖;B17 的漂移守卫 fail-closed 拦下(日志三处 `translation source drifted`),fd p2 传真行因此留源可见。修复为按元素恢复。守卫上线首个全量跑即抓住其建造目的所指的缺陷类。

## T3 受影响重跑 + 三份冷跑(语料十二份全覆盖)

运行目录:`examples/output/B17/{T3,T3R,T3F,T3F2}`。全部 HITL 走既有决议文件代批(reviews/*.decisions.json,三个冷样本 page_kinds 全覆盖)。实际耗时与花费在预估之内:冷跑单份 3-4 分钟(ABB 39k tokens);温跑单份 1-4 分钟,缓存命中见汇总表。回路接受数全语料为 0(无 PNG 修复证据义务);拒绝均带理由(ABB `overlap_not_ornament` ——B16 头部形态准入在第二个冷样本上再次正确拒绝 xobject 类提名;Courier-zh `orphan_is_canonical_article_text`、`chain_report_path_unavailable`)。

### fd-zh 温跑(最终 T3F)

- **残留 6 → 2,其余 kind 逐数与 B16 一致**(chain_conservation 2 / fragment_cluster 4 / instruction_compliance 10 / out_of_page 2 / tfo 8),零回归。
- 四处漏译:`遗症开始`(缝合整句译出)、`年/低/高`(表意地板译出)——**消失**;`编者的话` ——**归因** bilingual_companion(检出保留,双向命名)。计划外第五处 `The条毫无二致。` ——**归因** N-B17-1(切分尾行 + 缓存命中的 B16 echo;p3,5,6 子集跑曾因 prompt 不同而正常译出,证明是缓存钉住的模型行为)。
- 覆盖账单:231 源全解释,unowned 0;守卫触发 0。

### AramcoWorld-en-v2 温跑(T3)

- **检出集合与 B16 逐条一致(20 → 20,零增零减)**;p3 门禁全过(上文 T2);coverage 9 条未译全 trait 归因,unowned 0。

### 三份冷跑(当前管线首次走通)

| 样本 | 检出(before=after,回路 0 接受) | 覆盖 unowned | 亮点 |
|---|---|---|---|
| ABB-zh(9p) | out_of_page 1 + tfo 2 | 0 | tfo p6#5 被模型提名 refit、确定性准入以 `overlap_not_ornament` 拒绝——检测→提名→准入拒绝链第二次完整走通;display_glyph 字母限制在此定标(创新 拒钉且译出 innovation×5) |
| Courier-zh(8p) | abnormal_blank 1 + chain_conservation 1 + tfo 1 + residue 6 | 0 | 跨页 title 链联译溢出→释放→**成员各排、run 完整走完**(此前两次尝试均死于无条件联译证明);residue 6 条全为照片署名栏(© 摄影者)首次编目 |
| WIPO-zh(6p) | tfo 1(照片署名压图,no_op) | 0 | 两处真首字(格/没)被 display_glyph 正确让渡 drop-cap 通道 |

栏尾指标(tail_fill,冷跑三份):ABB 2 边界(column 2)fill 中位 0.974 / min 0.950,满行率 1.0,short_tails 0;Courier-zh 15 边界(column 13 / page 2)中位 0.907 / min 0.375,满行率 0.6,short_tails 0;WIPO 6 边界(column 2 / page 4)中位 0.727 / min 0.312,满行率 0.17,short_tails 0。

**语料十二份就此全部经当前杂志管线跑通。**

### 全语料汇总表(论文评估章底表)

每样本取其最新完整运行;batch 列注明运行出处。接受数全为 0(B16 起治因优先,回路只在确定性准入达标时动手)。

| 样本 | batch | 方向 | 检出(kind:数) | 接受 | 覆盖源数/归属 | unowned | 缓存命中 |
|---|---|---|---|---|---|---|---|
| fd-zh | B17/T3F | zh-en | chain_conservation:2, fragment_cluster:4, instruction_compliance:10, out_of_page:2, tfo:8, residue:2 | 0 | 231(joint 4/none 48/ordinary 175/preserve 4) | 0 | 74 |
| AramcoWorld-en-v2 | B17/T3 | en-zh | fragment_cluster:1, out_of_page:3, tfo:3, residue:13 | 0 | 149(8/9/127/5) | 0 | 76 |
| ABB-zh | B17/T3R | zh-en | out_of_page:1, tfo:2 | 0 | 133(4/25/85/19) | 0 | 45 |
| Courier-zh | B17/T3F2 | zh-en | abnormal_blank:1, chain_conservation:1, tfo:1, residue:6 | 0 | 138(24/15/94/5) | 0 | 63 |
| WIPO-zh | B17/T3 | zh-en | tfo:1 | 0 | 41(4/9/28/0) | 0 | 12 |
| Courier-en | B16/T5 | en-zh | instruction_compliance:1, residue:5 | 0 | 147(27/17/98/5) | -* | 58 |
| ITU-zh | B16/T5 | zh-en | fragment_cluster:1, instruction_compliance:3, tfo:2, ttc:1, residue:7 | 0 | 99(2/24/73/0) | -* | 35 |
| CERNCourier-en | B15/T4 | en-zh | fragment_cluster:7, instruction_compliance:1, tfo:3, ttc:9, residue:22 | 0 | 235(0/55/179/1) | -* | 61 |
| Vogue-en | B15/T4 | en-zh | fragment_cluster:2, instruction_compliance:1, residue:2 | 0 | 55(0/17/35/3) | -* | 0 |
| FD-en-v2 | B15/T4 | en-zh | fragment_cluster:5, out_of_page:2, residue:7 | 0 | 201(6/33/150/12) | -* | 90 |
| bull-zh | B12 | zh-en | fragment_cluster:1, instruction_compliance:3, tfo:1, residue:12 | 0 | 161(10/32/119/0) | -* | 62 |
| HuaweiTech-zh | B14/T4 | zh-en | fragment_cluster:2, tfo:2, residue:3 | 0 | 277(0/31/219/27) | -* | 88 |

\* B17 前的运行没有 unowned/skip_reason 字段(账单词表本批新增);其 B\A 构成已由 T1d census 按方向定性(en→zh 为 furniture/slug,zh→en 为无源文种图表数字)。

### 分类审计表追加行(page_kinds,HITL 决议文件套用后的运行实际值)

| 样本 | 页 → kind |
|---|---|
| ABB-zh | p1 front_cover, p2 toc, p3 toc, p4 section_divider, p5 editorial, p6 section_divider, p7 toc, p8 article_opener, p9 article_opener |
| Courier-zh | p1 toc, p2 article_opener, p3 photo_spread, p4 article_body, p5 article_opener, p6 article_body, p7 article_opener, p8 article_body |
| WIPO-zh | p1 article_opener, p2 article_body, p3 article_body, p4 photo_spread, p5 article_opener, p6 article_body |

### 既有回归网

- tests/minimal:9 失败逐名与基线一致(468 项中 460 过,失败清单同 [[minimal-suite-baseline-failures]] 记录)。
- spec_check:除 `spec_check_expectations_scope.py`(既有基线失败)外全绿;`spec_check_b14_t2` 以 ABB 工作目录喂参通过。

## 新问题清单(只记录,下批裁决)

- **N-B17-1(切分尾行链缺口)**:收窄带下的短尾行(fd p5#7 `条毫无二致。`,300-350pt)与头段(383-533pt)x 零重叠,intra-column 链 pairwise 重叠门(chain_signals.py:1495)与带聚类均不可达;单独入队时模型行为不定(B16 echo 加 "The" 前缀击穿精确匹配 echo-retry,且该畸形输出被缓存钉住)。正解是译前并链,涉 B13 带几何,缓。
- **N-B17-2(畸形回复被缓存)**:翻译缓存按 prompt 键存原始回复,一次畸形 JSON 回复(fd masthead 批)使同批次每次重跑都确定性走 fallback。fallback 现在能干净完成(0a56d31 + 008a03b),但缓存层面"不存不可解析回复"值得裁决。
- **N-B17-3(title 链溢出的排版形态)**:Courier-zh 释放后的 title 对成员各排,p3#1 上随之出现 abnormal_blank + tfo 检出——释放是正确的守恒行为,但溢出 title 的重试/缩排策略(如 escalation 预算 >1、按槽宽提示模型)是空白。
- **N-B17-4(照片署名栏 residue 形态)**:Courier-zh 6 条与 WIPO/ABB 的 tfo 均为 `© 摄影者/机构` 署名栏(credit rail):zh→en 方向逐条现身 residue。furniture/credit 角色未覆盖此形态;是"保留"还是"翻译"需按出版惯例裁决(摄影者名通常保留)。
- 另:formula_reclass 仍是暗模块(switch 声明、无调用方),与 [[pinned-switch-does-not-mean-wired]] 同型,留案。

## 红线自查

- 覆盖守恒与截断守卫为新增不变量,与段落守恒同级 ✓(fail-closed,实跑验证)
- 闭词表不增 ✓(display_glyph 是资产类;SKIP_REASONS 是 B17 新建账单词表,非缺陷 kind)
- config 单源带 range ✓(ideographic_exception_floor、display_glyph_max_chars;字号比率单源引用 drop_cap.json,未复制数值)
- 无样本字面量 ✓(测试全用构造夹具;bilingual/ideographic/display 规则均为通用判据)
- 默认值先测后定 ✓(T1d 重放否决短带;display_glyph 字母限制由冷跑证据当场定标)
- 前提不符停在任务边界 ✓(P3 → T1d 改测量交付,证伪归档于 T0 记录)
