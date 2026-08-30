# B13 — 四个成品质量问题的修复(演示级)交付报告

分支 `migration/minimal-v0.6.4`,基于 `7387d60`,任务提交
`d3f311d`(T1)· `5d3976a`(T1 补)· `ff65c6c`(T2)· `203b1da`(T3)·
`4542d3a`(T4a)· `d3b8e48`(T4b),tag `b13-render-fixes`。
验证样本:Courier-en(C1/C3/C4)与 FD-en-v2(C2),其余样本未跑。
改前基线工件:Courier 为 `examples/output/B12/Courier-en/`(即定因所用
work 目录),FD 为 `examples/output/fix0829/FD-en-v2/`(fix0829 早于
B12,但 B12 未触碰 C2 相关路径,作为改前状态成立;其运行早于
short_unit 报告的出现,故该侧改前证据缺一项,见 C2 节)。

## T0 前提复核结论

四条成因全部成立,其中两条与计划字面有出入,均不改变修法方向,
已分别登记 `UPSTREAM_DIFF.md`:

1. **C2 的"精确相等已有通路"实为死代码。** 上游 `a515ea2` 把比较右
   操作数从 `translate_input.unicode` 改成了对象本身,`str == 对象`
   恒假,连字节相同的输出也会重排。计划修法(归一化比较)本就要
   替换该行,且必须读 `.unicode`,方向不变、必要性更强。
2. **T4a 要新写的 pass 已存在而未接线。** `fragment_stitch.py` 完整
   实现(规则、守卫、审计、报告,docstring 直接点名本案例的
   `There are many more examples of how t` / `raditional knowledge`),
   开关钉为 true,但 `apply` 零调用、零测试。本批接线并按下述
   理由收窄规则,而非另写一份。

## C1 首字颜色跟了正文 → 已修

**成因(实测)**:源 p4 内容流 `(L)Tj` 前的填充为
`/CS0 cs 0.741 0.744 0.326 scn`,`/CS0 = [/ICCBased 50 0 R]`、
`/N = 3`(即 RGB 橄榄绿);颜色捕获解不开命名色彩空间,记
`scn:CS0:unsupported` 后回落 DeviceGray 黑。

**修复**:`freeze_color` 接受解析器;标记期在源 PDF 的字符自身
上下文(先表单 xobject 资源、后页面资源)解析 `cs`/`CS` 名字,
ICCBased 按 `/N`(1/3/4→Gray/RGB/CMYK)映射,直接设备名照收;
Separation/DeviceN/Pattern 等有意维持 unsupported,回落行为不变,
解析成败均入 evidence。

**改后实测**(`B13/Courier-en/work/.../drop_cap_intent.report.json`):
三个首字(p4#3、p5#5、p7#8)`source_color.fill.rgb` 全部为
`[0.741, 0.744, 0.326]`,与源流 scn 分量逐字节相等,evidence 含
`resolve:/CS0->DeviceRGB`;渲染报告 `post_render_color_failed = 0`,
`set: 3, committed: 3, reverted: 0`。

**图**:`courier-p4-dropcap-before.png`(黑"在")→
`courier-p4-dropcap-after.png`(橄榄绿"在",与源 `courier-p4-source.png`
的"L"同色)。

**门禁**:`tests/minimal/test_drop_cap_color.py` 6 例(正向捕获、
Separation 反向回落、无解析器不变、合成 PDF 端到端、缺源存活)。

## C2 未译/同文段落被重渲 → 已修

**成因**:见 T0 第 1 条——相等判定死于类型;近似相等更无通路。

**修复**:`post_translate_paragraph` 比较双方 NFC + 折叠连续空白 +
去首尾空白后的形式(仅此三条,无更宽模糊),相等即不改
composition。下游保护链路经实读闭合:无 unicode holder →
`_has_generated_target` 假 → protected → typesetting passthrough;
paren_dedup 只动 unicode runs、indent_policy/article_flow 不写
composition、title_typeset 的冻结同样以 unicode holder 为门,均不
需要前置豁免(以代码实读+夹具钉住,非推测)。

**改后实测**(FD-en-v2 全文重跑):
- translate_tracking 中归一化相等的段落 23 个(五个 `F&D` 页脚、
  刊头 14 个人名、`www.imf.org/fandd`、阿拉伯文 RTL 串
  `اقرأ باللغة`、纯占位符串等),其中 21 个字节级相同。
- **PDF 级守恒**:同文段落中可在源 PDF 词表里对齐的 32 个拉丁词,
  31 个在输出 PDF 的坐标与源逐字节相同(0.01pt 舍入粒度),1 个
  (`Celasun`)仅 x 差一个 0.01 舍入档,y/x2/y2 全同——为写出器
  浮点序列化噪声,非重排。
- **改前对照**(fix0829):同批人名全部重排——y 移 +2.28pt、字宽
  异(`Carriere-Swallow` 52.4pt 对源 59.8pt,替换字体度量),
  顾问名单换行错乱且 `Aqib Aslam`/`Helge Berger` 等被音译丢名。
- `short_unit.report.json` 中 5 个单元 `identity_skipped: true`
  (五个 `F&D`)——该字段在本修复前不可能为真(死比较),fix0829
  运行早于该报告存在,故无改前对照文件,此点由代码史而非工件
  证明。

**图**:`fd-p5-masthead-before.png`(重排+错行+丢名)→
`fd-p5-masthead-after.png`(源字体源坐标逐行还原)。

**门禁**:`tests/minimal/test_translation_identity_skip.py` 4 例
(字节相同、仅空白差、NFC 变体三者 composition 对象身份不变且
`_has_generated_target` 假;实质不同正常重排)。改动登记
`UPSTREAM_DIFF.md`(上游文件 il_translator.py)。

## C3 跨栏接续段前段结尾非整行 → 已修(机制级)

**成因**:tail_aligned 只会回拉;p4#20 理想切点落在首行内,回拉致
`kept_lines: 0` 被 `min_lines` 拒,切点留在行中
(B12 实录 `reason: min_lines, moved_chars: 0`)。

**修复**:回拉被拒时前推至理想切点所在行的测量行末(候选必须是
本成员自箱实测的行末),受两重界:窗口保证后续成员各留至少一字,
`tail_align.push_max_chars`(默认 24,range 1..80)防整段搬家;
`tail_align.allow_push`(默认 true)关掉即逐位回到旧行为。行网格
在开推时至多多测一次。报告词表:`cuts_by_reason` 增 `pushed`,
`pushed_chars` 与 `moved_chars` 并列,pushed 切同样记
`moved_to: line_end`。

**改后实测**(同链重放):p4#20 记
`{ideal: 20, position: 29, moved_chars: -9, kept_lines: 1, reason: pushed}`
——前推 9 字符至测量行末;全局 `cuts_by_reason:
{moved: 8, min_lines: 2, pushed: 1}`,`pushed_chars: 9`;全部 11 条链
`allocation.verified: true` 且逐链碎片拼回整译文(sha 相符)。
**如实说明**:切点落在成员自箱的*测量*行末;最终排版按成品字号
重新折行,视觉上末行为"明显更满"(`courier-p4-handover-after.png`
末行 "得益于国际文书,例如" 对改前 "得益于诸如")而非必然齐行,
测量尺度与渲染尺度之差是既有机制属性,本批未动。
新出现的两个 `min_lines`(p4#4、p4#6,单行箱)是窗口守卫的正确
拒绝:前推会掏空后续成员。

**门禁**:`tests/minimal/test_tail_align_push.py` 10 例(p4#20 形态
重放、超界拒、掏空拒、关开关旧行为、合法回拉优先、两分支守恒、
配置越界拒)。`tools/spec_check_tail_aligned_backfill.py` 12/12。

## C4 Courier p4 段落切碎 → 已修

**T4a(词中切断)**:接线既有 fragment_stitch(见 T0 第 2 条),
挂点在分类器之后、line_split 与链构建之前;被并走的成员留位释墨,
段索引全稳。**规则收窄为 inline 单条**并在配置声明理由:vertical
会把宽带与其下窄栏并成一个矩形并集(对 p4 实测,该并集压过
pull-quote 区),摧毁 T4b 逐槽保持的绕排几何;initial 会把超大首字
在源字符层重刷为正文多数样式,摧毁首字通道(含 T1)冻结的样式/
颜色证据。两者保持已实现、按声明可再启用;规则校验放宽为非空
子集。计划拟新设的 `same_line_y_overlap`/`same_line_max_gap_em`
未铸造——模块既有的 `stitch_min_y_overlap_ratio` 0.6 /
`stitch_max_inline_gap_ratio` 0.8em 已治同一判断。

改后实测:`fragment_stitch.report.json` 恰两针,
`p4#4 = "There are many more examples of how traditional knowledge"`、
`p4#6 = "has proven its worth, in areas as diverse as water management,"`
——两处词中切断(`t|raditional`、间隙 0.7pt / 2.6pt)复原,
`style_normalized: 0`。translate_tracking 全文不再有任何词中输入。

**T4b(宽窄带断段)**:chain_signals/chain_builder 新增第三边界类
`intra_column`:同带相邻、双方 body 标签、水平重叠、垂直缝 ≤
`intra_column_chain_max_gap_pt`(默认 6,range 1..24)、前带尾无
终结标点、后带头上方净空。规则声明为确定性门,行记录照算全部
信号但 `score: null`(没有阈值参与裁决就不写数)。装配优先级居
末;排他装配、小写接续守卫、pair class(由成员标签推导,
body→tail_aligned)、联合翻译、守恒律全部复用,零新建重分配。

改后实测(p4):3 条 `intra_column` 边(#4→#6、#6→#8、#9→#10),
成链 `[p4#4, p4#6, p4#8]`(536 源字符 1 次联翻)与 `[p4#9, p4#10]`;
被拒的相邻对全部因 `tail_no_terminal_punct: 0.0`(真句号处),逐行
可查。前提中的 `Today, Indigenous | communities worldwide` 断段由
#9→#10 链治愈(成品页读作"如今,全球的土著社区正在捍卫……")。
p4 独立翻译单元 **17 → 10**;全文链 9 → 11、边 9 → 12。图:
`courier-p4-band-before.png`(空洞+残句)→
`courier-p4-band-after.png`(三带连续文流);整页
`courier-p4-before/after/source.png`。

**门禁**:`tests/minimal/test_fragment_stitch.py` 9 例(p4 重放、
四类守卫反向、开关、报告、vertical 收窄钉死)、
`tests/minimal/test_intra_column_chain.py` 5 例(三带成链、终结标点
断链、超缝不设边、带边+栏边并成一路、三成员守恒)。

## 检出基线移动(风险声明兑现)

T4 动了分段,检出必然移动,实测:

| 样本 | 改前 | 改后 |
|---|---|---|
| Courier-en | instruction_compliance 1 · untranslated_residue 5 | **相同**(1 · 5) |
| FD-en-v2 | fragment_cluster 5 · out_of_page 2 · untranslated_residue 22 | fragment_cluster **4** · out_of_page 2 · untranslated_residue **23** |

FD 两处变动逐条比对过:residue 集合按摘录基本一一对应(仅
debug_id 随运行更换);净 +1 来自修复页上段落组成形态与文章归属
的改变(如顾问名单从"重排合成空格版"变为"源字符版"),刊头人名
在改前改后**均**被 residue 检出——C2 保护的是渲染形态,不改变
"这些段落确实是拉丁文"的检出事实。不回填历史批次数据。

## 运行与既有门禁

- Courier-en 全文:57 次翻译调用,31 次命中缓存;FD-en-v2 全文:
  65 次,14 次命中。两次运行 rc=0。
- `tests/minimal`:**9 failed / 340 passed**,失败逐名与基线一致
  (B12 记录的九个),新增 34 通过(本批 34 个新测试)。
- `tools/spec_check_*`:15 个脚本,14 个全绿;
  `spec_check_expectations_scope` 维持基线既有的 3/5。

## 遗留与顺延

- B12 的 T7(真实样本门禁 + 准入普查)按计划顺延,未并入本批。
- fragment_stitch 的 vertical/initial 规则保持声明关闭;若需启用,
  各自需先解决本报告记录的并框/重刷冲突。
- C3 的"末行满"以测量行末为准;测量-渲染尺度差(既有属性)使
  视觉不必然齐行,如需齐行需另行对齐两个尺度,超出本批红线。
- 本批只验 Courier-en 与 FD-en-v2;其余样本的检出移动未测量。
