# batch-e2 结果:R1 三跑与链 A/B(会话一)、M10 拼接点判官(会话二)

本目录是 E2 两个会话的全部产物。与 `results_e1/` 不同,这里的数字来自**实跑**——
本批次是评估阶段唯一花钱的地方,R1 三跑与 R2 判官 14 次之外零 API。

§1–§7 是会话一(batch-e2.1),§8 起是会话二(batch-e2.2)。

## 1. 文件清单

| 文件 | 内容 | 生成命令 |
| --- | --- | --- |
| `drift_attribution.json` / `.md` | 三跑逐段归因表(A-12 集 15 段 + 全变更集 59 段)、前提校验、成本台账 | `python tools/drift_attribution.py --out docs/eval/results_e2` |
| `eval_report.Courier-en.json` / `.md` | 三臂 × 两条几何路径的全指标(M1 分层、M2、M3、几何组) | 见 §4 |
| `splice_judgements.json` / `.md` | M10 判官逐点标注表(5 点 × 14 行),含三个窗口、原始回复与钉版字段 | `python tools/splice_judge.py --out docs/eval/results_e2` |
| `splice_manual_review.json` / `.md` | 人工抽验清单(14/14 行,空位待裁决) | 同上 |

`eval_report.Courier-en.*` 与 `results_e1/` 下的同名文件**不是同一张表**:E1 的三列是
`upstream / fork_full_il / fork_full_pdf`(三个配置),本目录的六列是
`chain_off_1 / chain_off_2 / chain_on`(三个臂)各走 IL 与 PDF 两条路径。

大件(三份译后 PDF、三个 working_dir 的 checkpoint 与 prompt trace)按 E1 保留策略留在
工作区 `examples/output/e2/r1/`,不入库;三份 PDF 的 sha256 逐份写在
`drift_attribution.json` 的 `runs` 数组里,`spec_checks/spec_check_e2.py` 以显式
"路径 + sha256"清单断言其存续。

## 2. 三跑设计,与它为什么不是 `ignore_cache`

三个臂共用 batch-b8.4 的全栈配置,逐字不改,只差一个开关:

| 臂 | `magazine_chain_translate` | 缓存命名空间 | 角色 |
| --- | --- | --- | --- |
| `chain_on` | true | 共享(与 b8.4 同键) | 冻结重放,给出被测取值 |
| `chain_off_1` | false | `e2_r1_arm=off1` | 独立采样,A/B 的参照臂 |
| `chain_off_2` | false | `e2_r1_arm=off2` | 独立采样,给出重复噪声 |

PLAN_E2 把两个 off 臂写作 `ignore_cache`。`ignore_cache` 确实能让第二臂读不到第一臂的
答案,但它**同时**关掉写入,而一次没有落盘的付费运行是本项目的评估协议(冻结重放)唯一
不允许的东西。改用**每臂一个 cache impact 参数**同时满足两头:两臂的 cache key 不同
(`1c23e53b…` 对 `ea01c25b…`,对照 on 臂的 `01466162…`),因此谁也服务不了谁;而
`add_cache_impact_parameters` 只进 cache key、不进线上请求,两臂发出的 prompt 逐字节相同;
两臂的答案都已落盘,可零成本重放。偏离登记为 W-E2-01。

## 3. 成本实录

| 臂 | 壁钟 s | translate 请求 | 缓存命中 | API 调用 | prompt tokens | completion tokens | 新落盘行 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `chain_on` | 64.9 | 54 | 53 | 1 | 1 734 | 93 | `magazine_repair` 1 |
| `chain_off_1` | 93.8 | 62 | 0 | 62 | 52 312 | 11 377 | `openai` 58, `magazine_orphan` 3, `magazine_repair` 1 |
| `chain_off_2` | 86.3 | 61 | 0 | 61 | 51 713 | 11 231 | `openai` 58, `magazine_orphan` 2, `magazine_repair` 1 |
| **合计** | **245.0** | **177** | **53** | **124** | **105 759** | **22 701** | — |

GAP-01 的估算是"两臂各 45 次上行、合计约 90 次调用、5~6 万 prompt tokens、约 13 分钟"。
实测 124 次调用、105 759 prompt tokens、4.1 分钟。调用数高出估算约四成、token 数接近估算
上限的两倍,原因有二:估算依据的是 b5.3 的精简配置(该臂 45 请求)而三跑跑的是全栈配置
(62 请求),且估算假设两臂各只有 14 次上行(共享缓存下的增量),而独立采样要求两臂**全部**
请求都上行。壁钟反而远低于估算(4.1 分钟对约 13 分钟),因为估算取的是 b5.3 的冷跑耗时,
而本次的版面解析走的是已预热的 ONNX 模型。

`chain_on` 的那 1 次调用**不是翻译**:它是 ReAct 决策请求,答案落在 `magazine_repair`
命名空间,`openai` 命名空间零新增行——即 54 次翻译请求 54 次全部由缓存服务。该决策请求在
b8.4 那一跑同样未命中(两跑各 1 次),两次落下的键不同,说明决策 prompt 在两跑之间不逐字节
相同;它改变的东西是零(`applications: 0`、`verdict: conserved`、132 段零变),原因未查,
记为遗留问题。

## 4. 链 A/B 全指标

```
python tools/eval_report.py \
  --run chain_off_1=examples/output/e2/r1/chain_off_1/work/Courier-en \
  --run chain_off_2=examples/output/e2/r1/chain_off_2/work/Courier-en \
  --run chain_on=examples/output/e2/r1/chain_on/work/Courier-en \
  --pdf chain_off_1_pdf=examples/input/Courier-en.pdf:examples/output/e2/r1/Courier-en.chain_off_1.pdf \
  --pdf chain_off_2_pdf=examples/input/Courier-en.pdf:examples/output/e2/r1/Courier-en.chain_off_2.pdf \
  --pdf chain_on_pdf=examples/input/Courier-en.pdf:examples/output/e2/r1/Courier-en.chain_on.pdf \
  --sample Courier-en.pdf --out docs/eval/results_e2
```

| 臂 | 路径 | MBR linkable | MBR all | inherited open | conserved | LTCR | legacy share | Overlap delta | Alignment delta | image IoU | page delta |
| --- | --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `chain_off_1` | IL | 0.4000 | 0.5714 | 2 | yes | 0.4821 | 0.7667 | 0.0000 | 0.0000 | 1.0000 | 0 |
| `chain_off_2` | IL | 0.4000 | 0.5714 | 2 | yes | 0.4286 | 0.7000 | 0.0000 | 0.0000 | 1.0000 | 0 |
| `chain_on` | IL | 0.4000 | 0.5714 | 2 | yes | 0.4464 | 0.7000 | 0.0000 | 0.0000 | 1.0000 | 0 |
| `chain_off_1` | PDF | 0.2000 | 0.4286 | 2 | yes | – | – | −0.0410 | 0.0033 | 1.0000 | 0 |
| `chain_off_2` | PDF | 0.2000 | 0.4286 | 2 | yes | – | – | −0.0406 | 0.0034 | 1.0000 | 0 |
| `chain_on` | PDF | 0.2000 | 0.4286 | 2 | yes | – | – | −0.0410 | 0.0034 | 1.0000 | 0 |

四条读法,均按实测写:

1. **M1 在链 A/B 上零判别力。** 三臂七条边界的逐边界判决**逐条相同**,两条路径各自内部
   也相同;`mbr_linkable` 三臂同为 0.4000(IL)/0.2000(PDF)。合同 §2c.4 此前只证到
   "上游与 fork 在 `7->8` 上都 closed",现在证到**同一 fork 的开关两态也都 closed**——
   M1 连这个 A/B 都分不开。
2. **M2 守恒三臂全 hold。** 页数 8→8、段落 132→132、`changed_outside_touched` 空。两个
   off 臂没有 `chain_translation.report.json`,链级那一层记 `absent` 而不是 0——开关是关的,
   没有链可守恒,与"守恒失败"是两件事。
3. **M3 (LTCR) 的臂间差落在噪声里。** 0.482143 / 0.428571 / 0.446429:**两个 off 臂之差
   (0.0536) 比 off₁ 与 on 之差(0.0357)和 off₂ 与 on 之差(0.0179)都大**。三臂的合格
   词条数都是 **3**,这个分母不足以分辨开关的两态(见 `results_e1/README.md` §6 的同一条
   判断)。
4. **几何组三臂几乎不动。** IL 路径的 Overlap/Alignment delta 三臂皆 0.0000(合同 §2c.3
   的结构性零),PDF 路径 `overlap_delta` 三臂在 −0.0406~−0.0410、`image_placement_iou`
   三臂 1.0000、页数差三臂 0。即链级联合翻译**没有移动版面**,这与台账 A-10/A-11 的零外溢
   结论一致,现在多了一个独立 off 臂作对照。

## 5. `7->8` 的双证伴表(论文表 X-1 的指标级伴表)

裁定单记 `7->8` 为 MID-SENTENCE BODY SPLIT(`a composite material from` → `the grass has
been patented`)。左半是 M1 的几何判决,右半是 A-09 的语义证据,两半在三臂上并列。M1 在三臂
上取的 tail 都是同一段 `p7#4`(`plain text`,非竖排),因此三列可直接并读:

| 臂 | M1 判决 | 末字符 | 页 7 末渲染行 | 页 8 首译文(首 18 字) | 语义 |
| --- | --- | --- | --- | --- | --- |
| `chain_off_1` | **closed** | `。` | `医用凝胶，以及一种复合材料。` | `这种草已经被申请了专利。根据协议…` | 悬空从句被**虚构收束**;专利句被切成两半 |
| `chain_off_2` | **closed** | `。` | `胶，以及一种复合材料。` | `这种草已经被申请了专利。根据协议…` | 同上 |
| `chain_on` | **closed** | `。` | `了专利。` | `根据协议,已经分享的利益包括…` | 真实句末;页 8 另起新句 |

三件事从这张表读出来:

1. **M1 三臂全 closed,零判别力**——几何量分不出"真收束"与"虚构收束"。台账 A-17 此前
   只在"上游 vs fork"上成立,现在在"fork 开关两态"上也成立,且这一次两侧是同一套排版代码,
   排除了"两条路径口径不同"这一解释。该边界的优劣**必须**引右半的语义证据。
2. **虚构收束不是采样噪声。** 两个独立 off 臂的 `p7#4` 整段并不相同(段中间有词级差异,
   归因表第 5 行记 `off1=off2` 为 no),但**收尾那一句逐字节相同**:两臂都以
   `以及一种复合材料。` 结束,`p8#8` 的开头两臂也逐字节相同
   (`这种草已经被申请了专利。`)。噪声动的是段中间,虚构收束不动。A-09 的这一半因此从
   "单跑观察"升为"两次独立采样复现"。
3. **A-09 的另一半没有复现,必须重述。** b5.3 记 `the grass` 被译为 `草地`(草坪,先行词
   丢失)。本次两个 off 臂都译作 `这种草`,是对的。先行词丢失的**误译**因此落在重复采样的
   方差之内,不得作为切断损害的确定性证据;**能作确定性证据的是虚构收束与专利句被切成两半**。

## 6. 归因结论(D3 GAP-01 关账)

三跑的前提先校验:三臂在翻译前的文档**逐段相同**(132 段、源文、`layout_label`、链成员位置
全等),两个 off 臂的**批次组成逐段相同**——它们问的是同一批问题,答的是两次独立的样本。

- **配置内跑间方差**:132 段中 **43** 段在两个 off 臂之间就不同,即 **0.3258**。这是同一
  配置重跑一次的基线抖动,是一切单跑差异的解释上限。
- **重组面**:**27** 段落在被重组的批次里,分布在页 **2/3/7/8**——与 A-13 的机制逐页吻合
  (页 2 一批 6→5、页 3 由 2→1、页 7 `[2,2,2,3,6]`→`[2,2,4,6]`、页 8 `[2,2,2,3,6]`→
  `[1,2,2,3,6]`)。
- **A-12 集**:既变更**又**落在重组批次里的段落恰为 **15** 段,其中 **4** 段是链成员、
  **11** 段是邻段——与 A-12 的 "15 段变(4 成员 + 11 邻段)" **逐数吻合**。这不是巧合:
  b5.3 的共享缓存设计下,批次未动的段落按构造相同,能被它看见的**只有**这 15 段。
- **11 段邻段的归属**:**8 段**归重组(两次独立采样一致,且批次确实动了),**3 段**与重复
  采样不可分辨(两次独立采样本身就不同)。

GAP-01 因此关账:重组效应在本样张上**存在且可定位**(8 段),不是全部噪声;但它也不是
全部机制——11 段里有 3 段落在噪声内。A-12 的状态由"需三跑"改为"直接可引"。

## 7. 本次运行发现的两处已知局限

1. **自动术语抽取本身是被采样的。** 抽取器走引擎,因此每臂抽出自己的词表:**36** 个批次里
   有 **10 个**(涉及 42 段)在两个 off 臂之间 prompt 不同而**批次成员完全相同**,差异全在
   glossary 块(例如 `LINKS → LINKS` 一行在 off₁ 在场、off₂ 缺席)。**所以 prompt 字节不等
   不能当作重组的判据**,归因表用的是批次成员是否移动,那个量对词表抖动免疫。这条此前无人
   记录,进台账 G-09。
2. **on 臂是另一场合的样本。** 冻结重放让 on 臂的答案取自 b8.4 那一次采样,因此
   "off₁=off₂≠on 即重组"这条 GAP-01 原文规则会把 **19** 段判成重组,其中 **11** 段的批次
   根本没动——它们只是第三次抽样。归因表两列并列:`gap01` 列可由三列译文复算(门禁断言),
   `verdict` 列加上批次证据后把这 11 段记为 `run_variance`。论文引用后者。

---

## 8. M10 拼接点判官(会话二,R2)

协议写在 `docs/eval/splice_protocol.md`,不在这里重复。运行事实:

| 项 | 实测 |
| --- | --- |
| 测试点 | 5(裁定单全部 `link: true` 正样本) |
| 行数 | 14(Courier-en 两点各 4 臂,其余三点各 2 臂) |
| 判官 | `gpt-5.6-terra`,`max_completion_tokens=1024`,不发 `temperature` |
| 拒答 | **0**(`judge_refused` 零行) |
| 请求 | **14** 次,对应 **13** 个不同 prompt |
| tokens | 16 256 prompt / 6 806 completion |
| 零成本重放 | `--offline` 14/14 命中缓存、0 请求,两份 JSON 逐字节相同 |

两处需要解释的数:**14 请求对 13 个 prompt**,因为 `Courier-en 2->3` 的两个 off 臂窗口
**逐字节相同**,同一个 cache key 服务了两行——缓存键由渲染后 prompt 组成,这是它应有的样子;
多出的那一次是某一行的**首次尝试未产出可用回复**(校验未过或请求本身失败,两者在本跑之后
已不可分辨),有界重试后通过——13 个 key 全部落盘,首次那份没有。哪一行重试,报告里查不到:结果表刻意不带 `attempts` 与 `from_cache`,否则
付费那一跑与重放跑的字节就不相同了。该列已加进成本文件
(`examples/output/e2/r2/judge_cost.json`),但那是在这一跑之后加的,对本跑只有总数。

### 8a. 逐点逐臂

| 点 | 臂 | 错误数 | 类别(严重度) |
| --- | --- | ---: | --- |
| AramcoWorld-en-v2 `6->7` | `upstream` | 2 | `accuracy/omission` (major)、`accuracy/mistranslation` (major) |
| | `fork_full` | 0 | — |
| Courier-en `2->3` | `upstream` | 1 | `accuracy/omission` (minor) |
| | `chain_off_1` | 0 | — |
| | `chain_off_2` | 0 | — |
| | `chain_on` | 1 | `accuracy/addition` (minor) |
| Courier-en `7->8` | `upstream` | 1 | `accuracy/mistranslation` (**critical**) |
| | `chain_off_1` | 1 | `accuracy/mistranslation` (**critical**) |
| | `chain_off_2` | 1 | `accuracy/mistranslation` (**critical**) |
| | `chain_on` | 1 | `accuracy/mistranslation` (**critical**) |
| Courier-zh `2->3` | `upstream` | 1 | `accuracy/untranslated` (major) |
| | `fork_full` | 0 | — |
| Courier-zh `7->8` | `upstream` | 1 | `fluency/grammar` (major) |
| | `fork_full` | 0 | — |

合计 10 处错误;**上游臂 5 行全部非空**,fork 侧 9 行中 4 行非空。这句话只能这样读:它是
5 个点上的存在性观察,不是比率——点集只有正样本、没有负控(协议 §6.2.1),且判官只问了
一次。

### 8b. `7->8` 的三方 + 副臂:四行都是 critical,但错在不同地方

| 臂 | 判词落点 | span | 判官解释(节录) |
| --- | --- | --- | --- |
| `upstream` | head | `草地已经被申请了专利。` | 源文说的是由这种草制成的复合材料获得专利,译文说草地本身申请了专利,**由跨页处把未完短语断开后重启造成** |
| `chain_off_1` | head | `这种草已经被申请了专利。` | 同上,并把"已获专利"弱化为"申请" |
| `chain_off_2` | head | `这种草已经被申请了专利。` | 同上 |
| `chain_on` | **tail** | `并已为这种草的复合材料申请了专利。` | 复合材料的**专利状态**被写成"申请"而非"已获得";与边界无关 |

这张表补上了 GAP-13 与台账 A-09 的一个缺角。GAP-13 判定 `the grass`→`草地` 这一**词级**
误译落在采样方差内、不得再引;判官指出的却不是词而是**谓述**——专利被安在"草"上而不是
"由草制成的复合材料"上——而这一点在 `upstream`、`chain_off_1`、`chain_off_2` **三处独立
产物上同时出现**,在 `chain_on` 上不出现。方向与 GAP-13 重述后的两项确定性证据(虚构收束、
专利句被切成两半)一致,可作**第三项候选**。纪律:单判官、每行一次抽样,按 GAP-03 的方案 a
只作定性错误类型的提示,不作质量排序,更不作显著性主张。

`chain_on` 那一行还说明另一件事:它的 critical **不在拼接处**。开关打开后这条边界的语义
问题换了性质——从"跨页断开导致的先行词错误"变成"一处与边界无关的事实性误译"。

### 8c. 链臂不是一律更好

`Courier-en 2->3` 是本次运行里唯一一处 **fork 链臂独有的缺陷**:两个 off 臂零错误,
`chain_on` 的页 3 首行被排成 `动科学发现`,判官记 `accuracy/addition` (minor),span 就是
那个多出来的 `动`。链级联合翻译在这条展示标题边界上引入了一个 off 臂没有的字。

反过来,`AramcoWorld-en-v2 6->7` 是 M1 唯一独立成立的正例(台账 A-16:上游 open → fork
closed),判官在这一点上与几何判决**同向**:上游臂 2 处错误(其中 mistranslation 的 span
正是被切断的 `沿途大部分地区水` 与页首拼成的 `水哈兰以南的路线`),fork 臂零错误。这是
M1 的那一个正例第一次拿到语义侧的佐证。

### 8d. 两条必须随表引用的限定

1. **`Courier-zh` 的两臂不是对照。** 上游那一跑是 zh→en(产物
   `examples/baseline/pdf/Courier-zh/Courier-zh.no_watermark.en.mono.pdf`),而 b8.4 全栈
   那一跑对该样张走的是 en→zh 配置,落在中文文档上等于没译——135 段中 45 段与源文逐字
   相同,其余差异只是标点与空白规范化(本会话现场核对)。因此 `Courier-zh` 的 `fork_full`
   两行"零错误"**不是**"fork 更好",它是"那份产物没有被翻译"。这两行的价值在别处:
   `7->8` 的 fork 臂显示链级重排把官方版的词中切断 `协议中包` / `含惠益分享条款` 处理成了
   页 8 首行以 `包含` 起头,即重排确实动了那条边界。
2. **上游臂与 fork 臂的窗口来自两条读数路径**(PDF 抽取 vs IL,台账 G-07)。窗口文本受
   影响远小于几何比率,但 tail 选取的一处分歧就能换掉整个窗口,故逐点比较须连同各行的
   `origin` 一起引。

### 8e. 人工抽验清单

`splice_manual_review.json` 与 `.md`,**14/14 = 100%** 覆盖(语料主人在本批次裁定取全覆盖
而非 GAP-03 建议的 20% 抽样)。每行给出三个窗口、判官的 `reading` 与逐条错误,留
`human_agrees` / `human_errors` / `human_note` 三个空位。本会话**只出清单不填**;填好的
那份即裁决文件,判官与人工的一致率待其入库后按行统计。

## 9. C-04 的 terra 档:降级为声明

PLAN_E2 与 D3 GAP-10 写"`gpt-5.6-terra` 若要同口径需 18 次调用"。**该前提本会话现场核实
为不可执行**:那 18 个 routed page 属于 **v1 语料的 31 页**,其中 **8 页**(AramcoWorld-en 5、
FD-en 3)落在 batch-b7.5.1 换血时移出的 `AramcoWorld-en.pdf` 与 `FD-en.pdf` 上,两份 PDF
已不在 `examples/input/`。**不只是 terra 档,四档都不能再实跑重现那个分母。**

可验证的替代事实(本会话零 API 复核):四档的 policy 列由
`python tools/vlm_classify_eval.py --from-report ... --name vlm_policy_c04` 从冻结报告离线
重算,**二次运行逐字节相同**(9 716 bytes)。四档同源同口径——是离线重算,不是缓存重放。
台账 C-04 与 GAP-10 按此措辞收口,不新增 needs-recompute。

## 10. 会话二遗留

1. **判官侧无负控。** 30 条 `link: false` 边界未跑(预算内可跑:14 + 60 ≤ 70)。因此本次
   结果不支持"判官能分辨好坏拼接"这一主张,只支持"在这 5 条被裁定切断的边界上,判官报出
   了什么"。
2. **一次重试的归属查不到。** 见 §8 的解释;`attempts_by_row` 已进成本文件,下一次付费跑
   会带上。
3. **`Courier-zh` 的 fork 侧缺一份 zh→en 的真跑。** zh 校准是 PLAN_E2 明确不做的事,该样张
   的 fork 臂因此只能作产物观察,不能作方向对照。
