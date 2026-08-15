# 拼接点判官协议(M10,batch-e2.2)

指标合同 D2 把 M10 记作 "GEMBA-MQM 拼接点标注",并留下两处待定:判官模型待用户决策
(GAP-03),协议本身"标注单位是拼接点而不是文档"只有一句话。本文件把协议写死:**测试点
怎么选、材料怎么切、答案怎么约束、判官怎么钉版、结果怎么复现**。实现是
`tools/splice_judge.py`,prompt 是 `prompts/splice_judge_mqm.md`,有界参数在
`configs/splice_judge.json`,结果在 `docs/eval/results_e2/splice_judgements.json` 与同名 `.md`。

---

## 1. 拼接点与测试点集

**拼接点**是读者一次动作跨过的页边界:被离开那一页的最后一段正文与被进入那一页的第一段
正文,读者按顺序读成**一段话**,被判的就是这段话。

测试点集 = `corpus/chain_labels.user.json` 中**全部 `link: true` 的正样本**,即裁定单认定
"语义单元被切断且续接就在下一页"的边界,共 **5** 条:

| # | 样张 | 边界 | 裁定单原话(节录) |
| --- | --- | --- | --- |
| 1 | `AramcoWorld-en-v2.pdf` | `6->7` | MID-SENTENCE SPLIT #2,issue p34->p35 |
| 2 | `Courier-en.pdf` | `2->3` | DISPLAY-TITLE SPLIT,跨页的一句展示标题 |
| 3 | `Courier-en.pdf` | `7->8` | MID-SENTENCE BODY SPLIT,issue pp.12-13 |
| 4 | `Courier-zh.pdf` | `2->3` | DISPLAY-TITLE SPLIT (zh) |
| 5 | `Courier-zh.pdf` | `7->8` | MID-WORD SPLIT (official),官方版同址 |

点集由裁定单现场读出、不在代码里另抄一份;`link: false` 的 30 条不进本次运行(见 §6.1)。

## 2. 臂:每个测试点跑哪些配置

臂是**该样张现存的冻结产物**,在 `tools/splice_judge.py` 中声明而非发现——一份"扫到什么算
什么"的报告会在两次 sweep 之间改变含义。

| 臂 | 产物(样张名与臂名代入下列目录) | 读法 |
| --- | --- | --- |
| `upstream` | `examples/baseline/pdf/` 下逐样张一个目录,取其 mono PDF | PDF 抽取(PyMuPDF → 最小 IL) |
| `chain_off_1` / `chain_off_2` / `chain_on` | `examples/output/e2/r1/` 下逐臂 work 目录 | IL,`checkpoint.11_typesetting` |
| `fork_full` | `examples/output/b8_4/smoke/` 下逐样张 work 目录 | 同上 |

具体路径逐行写在 `docs/eval/results_e2/splice_judgements.json` 的 `origin` 字段,不必从上表推。

规则:**跑过 R1 三跑的样张用三臂,其余样张用 fork 全栈那一跑**。Courier-en 的 `chain_on`
与它的 b8.4 全栈跑是同一个配置(冻结重放,54 次翻译请求 54 次命中缓存,台账 A-21),两者
并列会把一个配置在表里列两次,故只列前者。

由此得到 **5 个测试点 / 14 行**:Courier-en 两点各 4 臂,其余三点各 2 臂。
PLAN_E2 的 R2 预算是 ≤ 70 次判官请求,实际用 14 次。

`Courier-en 7->8` 的三方(`upstream` / `chain_off_1` / `chain_on`)就是计划要的三方对照,
`chain_off_2` 作稳健性副臂:它与 `chain_off_1` 是同一配置的两次独立采样(W-E2-01),
两臂标注不同的地方是判官或译文的抽样方差,不是开关效应。

## 2a. 有效集:哪些行真的测到了被裁定的切断(裁决后追加)

人工裁决(§7)发现窗口选取有一处结构缺陷:tail/head 取的是**该页阅读序的几何端点**,
而展示标题切断被裁定的那对单元是两个 display 段落。两个 `2->3` 点(Courier-en 与 Courier-zh)
的窗口因此拿到的是页尾图注与页首标题,**没有测到被裁定的那条切断**。缺陷登记为 GAP-14。

由此把 14 行分成两类,分法写进裁决文件、由门禁重算:

| 类 | 判据 | 行数 | 用途 |
| --- | --- | ---: | --- |
| **有效集** | 窗口对准被裁定的切断 | **8**(3 点) | 论文主证据;一致率的分母 |
| `PROTOCOL-INVALID` | 窗口未对准,`human_note` 以该标记起头 | **6**(2 点 × 各自全部臂) | 一律排除;其判词只作旁证,不作拼接结论 |

**论文主证据 = `Courier-en 7->8` 四臂 + `AramcoWorld-en-v2 6->7` 两臂 + `Courier-zh 7->8` 两臂。**
判官与人工的一致率一律按有效集报告:**6/8**。

`PROTOCOL-INVALID` 是**逐点**的,不是逐行的:窗口选取是边界的性质,不是被测那一跑的性质,
所以一个点要么全部臂有效、要么全部臂无效(门禁断言这一点)。

## 3. 材料:三个窗口

每个点交给判官三段文本,别的什么都不给。

- **source**:跨边界的源文段落对,前半是被离开页的尾段、后半是被进入页的首段,各按
  `source_window_characters` 的一半截断。取自**翻译前最后一个 checkpoint**
  (`checkpoint.08_chain_builder`),因此与臂无关。
- **tail**:该臂译后文档中,被离开那一页的最后一个"端点候选"段落,按
  `tail_window_characters` **从尾部**截断。
- **head**:该臂译后文档中,被进入那一页的第一个端点候选段落,按
  `head_window_characters` **从头部**截断。

三条口径上的决定,每一条都能反过来:

1. **tail 的定义与 M1 共用。** 端点候选与阅读序取自 `chain_signals.page_candidates`,即
   `babeldoc/magazine/metrics/mid_break_rate.py` 取 tail 的同一口径(合同 §2b.2)。几何判决与
   语义标注因此谈的是**同一条边界**,双证表(台账 A-17、A-20)才能左右并读。页码条、竖排
   credit、图注这些版面家具不当 tail。
2. **文本从渲染行读,不从字符串层读。** 窗口由段落的渲染行拼成,因此不含翻译往返用的标记,
   也保留了实际断行——`p7#4` 那一行"以及一种复合材料。"是**排版后**的样子。
3. **source 窗口与臂无关,并且是被校验的而不是被假定的。** 凡带 IL 的臂都各自算一遍 source
   窗口,不一致即记 `material_faults` 并让运行以非零码退出。同一样张的各臂译的是同一份文档,
   source 窗口若因臂而异,材料就不是"同一个问题问了两遍"。

窗口只有一段而不是"两侧各若干段":一段是读者跨过边界时真正连读的单位,多给上下文会把
"这一处拼接坏没坏"稀释成"这一页译得好不好"。

## 4. 答案约束

判官必须回一个 JSON 对象:

```
{"reading": "<一句话>", "errors": [{"category": ..., "severity": ..., "window": ..., "span": ..., "explanation": ...}]}
```

- `category` ∈ `configs/splice_judge.json` 的 `mqm_categories`(12 个,MQM 主类/子类扁平命名);
- `severity` ∈ `mqm_severities`(`critical` / `major` / `minor`);
- `window` ∈ `source` / `tail` / `head`;
- `span` 必须是从窗口里**逐字抄下**的原文;
- 错误条数 ≤ `max_errors`(5);空列表是完整答案,优于编造。

**越界即违规**,不是新类别:词表不因模型返回了什么而变宽。一次违规带着违规原因重问一次
(复用 `prompts/vlm_retry_notice.md`,其措辞不涉及模态),第二次仍违规即把该行记为
`judge_refused` 并保留原始回复与拒因,不硬凑。

**判官输出不作任何后处理修饰**:`reply` 字段逐字节保存判官返回的字符串,解析结果与它并列。
唯一的容忍是把整包答案外面的一层代码围栏剥掉——与 `babeldoc/magazine/vlm_client.py` 的
`unfence` 同一处理,不改动答案内容,且 `reply` 里那层围栏仍在。

## 5. 判官钉版与缓存

| 项 | 取值 | 进 cache key |
| --- | --- | --- |
| 模型 | `gpt-5.6-terra` | 是 |
| `token_parameter` | `max_completion_tokens` | 是 |
| `temperature` | `null`(不发该字段,用服务端默认) | 是 |
| `max_output_tokens` | 1024 | 是 |
| prompt 文件哈希 | `prompts/splice_judge_mqm.md` 的 SHA-256 | 是 |
| 渲染后 prompt 哈希 | 含全部三个窗口与两个词表 | 是 |
| `base_url` / `api_key_env` / `timeout_seconds` / `max_retries` | 见配置 | 否 |

**每一行结果都带 `judge_model` 与 `judge_transport`**,因此一行数字永远知道自己是谁在什么
参数下答的。缓存落在项目本地 `examples/cache/cache.v1.db`,引擎名 `magazine_splice_judge`,
`CACHE_KEY_VERSION = 1`。

**判官选型是异族判官(GAP-03 的方案 a)**:被测译文由 `gpt-4o` 产出,判官取 `gpt-5.6-terra`,
与被测非同族,故"判官偏向自身输出"这一系统性风险不适用。代价按 GAP-03 原文承担:判官本身
的质量须另行说明——那就是 §7 的人工抽验。

两处实现落点的说明,免得读者去别处找:

- **客户端落在 `tools/` 而不是 `babeldoc/magazine/`。** 判官是评估器具,不是流水线的一环:
  它不在任何 stage 里被调用,只读冻结产物。CLAUDE.md §3 把 `tools/` 定为独立脚本的位置,
  PLAN_E2 的批次白名单也不含 `babeldoc/`。它遵循的仍是 B3 立的那套缓存客户端规矩(自己的
  引擎名、prompt 文件哈希进 key、有界重试、闭词表),与 `magazine/article_context.py` 的
  `CachedBriefClient` 是同一种复用方式。
- **prompt 哈希记在结果表里,不记在 working_dir 清单里。** CLAUDE.md §4.3 要求 prompt loader
  把所加载文件的 SHA-256 记进 working_dir 的运行清单;判官没有 working_dir,故 `load_prompt`
  不带该参数,哈希改为**逐行**写进 `splice_judgements.json`(`prompt_file_sha256`),门禁断言
  它等于树内 prompt 文件的现值。逐行比清单更严,不更松。

**零成本复现**:`python tools/splice_judge.py --out docs/eval/results_e2 --offline` 完全不建
transport;任一点没有可用缓存即以错误中止,而不是重新发问。因此门禁重放出来的报告就是付费
那一跑产出的报告,逐字节相同。为此结果表里**不含任何缓存来源字段**(`from_cache`、
`attempts` 都不进表);成本另写 `examples/output/e2/r2/judge_cost.json`。

## 6. 与 GEMBA-MQM 原文的偏离,以及本协议的已知局限

### 6.1 偏离(kocmi2023gemba_mqm)

| # | 原文 | 本协议 | 理由 |
| --- | --- | --- | --- |
| 1 | 三样例 few-shot | **零样例** | 样例会给出"应该找到几个错误"的先验;5 个正样本的点集经不起这种先验 |
| 2 | 标注单位是一个句段(source/target 两段) | 标注单位是**拼接点**,材料三段 | M10 要问的是"拼接是否引入了错误",不是"这段译得如何" |
| 3 | 错误按权重合成一个 MQM 分数 | **不合成分数**,只报逐点错误表与类别计数 | 5 条正样本不支撑比率型主张(GAP-12),分数会把定性显微镜读成统计量 |
| 4 | 严重度含 `neutral` | 只有 `critical` / `major` / `minor` | `neutral` 在本协议里与"不报"不可分辨 |
| 5 | prompt 声明源语言与目标语言 | **不声明** | 没有任何冻结产物记录某一跑的 `lang_in`/`lang_out`;材料本身自明,与其在 prompt 里断言一个查不到出处的事实,不如不说 |

### 6.2 局限(一律不得在论文里被读强)

1. **只有正样本,本次不跑负控。** 点集是裁定单的 5 条 link,没有 `link: false` 的对照,
   因此判官"在拼接点找到错误"这一事实**不能**换算成"该判官能分辨好坏拼接"。要那个主张
   须另跑 30 条负边界(预算内:14 + 60 ≤ 70),本会话不跑。
2. **`Courier-zh` 的 fork 臂与 upstream 臂方向不同,不是对照。** 上游基线那一跑是 zh→en
   (产物 `Courier-zh.no_watermark.en.mono.pdf`),而 b8.4 全栈那一跑对该样张走的是 en→zh
   配置,落在中文文档上等于没译:135 段中 45 段与源文逐字相同,其余差异只是标点与空白
   规范化。该臂的标注**是关于那份产物的**(它确实携带未翻译文本),不能读作"fork 在
   zh→en 上如此"。zh 校准是 PLAN_E2 明确不做的事。
3. **两条读数路径不同源。** `upstream` 臂的窗口来自 PDF 抽取,fork 各臂来自 IL;台账 G-07
   记了这两条路径的元素划分不同(文本块数比 IL 段落数 1.00–1.72)。对**几何比率**这意味着
   不可比;对**窗口文本**影响小得多(抽取的是同一批字符),但一处 tail 选取的分歧就能换掉
   整个窗口,故 upstream 与 fork 的逐点比较须连同各自的 `origin` 一起引。
4. **判官本身是被采样的。** 本协议不作重复采样(同一 prompt 问 N 次),因为缓存钉版的意义
   正是"一个答案一次落盘";判官的可靠性由 §7 的人工抽验回答,而不是由自洽性回答。
5. **5 个点、14 行,是显微镜不是统计量。** 任何"某臂错误更多"的说法都只能作存在性论证。

## 7. 人工抽验(GAP-03 的第二半)

判官协议自带一层人工:`tools/splice_judge.py` 同时导出
`docs/eval/results_e2/splice_manual_review.json` 与同名 `.md`。

- **选点规则**(写进工具,不是一张手挑的名单):**全部点 × 全部臂**,即 **14 行 / 14 行 =
  100%**,远高于 GAP-03 建议的 20%。语料主人在本批次裁定取全覆盖而非抽样:这个规模下人工
  代价可承受,而全覆盖同时消掉了"被抽中的会不会正好是好看的那几行"这个问题。
- **格式与 HITL 同族**:机器导出一份带空位的清单(`*.review.json` 的角色),人工填好的那份
  即裁决文件(`*.decisions.json` 的角色)。每条给出三个窗口、判官的 `reading` 与逐条错误,
  留三个空位:`human_agrees`(true/false)、`human_errors`(不同意时按同两个词表写出你的
  标注)、`human_note`(自由文本)。
- **纪律**:机器会话只出清单、不填清单。清单一旦被填(任一 `human_*` 字段非 null),
  `tools/splice_judge.py` 就**不再覆写它**(`is_ruled`),与 HITL 的 decisions 文件同一条
  规矩:机器写草稿、读裁决,反过来不行。清单里的判官标注**原样**呈现,不作任何修饰或排序。
- **裁决已入库**(batch-e2.2 会话二后半):14 行全部作答,6 行标 `PROTOCOL-INVALID`,
  有效集 8 行上一致 **6/8**。裁决的判定口径由裁决文件自己声明并被门禁重算:
  `human_agrees` 只对**拼接归因**的错误作答,窗口内顺带看到的非拼接词汇问题写进
  `human_note` 而不计入。两处不一致各有名字:一处高估(把非拼接错误按 critical 计入拼接,
  GAP-16),一处漏报(未标语言不符与边界字符重复,GAP-15、GAP-17)。裁决另开 GAP-14~GAP-18。

## 8. 复现

```
# 付费那一跑(缓存为空时)
python tools/splice_judge.py --out docs/eval/results_e2

# 零成本重放:不建 transport,缺缓存即中止
python tools/splice_judge.py --out docs/eval/results_e2 --offline
```

门禁 `spec_checks/spec_check_e2.py` 的断言 10–12 复跑第二条命令并逐字节比对,同时全谱校验
每一行的类别、严重度、窗口名与钉版字段。
