# B14 冷跑新样本问题清单(只记录,留待下批裁决)

来源:`examples/output/B14/T4/{CERNCourier-en,HuaweiTech-zh}/work/…/issues.after.json`、
`drop_cap_render.report.json`、`chain_report.json`、`translate_tracking.json`。
按 B14 红线,以下问题一律未修。

## CERNCourier-en(en→zh)residue 20 条逐条

| 页 | 段 | ratio | 摘录 | 初步归因 |
|---|---|---|---|---|
| p1 | p1#16 | 0.80 | `要订阅该杂志,请访问:https://cerncourier.com/p/about-cern-courier` | URL 主体,应保留 |
| p1 | p1#6 | 0.87 | `CCJulAug2626_封面_v22.indd   1 1 CCJulAug _封面.v.indd` | 印刷 slug,**交错重复 + 被部分翻译**(问题 N1) |
| p2 | — | 0.78 | `V o l u m e   6 6 … J 七月 / A 八月  2 0 2 6` | 字距拉开单元被逐段混译(问题 N2) |
| p2 | — ×2 | 1.0 | `CCJulAug26_Conts_v3.in` | 印刷 slug,应保留;重复出现两条(N1 关联) |
| p2 | — ×2 | 1.0 | `CJulAug26_pIFC.indd   1` | 同上 |
| p2 | — | 1.0 | `CERNCOURIER.COM` | 刊头域名,应保留 |
| p2 | — | 1.0 | `Volume 66 Number 4  July/August 2026` | 版权页期号行,可译类,未入队(N3) |
| p2 | — | 1.0 | `IBIC2026@triumf.ca` | 邮箱,应保留 |
| p2 | — | 1.0 | `P Dinault/CERN` | 图片署名,应保留类 |
| p2 | — | 1.0 | `indico.jacow.org/event/113/` | URL,应保留 |
| p3 | p3#28/30 | 1.0 | `www.bergoz.com` / `info@bergoz.com` | 广告 URL/邮箱,应保留 |
| p3 | p3#44 | 0.76 | `CCJulAug2626_新闻分析_v33.indd …` | slug 交错重复+部分翻译(N1) |
| p3 | p3#49/51 | 1.0 | `ul-Aug-Bergoz_colourRL.indd …` | slug,p3#51 同现交错重复(N1) |
| p4 | p4#23 | 0.81 | `CCJulAug2626_历史_v44.indd … /2026年7月` | slug 交错重复+部分翻译(N1) |
| p4 | p4#38 | 1.0 | `R Hahn, Fermilab` | 图片署名,应保留类 |
| p4 | p4#6 | 1.0 | `CERNCOURIER.COM` | 页眉域名,应保留 |

## HuaweiTech-zh(zh→en)residue 3 条逐条

| 页 | ratio | 摘录 | 初步归因 |
|---|---|---|---|
| p2 | 1.0 | `目` | 目录页装饰性拆字标题,单字单元(N5) |
| p2 | 1.0 | `录` | 同上 |
| p2 | 1.0 | `范济安` | 目录页作者名未音译(N6) |

## 新问题登记

- **N1 印刷 slug 交错重复且被部分翻译**(CERN p1/p3/p4):裁切标线旁
  `.indd` slug 输出为源文与半译文交错(如 `CCJulAug2626_封面_v22.indd 1 1
  CCJulAug _封面.v.indd`)。疑似同一 slug 的多个旋转/重叠 run 被分组后
  各自处理。涉及 6 条 residue。
- **N2 字距拉开的报头行被逐段混译**(CERN p2):`V o l u m e   6 6 …`
  单字符间隔单元内 `Jul`/`Aug` 被局部替换为 `七月/八月`,余下保持拉开
  的拉丁字符,成品为中英混杂。
- **N3 版权页期号行未入队**(CERN p2):`Volume 66 Number 4 July/August
  2026` 为可译文本,ratio 1.0 原样残留。
- **N4 两份冷跑链数均为 0**:`chain_report.json` chains=0,tail_fill
  所有接续边界 unchained(CERN 3/3、HuaweiTech 5/5)。T2b 的配对规则
  对这两个版式族未命中,栏尾充满率也偏低(中位 0.72 / 0.64,对照
  Courier 0.885)。是否为真漏配需下批定因。
- **N5 装饰性拆字标题按单字单元处理**(HuaweiTech p2):目录页
  "目/录"两个单字框各自成段,拒绝入队后计为 residue。
- **N6 zh→en 方向 echo_retry 准入不生效**:HuaweiTech 8 条候选全部
  `not_wrong_script`,`范济安`(han,对 en 目标为错文种)未获重试。
  疑似准入判定的"错文种"对 zh→en 方向的 han 残留未命中。
- **N7 HuaweiTech 首字两个 intent 均回滚**:`glyph_metrics_unavailable`
  ×1、`post_render_coverage_failed` ×1(fail-open,原版式保留,非缺陷
  行为,但覆盖率待查)。
