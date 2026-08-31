# B19 交付报告:缩进按目标语言分离、首字装置解盲、重试反幻觉守卫、正文底边释放

分支 `migration/minimal-v0.6.4`,起点 `77e62f9`(b18)。
T0 复核见 [_t0_premise_findings.md](_t0_premise_findings.md)(P1–P5 全部实质证实,
P4/P5 各带一处精确化修正);回路硬交付见 [mapek_repair_report.md](mapek_repair_report.md);
证据图见 [png/](png/)。

## T1 缩进政策按目标语言分离(`740b563`)

**T0 修正落地**:P5 说"indent_policy 现为单一政策集"——复核发现 mode 选择
**已经**按目标语言键控(`indent_mode_by_target.entries = {zh: "all"}`),en 目标
走 `fallback_mode: "source"`,即"不裁决、照抄中文源几何"。所指缺陷真实存在,
落点比计划预期更小。

- `indent_mode_by_target` → **`indent_policy_by_target`**:从"只键 mode"扩为
  "键整个风格政策集"(`style_indent` / `indent_em` / `article_opening_rank`),
  数值键的 range 在块内声明一次、对每个 entry 同样生效。zh 侧三个值**逐位平移**
  (all / 4 / 1);en 侧声明 `style_indent: none`——英文杂志惯例,正文段首行不加
  风格缩进。en 由"fallback 不裁决"变为"声明式裁决 none",这是行为改变,正是任务目的。
- 功能避让(B16)不进分离:一次墨迹避让是关于一页纸的事实,不是一种语言的惯例,
  任何 entry 都无权重述它。
- **单页验证**(用户指令收窄;执行侧取法:Courier-zh 物理 p5,该页同时有两条源起
  风格旗与一条 B16 功能避让,一页即可正反两证):mode `none`/`declared`,两条风格旗
  按 `mode_decides_nothing` 清平,功能避让段保旗并走实测宽度 **11.81pt**,该页
  正文段**零风格缩进残留**。
- 夹具一正一反(en 各 rank 皆 flush / zh 三值未动);spec gate 新增 E10
  (声明式 flush 目标把源起旗**向下**改写)。

## T2 首字装置解盲 + 重复墨迹(`7ae2a0e`)

**溯源结论**:standalone 首字通道在**十二样本上零命中**——它从未绑定过任何东西。
三条判据各自否决了良构情形:

| 判据 | file:line | 为何是错的 |
|---|---|---|
| `visual.reading_order >= owner.reading_order` | drop_cap.py 配对循环 | 正文段矩形包络首字区是首字装置的**常态几何**,于是 owner 先于 visual 排序 —— 该要求恰好排除良构情形。bull p3:visual ro=3、owner ro=2。 |
| `visual.role not in labels` | 同上 | 版面模型拿到一个孤立字形无从分类:bull p3 判 `plain text`、p8 判 `pull_quote`,同一形状两种标签。 |
| `companion.layout_label not in labels` | 同上 | 同上。 |

后果分两形:p3 的 `核` 原样直通遗留,且正文段**缺首字符**进翻译
(`核技术` → `技术` → "Technology",Nuclear 语义丢失);p8 的 `塞` 作为独立单元
译成 "Senegal" 压在正文起排区(用户所见重叠)。两形同根,一处治法。

- **T2a**:改为方向无关的形状判据——一个孤立的超大字母,起于 owner 自己的左边缘,
  正文首行从其右侧开排,字形纵跨 owner 的起首若干行(`min_initial_line_span`,
  默认 1,range 1..6)。尺寸比仍沿 `min_first_run_size_ratio` 单源。首行间距改为
  **有向**(正文必须在右),放弃一切"框不相交"要求。三条被退役的负向夹具由形状
  判据的真负向替换(纵跨为零 / 正文起于字形左侧)。
- **T2b**:绑定成立即归段——既有 `flatten_standalone` 把首字符并进 owner,
  译出 "Nuclear technology…" / "Senegal has strengthened…";目标首字经既有
  render 提交(en 目标 = 升高式首字母),零新排版原语。HITL 裁决对两个新候选
  照常出具(`p3#0`/`p8#0` → `keep`),Claude Code 代批。
- **T2c 重复署名**:溯源结论与计划的假设不同——**不是同源段渲染两次**。源文件
  自己把 `（图/国际原子能机构）` 画在两条相邻行上(相距 13.46pt,段框并不相交),
  上面那条被它所署的照片**整幅盖住**;译文的拉丁行在同一框内坐姿不同,从照片下缘
  露了出来。即:源隐藏的重复,被翻译变成了可见的重复。
  新通道 `duplicate_ink`(开关 `magazine_duplicate_ink`,默认开):同页同文本、
  共享一行的多份拷贝只印一份,留下的是源展示过的那份——依据是"框内不被美术资产
  遮盖的面积占比",而遮盖清单**取自源文件自身的图像放置矩形**,因为 IL 的
  artwork 清单在这一页里只有一条细线、没有那张照片(实测)。被撤下的拷贝按
  `flatten_standalone` 的同一手法清空(不删除段落),因此覆盖账单不欠它。
- **门禁实测**(bull-zh 全跑):p3/p8 **CJK 遗留 0**;`N`(30pt)与 `S` 挂排;
  `Nuclear technology` / `Senegal has strengthened` 语义完整;首字墨迹与相邻行
  **墨迹级零相交**(净空 2.52pt / 2.88pt——框级"相交"是 B16 记录过的谎言,
  行剖面实测才是答案);p3 residue 1→0,p8 text_text_collision 1→0;credit 重复消失;
  unowned 仍 0。
  **Courier-en 全跑:三处首字逐字节一致**——候选、binding_proof、裁决、render
  by_state、成品坐标(`在` 25.449pt @ [55.961,67.426,81.41,103.972] 等)全同。
  方向改造零回归,因为 Courier-en 的首字全是 inline,standalone 通道在它上面
  本就零命中。

## T3 重试通道反幻觉守卫(`4faa0c7`)

**溯源结论**:两条幻觉都不在 translate_tracking 的任何 output 里——它们来自
**术语梯级 4 钉裁重译**(B18 新通道),写入点
[term_enforce.py:264](../../../babeldoc/magazine/term_enforce.py#L264),该处唯一的
验收是"钉的译名在不在输出里",而幻觉整段里恰好含有它。两条回复**都在缓存里**
(`~/.cache/babeldoc/cache.v1.db` id 2344 / 2273),N-B17-2 形态实锤:温跑不发请求
即可复现。

- **咽喉点**:`retry_guard.accept()`,由三条单单元通道共同调用——echo-retry、
  级 4 钉裁、short_unit 补译。溯源另发现 `name_harvest` 亦是同族但开关钉死为假,
  不在本批辖区,记 N-B19。
- **阈值全部实测,不是选的**。计划给的 `retry_output_max_ratio` 默认 4 被语料
  证伪:按字符计,中→英正当译文最宽处 **6.79**,而必须拒的回复是 **15.5**,
  两个阈值挨得太近不可能都安全。改为**文种中性度量**(一个汉字或一个词记 1),
  这正是上游用 tokenizer 达到的效果而无需 tokenizer:如此量之,十二样本全部
  **1456 个已译单元**都 ≤ 9.0,两条被拒回复是 7.75 与 118。
  句终标点亦经实测:把每个拉丁句点都读作句终,会把六条正当的公司名/职务译文
  误判为多句散文,故拉丁句点只在收尾或另起一句时计数。
- **三条判据**:句子发明(源无句、译文有句、且体量超 `retry_sentence_max_ratio`
  =5.0——语料中最宽的正当片段译文是 3.69)、粗长度(比值**与**绝对上限须同时
  越界)、内容锚(名形输入、无共享 token、非纯目标文种改写、且超比值——本批
  **零次触发**,如实记而非隐去)。全语料 1456 单元回放:**误杀 0**。
- **拒绝的后果**:原文逐字节保留 + typed 理由入 tracking 与账单,**不重问**;
  并把该回复**从缓存中丢弃**(`TranslationCache.discard`,新增上游方法,
  已记 UPSTREAM_DIFF),否则下一跑仍被喂以本跑拒绝的答案。
- **门禁实测**:两条已投毒缓存条目清除后重跑(该处冷)——引擎**又生成了同形
  幻觉**,守卫当场拦下两条,各按 `retry_hallucination_rejected` 升级进人工违裁清单,
  守恒等式 `ruled == applied + substituted + retried_ok + escalated` 两样本皆真。
  CERN p3 页脚与 Courier p1 封面**幻觉消失**(见
  [png/t3_cern_p3_footer.\*](png/));两样本全部 **302 个已译单元**过守卫扫描,
  超限 **0**。

## T4 正文底边释放 + 最小可读字号(`ac433d7`)

- `min_visual_font_pt`(6,range 4..10)是"缩放不再算拟合"的下界。搜索跨过它之前,
  源框底边释放进下方的确定性走廊:**B18 的宽度走廊转九十度**,读同一份
  `functional_clearance_pt`、同一个文件,两个方向不可能对同一页给出不同答案。
  刻意**不复用** `get_max_bottom_space`(它把版心乘 1.1、不留净空)——那是本 pass
  身旁那条既有扩展的构件,原样不动。
- 三条限制各有其义:地板只辖 running body text(按本 config 已声明的 `body_labels`,
  因为页码设得小是**故意**的);**外来的框一律不释放**(flow slot、联排成员的份额、
  承诺"进不可变源框"的 bounded 重排——只有段落自己的源框可放);每段一次,
  且只在更高的框真买回可读字号时采纳,两种结局都记录。
- **门禁实测**(Courier-zh 全跑,如实分级):
  - `defending their rights…`(10 行)**4.38pt → 6.56pt**,越过地板 ✔
  - `There are countless cases…`(2 行)**3.50pt → 4.38pt**,释放了 5.90pt 仍不足:
    走廊下方只有 5.90pt,而两行地板字号需 15.6pt、释放后的框是 14.28pt,差 1.3pt。
    走**走廊不足的兜底分支**,`corridor_exhausted` 记录在案,不强求。
  - 全样本 <6pt 的 span 数 **153 → 142**;检出集与 B18 **逐条相同**(6 条 residue,
    同页,零新增重叠);四条 unbounded fallback **按 debug id 逐条相同**;
    覆盖 owners 与 unowned 未变。

## T5 运行矩阵

| 任务 | 样本 | 方向 | 范围 | status | 缓存命中 | unowned |
|---|---|---|---|---|---|---|
| T1 | Courier-zh | zh→en | p5 单页 | complete | 1 | 0 |
| T2 | bull-zh | zh→en | 全跑 | complete | 71 | 0 |
| T2 | Courier-en | en→zh | 全跑 | complete | 58 | 0 |
| T3 | CERNCourier-en | en→zh | 全跑 | complete | 74 | 0 |
| T3 | Courier-en | en→zh | 全跑 | complete | 58 | 0 |
| T4 | Courier-zh | zh→en | 全跑 | complete | 62 | 0 |

六跑 exit 0、status complete、unowned 全 0。幻觉相关键清缓存后局部冷,
级 4 实际重译 2 次(两条皆被守卫拒),其余翻译近零。

- **回路**:9 次提名全部被确定性准入拒绝(闭表理由,逐条见回路报告),
  接受 0、回滚 0、PNG 义务 0,双向门禁以全零成立;`translator_requests` 六跑均 0。
- **回归**:tests/minimal **9 败逐名同基线 / 531 过**;spec_check 除既有基线项
  `expectations_scope`(3/5)外全绿,`indent_scope` 15/15、`switch_completeness` 5/5、
  `demo_verifier_scope` 16/16、`hitl_term_source` 14/14、`repair_admission` 6/6、
  `residue_evidence` 5/5、`tail_aligned_backfill` 12/12、`b12_*` 全部 all claims hold。
- **一处需要说清楚的门禁**:`spec_check_b14_t1` S3(成品首字墨迹顶端须与源首字
  墨迹顶端对齐,容差 1pt)在 bull-zh 上**失败**(p3#0 −14.00pt)。这**不是本批回归**,
  而是本批让一条既有状况第一次在这个样本上可被检验:
  - en→zh 半区 B18/B19 **逐值相同**全绿(Courier-en:+0.00 / +0.00 / −0.25pt)。
  - zh→en 半区**在 B18 就已失败**:WIPO-zh p2#1 −16.00pt、ITU-zh p7#2
    "no source ink in the probe window"、HuaweiTech-zh "no committed initial"。
  - 成因:该断言的前提只对 `chinese_two_line_initial`(en→zh)成立。zh→en 走
    `english_raised_initial`,渲染层按首行 cap 高度定位、`anchor: null` 是设计,
    升高式首字本就应比源的两行式首字**更高**。断言把一种排版惯例当成了全体的契约。
  - B18 的交付报告称"spec_check 全绿"是**记录不全**:该 gate 需两个参数,
    当时未对 zh→en 工作目录跑过。记 N-B19-6。

## N-B19 清单(只记不修)

- **N-B19-1** `babeldoc/magazine/cache_setup.py` 的 `use_project_cache` 声称
  "每个入口都调用",实为**零调用**:`examples/cache/` 不存在,真实缓存一直在
  `~/.cache/babeldoc/cache.v1.db`;其 `init_db(db_path=..., enable_cleanup=...)`
  签名也与上游 `init_db(remove_exists=False)` 不符,即便调用也会报错。
  后果:缓存不随项目走,且上游的 MAX_CACHE_ROWS 淘汰仍在生效——本批赖以复现的
  两条投毒条目本可能早已被淘汰。
- **N-B19-2** `name_harvest` 是第四条单单元 LLM 通道,与本批咽喉点同族,
  但开关钉死为假、本批未纳管辖。开关一旦翻开,它绕过 `retry_guard`。
- **N-B19-3** 回路的检出面与本批四类缺陷几乎不交:首字缺陷只以两条间接征状
  现身(遗留 residue、误译碰撞),幻觉与过小字号**没有任何检测器看得见**。
  需要能读出"这段译文与其源文无关"与"这行字小到不可读"的检测器。
- **N-B19-4** 成品在 en→zh 半区使用 CJK 兼容表意字(如 U+FA08「行」),
  以常用码位 grep 成品会漏检;任何成品文本扫描器都需先 NFKC 归一。
- **N-B19-5** T4 的走廊只朝下。`There are countless cases…` 差 1.3pt,
  而它右侧另有空间——多词段落的横向扩宽通道(N-B18-1)与垂直走廊尚未联手。
- **N-B19-6** `spec_check_b14_t1` S3 把 `chinese_two_line_initial` 的锚定契约
  当成了全体首字的契约,于是整个 zh→en 半区自 B18 起就在失败(WIPO −16.00pt、
  ITU 探测窗无源墨、HuaweiTech 无 committed)。断言需按 `direction_policy` 分支:
  锚定式比对源墨迹顶端,升高式比对**首行 cap 高度**。附带:该 gate 需两个参数,
  B18 未对 zh→en 工作目录跑过,故"全绿"的记录不全。
- 既有 **N-B17-1/3/4** 与 **N-B18-1..4** 原样带入;**N-B17-2**(畸形回复入缓存)
  在本批 T3 辖区内的部分**标记结清**——拒绝即丢弃缓存,两条在案条目已清除;
  其余形态(chain 通道的畸形回复)原样带入。

## 红线自查

守恒:T3 拒绝即原文逐字节(不改一字,只记理由);T4 释放只动框的一条边、不改字符集;
T2 撤下重复拷贝按既有手法清空且覆盖账单不欠(unowned 仍 0)。
单点执行:T3 咽喉点唯一(三通道共用一个 `accept`);T4 与 B18 T1 同一函数族、
同一份 clearance。config 带 range:本批新增七个键(`min_initial_line_span`、
duplicate_ink 四键、retry_guard 三键、`min_visual_font_pt`)全部带 `_allowed_range`。
闭表:拒绝理由三词 + 家族名、withhold/keep 理由各一组、bottom_release outcome 两词。
无样本字面量(bull 的坐标只出现在测试夹具的注释与常量里,规则本身不含任何页码或
出版物名)。报告全为实测数,T4 的半达成如实分级。前提复核未触发停机。
