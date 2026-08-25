# B11.7 前提差异报告 —— 停止执行

依 §5.2:动手前复核 PLAN 引用的代码事实,事实与前提不符即停止并报告。

前置 tag `b11.6`(825670a)。所核为该 tag 上的树与 `examples/output/b11_6/` 的
冻结证据。机器可复算的量全部由
`examples/output/b11_7/scripts/premise_check_b11_7.py` 产出,落在
`examples/output/b11_7/premise_check.json`。

**裁决:STOP。六条前提中五条成立,第 4 条的第二个分句不成立。**

代码一行未改,配置一字未动。本批未跑任何样张,未发起任何 API 调用。

---

## 0. 前提逐条

| # | 前提 | 实测 |
| --- | --- | --- |
| 1 | FD indent sidecar p3 三段 `before:true, after:true`,源几何继承;`page_ineligible → left_alone` | **成立** |
| 2 | FD p6 栏链续段首行 x=409.4 vs 后续 393.7;句界回填使整句落入第三栏首 | **成立** |
| 3 | Courier-zh 残留四处,两报两未报 | **成立** |
| 4a | 上游 typesetting 对 vertical 段恒以水平矩阵重排 | **成立** |
| 4b | residue 检测器读 IL 段文本,**公式字符不计** | **不成立** |
| 5 | body 链现行为句界回填;indent_policy 合格页加缩进、其余不动 | **成立** |
| 6 | `translate_orphan_lines` 受理 fallback_line;p6 finding 未被修 —— 拒绝还是施加失败 | **成立**,判定见 §3 |

---

## 1. 成立的五条,实测值

**前提 1**。`FD-en-v2/sidecars/indent_policy.report.json`:p3 共 52 段,带缩进标志
的恰为 `p3#18` / `p3#36` / `p3#43` 三段,三段均 `before=true, after=true,
decided=false, skipped="page_ineligible"`。p3 全页 `decided = 0`,跳过理由集合
恰为 `{page_ineligible}`。全文 `left_alone = 194 = 167 + 27`。

**前提 2**。`FD-en-v2/indent_evidence.json`:`p6#12` 盒 x=393.650、首行
x=409.375(offset 15.725、`first_line_indent=true`);其后 `p6#13` 盒 x=393.647、
`p6#14` 盒 x=393.363。excerpt 含整句"食品和化肥成本上升"。

一处记法订正:前提写的 393.7 是 393.650 的四舍五入,而 `round(393.65, 1)` 在二进
制浮点下得 393.6(393.65 的最近可表示值略小于 393.65)。门禁写这类断言须用容差比
较而非取整相等,否则一条为真的命题会因舍入方向报假。本脚本已按容差 0.1 pt 写。

**前提 3**。`Courier-zh` 译后 PDF 的**文本层**canvas 扫描,CJK 字形逐页
`{p3: 10, p5: 31, p6: 23}`,合计 64,分布在四处版面单元:

| 处 | 页 | 走向 | 文本 | 检测器 |
| --- | --- | --- | --- | --- |
| 1 | 3 | 旋转 | `卡洛丽娜·赞布拉诺（Carolina Zambrano）` | **未报** |
| 2 | 5 | 水平 | `巴西：水之民族的启示` | **未报** |
| 3 | 5 | 旋转 | `阿德里亚诺·甘巴里尼（Adriano Gambarini）/亚马孙原住民行动组织` | 已报 `p5#8` |
| 4 | 6 | 旋转 | `鲍里斯·塞梅尼亚科为联合国教科文组织《信使》创作` | 已报 `p6#14` |

`issues.json` 的 `untranslated_residue` 恰为 `p5#8` 与 `p6#14` 两条。

**p1 canvas 文本层 CJK = 0**,与 T3.5 的图片字排除自洽:那三处字形在图片层,
文本抽取够不到,不入账。这一条前提为真且与硬约束无冲突。

**前提 4a**。`_layout_typesetting_units` 全函数以 x 为行内轴、y 为行间轴书写:
`current_x = box.x`、`current_y = box.y2 - avg_height`、换行判据
`current_x + unit_width > box.x2`,函数签名与函数体内**不出现任何轴参数**。新造
的译文字符在 `typesetting.py:861` 以 `vertical=False` 构造。即无论段落是否
vertical,重排一律沿水平轴。

**前提 5**。`configs/chain_translation.json` 的
`strategies.by_pair_class = {"body": "sentence_greedy", "title": "proportional"}`,
默认 `sentence_greedy`。`indent_policy.py:372-386`:`decision` 仅在
`eligible` 为真时求值,否则为 `None` 且不写回;sidecar 全文零段
`decided ∧ ¬indent_eligible_page`。

---

## 2. 不成立的一条 —— 前提 4b

### 2a. 命题与实测

前提写:"residue 检测器读 IL 段文本,**公式字符不计**"。

实测:**公式字符全部计入**。链路是
`residue.detect → base.rendered_text → reading_order.paragraph_reading_text`,
而 `reading_order._CHARACTER_HOLDERS = ("pdf_same_style_characters", "pdf_line",
"pdf_formula")` —— `pdf_formula` 在其中,其 `pdf_character` 全部被取出计数。

这不是读代码读出来的推论,而是已冻结的运行自己说的话:Courier-zh 七个带 han 的
IL 段**全部**是纯 `pdf_formula` 组成(无一例外),而检测器**已经报了其中两条**,
且报出的数字与逐字符重算**逐位相同**:

| ref | 组成 | han | 全脚本 | ratio | issues.json 记录 |
| --- | --- | --- | --- | --- | --- |
| p5#8 | 纯 pdf_formula | 13 | 29 | 0.4483 | `residue_chars 13, script_chars 29, residue_ratio 0.4483` |
| p6#14 | 纯 pdf_formula | 16 | 16 | 1.0 | `residue_chars 16, script_chars 16, residue_ratio 1.0` |

若公式字符不计,这两条的 `residue_chars` 都会是 0,两条 finding 都不会存在。

### 2b. 两处未报的真实成因

不是盲区,是两道**已声明的下闸**遇上**段落碎裂**:

| ref | 标签 | 走向 | han | 全脚本 | ratio | 未报因由 |
| --- | --- | --- | --- | --- | --- | --- |
| p3#2 | fallback_line | 旋转 | 1 | 17 | 0.059 | `residue_min_script_chars`(12) |
| p3#3 | fallback_line | 旋转 | 7 | 7 | 1.0 | `residue_min_script_chars`(12) |
| p5#0 | abandon | 水平 | 9 | 9 | 1.0 | `residue_min_script_chars`(12) |
| p5#9 | abandon | 旋转 | 6 | 6 | 1.0 | `residue_min_script_chars`(12) |
| p6#15 | fallback_line | 旋转 | 5 | 5 | 1.0 | `residue_min_script_chars`(12) |

`configs/detectors.json`:`residue_min_script_chars = 12`、
`residue_min_ratio_into_en = 0.4`。

要看清的是**碎裂**这件事:p3 那一行版面上是一行,IL 里是**两段** ——
`p3#3 = "© 卡洛丽娜·赞布拉"`(7 字)与 `p3#2 = "诺（Carolina Zambrano）"`(1 字
+ 16 拉丁)。整行合起来 han=8、latin=16,任何按段计的 12 字下闸都拦不住它;拆开
之后更拦不住。p5 的 Gambarini 一行同样是 `p5#9 + p5#8` 两段,只是后半段自己够到
了 13 字才被报出来。p6 亦然(`p6#15 + p6#14`)。

### 2c. IL 与 canvas 逐页相等

用**同一个** CJK 谓词同时数 IL 段文本与译后 PDF 文本层:

| | p3 | p5 | p6 | 合计 |
| --- | --- | --- | --- | --- |
| IL(checkpoint.11) | 10 | 31 | 23 | 64 |
| canvas(文本层) | 10 | 31 | 23 | 64 |

**逐页相同**。旋转字符也不构成盲区:`reading_order` 专为 vertical 段按几何重排读
序,`p6#14` 正是一条旋转段且**已被报出**。

即:**IL 视野内没有任何一个 canvas 上有而 IL 里没有的 CJK 字符。**

---

## 3. 前提 6 的判定 —— 施加失败,不是拒绝

`Courier-zh/sidecars/react_repair.report.json`,第 1 轮:

- 决策:`translate_orphan_lines`,`issue_ids = ["untranslated_residue:p6:p6#14"]`,
  理由"residue_ratio 1.0、16 字、label 为 fallback_line,三条全中"。**受理了。**
- 执行:`attempts = 1`,发起真实请求一次(`cache_verdict =
  no_stored_reply_under_this_key`),引擎**答了**:
  `source_text = "作创》使信《织组文科教国合联为科亚尼"` →
  `translated_text = "Creative Work by Keni"`。
- 结果:`accepted = false`、`changed = false`,
  **`reason = "retypesetting_needed_more_room_than_the_paragraph_had"`**。
- 全局:`applications = 0`、`stopped_because = "no_paragraph_was_written"`。

**判定:施加失败(apply failure),不是拒绝(refusal)。** 动作选了、钱花了、
答案回来了,倒在写回的最后一步 —— 重排装不下。

成因与前提 4a 直接咬合:`p6#14` 的盒是 `x 413.39–419.84`(**宽 6.45 pt**)、
`y 709.71–823.61`(高 113.9 pt)的旋转窄条。排版器按水平轴装箱,它量的是那
**6.45 pt** 当行宽,任何一个拉丁词都放不进去。**这条 finding 未被修的原因不在
判定层,在写回层**;T3.4 要造的"旋转写回车道"正是它缺的那一段。

顺带一条对 T3 有用的观察:`source_text` 是**字序倒排**的("尼亚科为联合国教科文
组织《信使》创作"倒着写),模型据此产出的 `"Creative Work by Keni"` 是对一个被打
乱的问题的回答。IL 的存储序即倒序,`reading_order` 在**检测**侧把它转正了,而
**修复**侧送进引擎的是 `offered_text`,与 `source_text` 同为倒序 —— 两侧读的不是
同一个串。这一点前提里没有,记在此处。

---

## 4. 差异对计划的影响面

只影响 T3 的三个子项,且**只影响其理据,不必然影响其目标**。逐条:

**T3.1(检测器 canvas 化)**。计划的理据是"IL 级盲区(前提 3 的两处未报)随之关
闭"。**该盲区不存在**(§2c:IL 与 canvas 逐页相等),故 canvas 化**关不掉**那两
处 —— 它们不是没被看见,是被两道下闸挡了。

但目标本身仍成立,且路径就在证据里:硬约束"canvas 零 CJK 字形"是**页级**命题,
而现行检测是**段级带下闸**的。要让检测器看见那五段,改的是**计数的粒度与闸的位
置**(页级零容忍 vs 段级 12 字/0.4 比),不是数据来源。这是一个比"换数据源"更小
也更准的改动,但它**改的是阈值语义**,按 §5.14(c) 须由用户在修正案里明写。

**T3.2(反向括注)**。计划称其"关闭 p3 类"。**关不闭**:`中文串（Latin串）` 的模
式按段匹配,而 p3 那一行**碎成两段** —— 模式只命中 `p3#2`(输出
`Carolina Zambrano`),`p3#3` 的 `"© 卡洛丽娜·赞布拉"` **7 个 CJK 字符原样留在
canvas 上**。p5 的 Gambarini 一行同理:命中 `p5#8` 会输出 `Adriano Gambarini`,
却把 `/亚马孙原住民行动组织`(该译而非该还原的机构名)一并丢掉,且 `p5#9` 的 6
字不动。**碎裂是这一子项的前置问题**,计划里没有它。

**T3.3(公式吞字的方向感知豁免)**。计划的触发条件是"段内公式 composition 含
CJK"。实测:七段**全部**是纯 `pdf_formula`,该条件对**七段全中**,包括已被正常报
出并本可走常规路径的 `p5#8` / `p6#14`。故这一子项的作用面比计划设想的大得多,
§4.18 的消费者清单要按"七段全改判"来做,而不是按"页脚一处"。另,其立项理据
("关闭 p5 页脚类"因公式吞字而未报)同样不成立 —— `p5#0` 对检测器**完全可见**,
只是 9 字不足 12。

**T1 / T2 / T3.4 / T3.5 / T4 不受影响**:前提 1、2、4a、5、6 全部成立。

---

## 5. T3.4 可行性 —— 三处承载点的实测(未完成裁定)

计划要求"逐项核查写回路径:字符矩阵构造、排版对旋转盒的处理、渲染端矩阵消费,
三处均可承载则实现"。因前提校验已判 STOP,**本会话不作最终裁定**;三处的实测事
实记于此,供修正案取用。

**(c) 渲染端 —— 可承载。** `pdf_creater.py:111` 与 `:1186` 两条渲染路径都消费
`char.vertical`,为真时发
`BT /F sz Tf 0 1 -1 0 {box.x2} {box.y} Tm`,即 90° 逆时针,锚在盒右下。现存三处
残留在 canvas 上的走向实测均为 `dir (0, -1)`,与这一个矩阵吻合。

一处需在修正案里改写的措辞:计划写"per-char 矩阵**取源旋转**"。IL 上没有源旋转矩
阵可取 —— `PdfCharacter` 只带一个布尔 `vertical`,渲染端把它固定展开为那**一个**
90° 矩阵。在这三处上二者等价,但"取源旋转"这个说法在现行 schema 下无所指,而 IL
schema 处于冻结态(§4.10,W-B1-01 未解除)。

**(a) 字符矩阵构造 —— 现不承载,改动落在上游。** `typesetting.py:861` 造新字符时
`vertical=False` 为硬编码。译文字符因此一律水平。要旋转写回,须让它继承段落的
vertical —— 一处上游改动,需 UPSTREAM_DIFF 登记与消费者清单。
(注:`:550` 与 `:613` 两处**沿用**源字符的 `char.vertical`,即标志本身在直通与公
式路径上是活的;死的只是新造字符这一支。)

**(b) 排版对旋转盒的处理 —— 现不承载,且这是三处里唯一可能超出"一条车道"的。**
`_layout_typesetting_units` 没有轴的概念(§1 前提 4a),其**每一个**几何决定都写
在 x=行内 / y=行间上:`space_width`、`hang_limit`、`line_ys`、
`first_line_indent` 加在 `current_x` 上、悬挂标点的 `overflow = current_x +
unit_width - box.x2`、以及回吸逻辑 `_hang_retreat` 保存的 `current_x`。给它加轴
参数是对上游装箱器的实质重写。

存在一条**不动该函数**的绕行:以转置盒(宽高互换)调用它,再把产出的字符盒作坐标
旋转并置 `vertical=True`。这条路看上去与 (c) 的固定矩阵自洽,**但本会话未验证它
与悬挂标点账、drop_cap、`column_reflow`、`typeset_hang` 的记账如何复合** ——
那几处都按 x 读盒。**故 (b) 记为"已读,未裁定"**,不记为可行,也不记为不可行。
把一条未验证的绕行写成"可行"会让 4b 分支在没有证据的情况下被实现。

---

## 6. 建议的处置

按 §5.14,批内修正案(`PLAN_B11_7_REV2`)是合法续作,三条件本报告已备其一:
(a) 修正由一次对当前树的实测触发,实测表即本报告 §1–§3 与
`premise_check.json`。余下两条(原件留档标注作废、只收窄或重指不放宽)由修正案
自己履行。

请用户裁决的点,按影响面排序:

1. **T3.1 的重指**。检测由"段级带下闸"改为"页级零容忍"是**阈值语义的变更**,
   §5.14(c) 不许机器为使预期数字成立而动旋钮。要么由用户在修正案里明写这次改的
   是判据而非旋钮及其理由,要么 T3.1 收窄为"canvas 化数据源"(此时它关不掉任何
   一处,须同时改写 T3 的验收基准)。
2. **碎裂的处置**。p3 / p5 / p6 三行各碎为两段,是 T3.2 与 T3.3 共同的前置。是先
   合段(fragment_stitch 一族已有机制)再施规则,还是让规则跨段成对,两条路的作
   用面差别很大,且都不在现计划里。
3. **T3.3 的作用面**。触发条件在活语料上七段全中而非一处,消费者清单须按此规模
   做。§4.18 的绝对项(携带 `pdf_form` / `pdf_curve` 的 composition 一律不改判)
   在本报告里**尚未计数** —— 计数属清单工作,待修正案确认作用面后再做。
4. **T3.4 的 (b)**。转置盒绕行是否属"旋转写回车道"的允许实现,或该走 4c 分支登记
   gap 交裁决。

T1、T2、T4 的前提全部成立,可原样保留。

---

## 7. 本会话产物

- `examples/output/b11_7/scripts/premise_check_b11_7.py` —— 六条前提的复算脚本
- `examples/output/b11_7/premise_check.json` —— 复算结果,`verdict: STOP`
- `examples/output/b11_7/premise_difference.report.md` —— 本文件

代码、配置、门禁、prompt 一律未改。未跑样张,未发起 API 调用(§3 引用的那一次调
用是 b11.6 运行时发生的,记在其冻结 sidecar 里)。
