# B14 — 首字锚定、栏尾实测与治理、报头漏译 + 两份冷跑样本 交付报告

分支 `migration/minimal-v0.6.4`,基于 `5e967fb`,任务提交
`158d240`(T1)· `e4d2442`(T1 补)· `ef407cd`(T2a)· `19c3439`(T2b)·
`b4dc00c`(T2c)· `5fc5c93`(T3)· `ab88f37`/`df78ed3`(门禁适配),tag `b14`。
验证样本:重跑 Courier-en 与 FD-en-v2(受影响样本,工件在
`examples/output/B14/T3/`,其后两个提交只动 `tools/` 门禁、不触管线,
故 T3 工件即最终管线状态);冷跑 CERNCourier-en(en→zh)与
HuaweiTech-zh(zh→en)(`examples/output/B14/T4/`),两份均为从未运行过的
样本,版式族与已测样本不同,一 en 一 zh。

## T1 首字装置锚定到源墨迹 → 已修

锚定改为:用 pymupdf 字形墨迹度量计算源首字墨迹顶相对其度量框的
偏移,渲染锚点下移该偏移,首行网格随锚点走;度量不可得走
`anchor_fallback_metric_box`,fail-open。

**改后实测**(`B14/T3/Courier-en/.../drop_cap_render.report.json`,
`anchor` 字段):三个首字位移 `shift_pt` = 18.6024 / 17.8692 / 18.5665,
与 P1 像素实测的上浮量(p4 浮 18.5pt、p5 浮 17.75pt)吻合,
`fallback: null`,三个全部 committed、零回滚。FD 一个首字同机制,
`shift_pt` = 2.303,committed。颜色守卫:代码内无颜色分量字面量,
三个首字 `source_color.fill` 携带 `resolve:` 证据链(沿 B13)。

**图**:`courier-p4-dropcap-source.png` / `-b13.png`(浮起)/
`-b14.png`(对齐);`fd-p8-dropcap-source/-b13/-b14.png`。

**门禁**:`tools/spec_check_b14_t1.py` 通过(合成字体夹具 ≤0.5pt 正向、
度量不可得 fallback 反向、实样 ≤1pt 像素断言)。

## T2 栏尾:实测指标 → 链覆盖 → 切点保真 + 微再平衡

**T2a 排版后指标**:新增 `tail_fill.report.json`——对每个链切口与跨栏/
跨页接续边界测最终渲染末行的充满率、字符数、终结标点。B14 起栏尾
改进只引用此指标,`cuts_by_reason` 降级为过程信息。

**T2b 链覆盖**:按 strata 重建栏系统,内嵌盒多栏序列可成链
(`19c3439`);Courier 链数 11 → **13**(B13 → B14,
`chain_report.json`),p4 LINKS 内嵌盒跨栏接续("家、"2 字挂尾)
被覆盖(图 `courier-p4-links-source/-b13/-b14.png`)。FD 3 → 3(不变,
该刊无新增可配对)。无任何按样本/按页特判。

**T2c 切点与兜底**:切点改在全尺寸网格上选(`measurement_scale`
仍记录,期望值按 `(measurement_font_size/measurement_scale)*cut_scale`
还原);排版后微再平衡对 ≤`tail_min_chars`(3)且非终结标点的挂尾
并入接续成员,复用 `verify_redistribution` 守恒。

**四样本末行充满率分布**(`tail_fill.report.json` summary):

| 样本 | 边界数 | 中位 | p25 | min | 满行占比 | 1-2 字挂尾 | 再平衡 |
|---|---|---|---|---|---|---|---|
| Courier-en | 18(栏 16/页 2) | 0.885 | 0.783 | 0.121 | 0.556 | 2(见下) | 3 applied |
| FD-en-v2 | 3(栏) | 0.963 | 0.931 | 0.900 | 1.0 | 0 | 0 |
| CERNCourier-en | 3(栏) | 0.719 | 0.564 | 0.409 | 0.0 | 0 | 0 |
| HuaweiTech-zh | 5(栏) | 0.639 | 0.577 | 0.060 | 0.2 | 0 | 0 |

Courier 残余 2 条 2 字挂尾(p4#9→p4#10、p6#14→p6#5)**均以终结标点
收尾**,不满足再平衡准入(非终结标点),按规则保留;3 条非终结
标点挂尾(p4#20/21、p4#22/23、p8#7/1)全部并入接续成员。相对 B13
基线(p4 LINKS"家、"等挂尾)清单收缩,残余清单如上原样列出。

**门禁**:`spec_check_b14_t2.py` 四个 work 目录全过(S1 行与汇总
一致、S2 分布可复算、S3 挂尾逐条带文本、S4 再平衡逐条);
`spec_check_tail_aligned_backfill.py` 通过(E1 期望值按还原尺寸复算,
`ab88f37`)。

## T3 FD 报头漏译 → 已修

**T3a 入队排除溯源**:被字体样式分组吞掉的词级 run(职衔单元从未
入队的原因)在 `styles_and_formulas.py`/`il_translator.py` 侧修正
(`5fc5c93`),整类恢复入队,非按样本特判。

**T3b 错文种回显重试**:`babeldoc/magazine/echo_retry.py`,配置
`configs/echo_retry.json`(`echo_retry_max_chars` 80,range 10..200;
`echo_retry_budget` 40,range 0..120),开关 `magazine_echo_retry`。
回路准入未放宽,fallback_line 兜底维持。

**改后实测**(`translate_tracking.json`):FD 重跑 echo_retry
**18 accepted / 6 exhausted** / 1 over_max_chars / 1 not_wrong_script;
residue **21 → 8**,逐条归因:

| 页 | 摘录 | 归因 |
|---|---|---|
| p2/p3 | `BRIANSTAUFFER` ×2 | 插画署名,连写全大写,应保留类 |
| p4 | `PORTERGIFFORD,CHANTALJAHCHAN` | 摄影署名连写,应保留类 |
| p5 | `Subir Lall…Christoph Rosenb…`(编辑名单连排) | 人名列表单元超 `echo_retry_max_chars`,仍失败类 |
| p5 | `www.imf.org/fandd` | URL,应保留 |
| p5 | `电子邮件:publications@IMF.org` | 邮箱主体,应保留 |
| p8/p9 | `COURTESYKIMRUHL` / `COURTESYSWISSNATIONALBANK` | 供图署名连写,仍失败类(无空格致检测为单词) |

`EDITOR-IN-CHIEF`/`SENIOR EDITORS` 等职衔与 `Gita Bhatt` 类人名已译出
(图 `fd-p5-masthead-source/-b13/-b14.png`)。Courier 重跑 residue 5 条,
全部为 `©`/`照片:` 摄影署名(应保留类),echo_retry 1 accepted。

**门禁**:`tests/minimal/test_echo_retry.py`(人名回显重试正向、
目标语单元回显维持原样反向等 130 行)通过。

## T4 防过拟合:两份冷跑

两份新样本 HITL 两段裁决按授权由 Claude Code 代批,走正常人工路径,
决议落 `reviews/CERNCourier-en.decisions.json` /
`reviews/HuaweiTech-zh.decisions.json` 与审计。

**CERNCourier-en(en→zh)**:`minimal_run.report.json` status complete。
翻译 213 单元级 echo 判定:2 accepted / 19 exhausted / 6 not_wrong_script /
4 over_max_chars / 1 reply_unusable。首字:0 个 intent(该刊无首字)。
回路 termination:5 项 decision 全部 no_op、0 acceptances、0 影响元素
(无接受修复,故无 PNG 证据项)。residue 20 条已逐条落
`_cold_run_findings.md`。

**HuaweiTech-zh(zh→en)**:status complete,translator_cache 88/88
(本次续跑全部命中中断跑的缓存,**API 增量成本为零**)。residue 3 条
(p2 目录页:装饰单字"目""录"+ 作者名"范济安")。首字:2 个 intent
均回滚(`glyph_metrics_unavailable` 1、`post_render_coverage_failed` 1),
回滚即维持原版式,fail-open 符合设计。回路 3 项 decision 全部 no_op。

**新样本暴露的新问题(只记录不修,修复面冻结在 T1–T3 通用规则)**:
见 `docs/reports/B14/_cold_run_findings.md`,要点——CERN 印刷厂 slug
(`.indd` 行)出现交错重复且被部分翻译;CERN p2 报头字距拉开的
`V o l u m e 6 6…` 单元被逐段混译;两份冷跑链数均为 0(接续边界全部
unchained,链构建对这两个版式族未命中);HuaweiTech 首字两类回滚
原因;zh→en 方向 echo_retry 8 条候选全部 `not_wrong_script`(准入门
对 zh→en 人名残留不生效,如"范济安")。

**中断说明**:上一会话 HuaweiTech 冷跑曾报 `debug_info` 属性错误;
本会话在 HEAD `df78ed3` 原样重跑(同命令、同 work 目录),全程无异常
跑通,该错误不再复现(推断死于中断会话内后续已落的提交,无栈可抓;
如再现,以完整 traceback 为准另立任务)。

## 门禁总览

- `tests/minimal`:**9 failed / 368 passed**,失败名与基线九项
  **逐名一致**(`test_chain_single_request` 5、`test_detectors` 2、
  `test_drop_cap_keep_flatten` 1、`test_structure_real_pdf` 1),零回归。
- `tools/spec_check_*`:除 `spec_check_expectations_scope.py`
  (基线即失败,3/5 夹具,未触碰)外全部通过;`spec_check_b14_t1`、
  `spec_check_b14_t2`(四样本)、`spec_check_tail_aligned_backfill`、
  `spec_check_demo_verifier_scope`(drop-cap schema 兼容 B14 前工件,
  `ab88f37`)均绿。
- 红线:锚移不改字符集(T1)、再平衡过 `verify_redistribution`(T2c)、
  T3 只改文本不改框;config 单源带 range;无出版物/页码字面量入逻辑。
