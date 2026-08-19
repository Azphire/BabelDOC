# B9.5 acceptance: the collision census and page containment

Three arms per sample over the whole corpus, the same stack in all three. The arm attribute is `magazine_repair`; the control repeats the off arm and is what says how much a run differs from itself.

Two instruments, and the report says which produced each number. The arms produce the pages and the pixels. The census and the containment inventory are computed by `analyze_b9_5.py`, which drives the shipped detectors and the shipped action over each run's own checkpoints: the loop's decision is by design not served from the cache, and a mechanism measured through a sampled decision is measured through the sampling too.

Bounds in force: `collision_min_iou` 0.2, `collision_source_min_iou` 0.05, `page_safety_margin_ratio` 0.0, `out_of_page_min_overflow_ratio` 0.002, source layout read from the `styles_and_formulas` checkpoint.

## Cost

| arm | requests | cache hits | API calls | prompt tokens | completion tokens | seconds |
| --- | --- | --- | --- | --- | --- | --- |
| off | 396 | 317 | 79 | 71033 | 13632 | 368.9 |
| control | 397 | 384 | 13 | 15611 | 3039 | 325.0 |
| on | 406 | 396 | 10 | 38836 | 549 | 1141.3 |
| contain | 394 | 389 | 5 | 5201 | 848 | 2560.0 |

## Which document the geometry is measured on

The finished geometry here is the `typesetting` checkpoint. The one pass between that checkpoint and the run's own detection is the heading policy, so the findings made here are compared against the `issues.json` each run wrote, and where they differ the difference is the heading policy and is stated rather than smoothed away.

| sample | agrees | counts here | counts in the run's sidecar | only here | only there |
| --- | --- | --- | --- | --- | --- |
| AramcoWorld-en-v2 | True | {"fragment_cluster": 4, "out_of_page": 3, "untranslated_residue": 35} | {"fragment_cluster": 4, "out_of_page": 3, "untranslated_residue": 35} | none | none |
| CERNCourier-en | False | {"fragment_cluster": 16, "out_of_page": 1, "untranslated_residue": 33} | {"fragment_cluster": 16, "out_of_page": 1, "untranslated_residue": 32} | `untranslated_residue:p2:p2#31` | none |
| Courier-en | True | {"fragment_cluster": 1, "out_of_page": 1, "untranslated_residue": 12} | {"fragment_cluster": 1, "out_of_page": 1, "untranslated_residue": 12} | none | none |
| Courier-zh | True | {"untranslated_residue": 2} | {"untranslated_residue": 2} | none | none |
| FD-en-v2 | True | {"fragment_cluster": 9, "out_of_page": 2, "untranslated_residue": 34} | {"fragment_cluster": 9, "out_of_page": 2, "untranslated_residue": 34} | none | none |
| Vogue-en | True | {"fragment_cluster": 8, "untranslated_residue": 10} | {"fragment_cluster": 8, "untranslated_residue": 10} | none | none |

## a. CERN Courier page 1, the masthead

F1 recorded this heading as drawn off the top of its own page and b9.2.2 found the cause: the typesetting stage anchors a paragraph's line spacing on the modal size of the units it holds, and this paragraph holds the masthead together with the issue date, the URL and the strapline. The heading path changed in b9.2, so the F1 measurement is void and the state is measured again here before anything is done about it.

| what | box | frame | past the frame | as a share of the axis | the source, past the same frame | added by the translation |
| --- | --- | --- | --- | --- | --- | --- |
| `p1#2` (title), side top | [521.09, 633.25, 978.56, 760.32] | [0.0, 0.0, 1024.0, 768.0] | 36.6881 | 0.047771 | 16.07 | 20.6181 |

Classification: **bleed the translation deepened**. The comparison is between the same quantity on both sides -- the extent of the boxes the characters are laid out in, which for a display line is the em box and not the visible ink -- so both figures are wider than what a reader sees being cut, and they are comparable to each other.

What containment does to it, and what a reader gets:

| measured on | outcome | state | scale | shift | box before | box after | worst overflow after |
| --- | --- | --- | --- | --- | --- | --- | --- |
| the scripted arm, on the document the PDF was written from | accepted | translated | 1.0 | [0.0, -34.0135] | [521.0887, 754.9809, 1008.4199, 794.3335] | [521.0887, 720.9675, 1008.4199, 760.32] | 0.0 |
| this script, on the typesetting checkpoint | accepted | translated | 1.0 | [0.0, -44.3681] | [521.0887, 677.6131, 978.5587, 804.6881] | [521.0887, 633.245, 978.5587, 760.32] | 0.0 |

The two rows differ by the heading policy, which runs between the checkpoint this script reads and the document the run detects and writes: the policy has already pulled the masthead part of the way back, and what containment then has to move is the remainder. Both land the ink inside the frame; the first is the one the pixels come from.

Rasters, and every one of them is written by this script:

- p1#2 as the source drew it: `examples/output/b9_5/raster/CERNCourier-en.p1_2.source.png`
- the masthead as translated, before containment: `examples/output/b9_5/raster/CERNCourier-en.p1_2.before.png`
- the same, contained: `examples/output/b9_5/raster/CERNCourier-en.p1_2.after.png`
- the whole page before: `examples/output/b9_5/raster/CERNCourier-en.p1.before.png`
- the whole page contained: `examples/output/b9_5/raster/CERNCourier-en.p1.after.png`


## b. The corpus collision census

Every pair of texts that overlaps at all on a finished page, classified against the layout the source drew. A pair the source already overlapped at or above `collision_source_min_iou` is the designer's decision and is exempt; a pair the source did not, overlapping now at or above `collision_min_iou`, is raised; the rest are under the bound and are counted here so that the census can be read for near misses as well.

| sample | pages | overlapping pairs | induced | source design | below the bound | no source counterpart | raised as findings |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AramcoWorld-en-v2 | 9 | 2 | 0 | 0 | 2 | 0 | 0 |
| CERNCourier-en | 4 | 39 | 0 | 25 | 14 | 0 | 0 |
| Courier-en | 8 | 0 | 0 | 0 | 0 | 0 | 0 |
| Courier-zh | 8 | 0 | 0 | 0 | 0 | 0 | 0 |
| FD-en-v2 | 9 | 7 | 0 | 7 | 0 | 0 | 0 |
| Vogue-en | 3 | 18 | 0 | 6 | 12 | 0 | 0 |

### The overlaps the source already had, pair by pair

Everything at or above the bound the detector measures at, so what is listed is what the source exemption is carrying. Nothing here is a finding.

| sample | page | paragraphs | labels | iou | source iou | covered | source covered | class | text |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CERNCourier-en | 1 | `p1#7`, `p1#9` | abandon/abandon | 1.0 | 1.0 | 1.0 | 1.0 | source design | `2026年7月3日` / `2026年7月3日` |
| CERNCourier-en | 1 | `p1#8`, `p1#10` | fallback_line/fallback_line | 1.0 | 1.0 | 1.0 | 1.0 | source design | `16:06` / `16:06` |
| CERNCourier-en | 2 | `p2#30`, `p2#32` | fallback_line/fallback_line | 1.0 | 1.0 | 1.0 | 1.0 | source design | `C` / `C` |
| CERNCourier-en | 2 | `p2#31`, `p2#33` | title/title | 1.0 | 1.0 | 1.0 | 1.0 | source design | `CJulAug26_pIFC.indd 1` / `CJulAug26_pIFC.indd 1` |
| CERNCourier-en | 2 | `p2#131`, `p2#133` | abandon/abandon | 1.0 | 1.0 | 1.0 | 1.0 | source design | `CCJulAug26_Conts_v3.in` / `CCJulAug26_Conts_v3.in` |
| CERNCourier-en | 2 | `p2#132`, `p2#134` | fallback_line/fallback_line | 1.0 | 1.0 | 1.0 | 1.0 | source design | `dd   3` / `dd   3` |
| CERNCourier-en | 3 | `p3#45`, `p3#47` | fallback_line/fallback_line | 1.0 | 1.0 | 1.0 | 1.0 | source design | `16:22` / `16:22` |
| CERNCourier-en | 3 | `p3#48`, `p3#50` | fallback_line/fallback_line | 1.0 | 1.0 | 1.0 | 1.0 | source design | `Pub_CERN-26-J` / `Pub_CERN-26-J` |
| CERNCourier-en | 4 | `p4#24`, `p4#26` | fallback_line/fallback_line | 1.0 | 1.0 | 1.0 | 1.0 | source design | `16:44` / `16:44` |
| CERNCourier-en | 4 | `p4#39`, `p4#42` | fallback_line/fallback_line | 1.0 | 1.0 | 1.0 | 1.0 | source design | `C` / `C` |
| CERNCourier-en | 4 | `p4#40`, `p4#43` | title/title | 0.5196 | 1.0 | 0.9874 | 1.0 | source design | `CJulAug26_HI` / `卷66 第4期 2026年7/8月` |
| CERNCourier-en | 3 | `p3#35`, `p3#40` | plain text/plain text | 0.5165 | 0.7091 | 0.9846 | 1.0 | source design | `在数字化过程中保持模拟信号的完整性确保通过使用实现长期可持续性提供一个易于使用且` / `数字化；高性能且广泛可用的组件；可以适应不同的光束类型。` |
| FD-en-v2 | 9 | `p9#0`, `p9#6` | abandon/abandon | 0.9778 | 0.9778 | 0.9888 | 0.9888 | source design | `MONTH 202` / `JUNE 2026` |
| FD-en-v2 | 9 | `p9#0`, `p9#3` | abandon/abandon | 0.8986 | 0.8986 | 1.0 | 1.0 | source design | `MONTH 202` / `DECEMBER 2` |
| FD-en-v2 | 9 | `p9#3`, `p9#6` | abandon/abandon | 0.8823 | 0.8823 | 0.9904 | 0.9904 | source design | `DECEMBER 2` / `JUNE 2026` |
| FD-en-v2 | 9 | `p9#2`, `p9#7` | abandon/abandon | 0.5775 | 0.5691 | 0.8714 | 0.9962 | source design | `F&D 标识` / `F  D 货币票据` |

### Where one text stands under another and no finding is made

The same pairs read by the other measure: the shared area over the area of the smaller box. A folio printed inside a contents entry covers almost all of itself and almost none of their union, so the intersection over union the detector is bounded by reports it as nothing. Listed at coverage 0.5 and above, which is a floor for this table and not a threshold anything is judged by.

| sample | page | paragraphs | labels | iou | covered | source covered | class | text |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| AramcoWorld-en-v2 | 3 | `p3#0`, `p3#4` | abandon/title | 0.0089 | 0.5234 | 0.1347 | below the bound | `阿特拉斯上的班卓琴 撰文 Banning Eyre 一种拥有西非祖先并与美国音乐` / `专题内容` |
| CERNCourier-en | 1 | `p1#7`, `p1#9` | abandon/abandon | 1.0 | 1.0 | 1.0 | source design | `2026年7月3日` / `2026年7月3日` |
| CERNCourier-en | 1 | `p1#8`, `p1#10` | fallback_line/fallback_line | 1.0 | 1.0 | 1.0 | source design | `16:06` / `16:06` |
| CERNCourier-en | 2 | `p2#30`, `p2#32` | fallback_line/fallback_line | 1.0 | 1.0 | 1.0 | source design | `C` / `C` |
| CERNCourier-en | 2 | `p2#31`, `p2#33` | title/title | 1.0 | 1.0 | 1.0 | source design | `CJulAug26_pIFC.indd 1` / `CJulAug26_pIFC.indd 1` |
| CERNCourier-en | 2 | `p2#131`, `p2#133` | abandon/abandon | 1.0 | 1.0 | 1.0 | source design | `CCJulAug26_Conts_v3.in` / `CCJulAug26_Conts_v3.in` |
| CERNCourier-en | 2 | `p2#132`, `p2#134` | fallback_line/fallback_line | 1.0 | 1.0 | 1.0 | source design | `dd   3` / `dd   3` |
| CERNCourier-en | 3 | `p3#45`, `p3#47` | fallback_line/fallback_line | 1.0 | 1.0 | 1.0 | source design | `16:22` / `16:22` |
| CERNCourier-en | 3 | `p3#48`, `p3#50` | fallback_line/fallback_line | 1.0 | 1.0 | 1.0 | source design | `Pub_CERN-26-J` / `Pub_CERN-26-J` |
| CERNCourier-en | 3 | `p3#49`, `p3#51` | abandon/abandon | 0.017 | 1.0 | 1.0 | below the bound | `ul-Aug-Bergoz_colourRL.indd 1` / `ul-Aug-Bergoz_colourRL.indd   1 30/0623 ` |
| CERNCourier-en | 4 | `p4#24`, `p4#26` | fallback_line/fallback_line | 1.0 | 1.0 | 1.0 | source design | `16:44` / `16:44` |
| CERNCourier-en | 4 | `p4#39`, `p4#42` | fallback_line/fallback_line | 1.0 | 1.0 | 1.0 | source design | `C` / `C` |
| CERNCourier-en | 4 | `p4#41`, `p4#44` | abandon/abandon | 0.0106 | 1.0 | 1.0 | below the bound | `STORY_v4.indd 24` / `STORY_v4.indd   24 03/0743 030743/2026  ` |
| CERNCourier-en | 4 | `p4#40`, `p4#43` | title/title | 0.5196 | 0.9874 | 1.0 | source design | `CJulAug26_HI` / `卷66 第4期 2026年7/8月` |
| CERNCourier-en | 3 | `p3#35`, `p3#40` | plain text/plain text | 0.5165 | 0.9846 | 1.0 | source design | `在数字化过程中保持模拟信号的完整性确保通过使用实现长期可持续性提供一个易于使用且` / `数字化；高性能且广泛可用的组件；可以适应不同的光束类型。` |
| CERNCourier-en | 4 | `p4#23`, `p4#25` | abandon/abandon | 0.0359 | 0.9564 | 1.0 | source design | `CCJulAug2626_HISTORY_v44.indd   25 25 03` / `2026年7月3日` |
| CERNCourier-en | 3 | `p3#22`, `p3#24` | plain text/plain text | 0.0052 | 0.8184 | 1.0 | below the bound | `T` / `战略过程显示了粒子物理学界的强烈参与，并得出了非常明确的结论：如果获得批准，FC` |
| CERNCourier-en | 3 | `p3#23`, `p3#24` | title/plain text | 0.005 | 0.8184 | 1.0 | below the bound | `h` / `战略过程显示了粒子物理学界的强烈参与，并得出了非常明确的结论：如果获得批准，FC` |
| CERNCourier-en | 4 | `p4#1`, `p4#40` | title/title | 0.0716 | 0.8057 | 0.8259 | source design | `C` / `CJulAug26_HI` |
| CERNCourier-en | 4 | `p4#1`, `p4#43` | title/title | 0.1327 | 0.8032 | 0.8259 | source design | `C` / `卷66 第4期 2026年7/8月` |
| CERNCourier-en | 3 | `p3#11`, `p3#13` | plain text/plain text | 0.0016 | 0.7876 | 1.0 | below the bound | `T` / `“欧洲战略重申了高亮度大型强子对撞机的关键重要性，该对撞机将利用先进的加速器和探` |
| CERNCourier-en | 3 | `p3#12`, `p3#13` | title/plain text | 0.0015 | 0.7876 | 1.0 | below the bound | `h` / `“欧洲战略重申了高亮度大型强子对撞机的关键重要性，该对撞机将利用先进的加速器和探` |
| CERNCourier-en | 3 | `p3#2`, `p3#48` | fallback_line/fallback_line | 0.0719 | 0.676 | 0.7119 | source design | `C` / `Pub_CERN-26-J` |
| CERNCourier-en | 3 | `p3#2`, `p3#50` | fallback_line/fallback_line | 0.0719 | 0.676 | 0.7119 | source design | `C` / `Pub_CERN-26-J` |
| CERNCourier-en | 4 | `p4#23`, `p4#44` | abandon/abandon | 0.065 | 0.5325 | 0.5325 | source design | `CCJulAug2626_HISTORY_v44.indd   25 25 03` / `STORY_v4.indd   24 03/0743 030743/2026  ` |
| FD-en-v2 | 9 | `p9#0`, `p9#3` | abandon/abandon | 0.8986 | 1.0 | 1.0 | source design | `MONTH 202` / `DECEMBER 2` |
| FD-en-v2 | 9 | `p9#3`, `p9#6` | abandon/abandon | 0.8823 | 0.9904 | 0.9904 | source design | `DECEMBER 2` / `JUNE 2026` |
| FD-en-v2 | 9 | `p9#0`, `p9#6` | abandon/abandon | 0.9778 | 0.9888 | 0.9888 | source design | `MONTH 202` / `JUNE 2026` |
| FD-en-v2 | 9 | `p9#1`, `p9#3` | fallback_line/abandon | 0.0858 | 0.984 | 0.984 | source design | `3` / `DECEMBER 2` |
| FD-en-v2 | 9 | `p9#2`, `p9#7` | abandon/abandon | 0.5775 | 0.8714 | 0.9962 | source design | `F&D 标识` / `F  D 货币票据` |
| FD-en-v2 | 9 | `p9#5`, `p9#7` | abandon/abandon | 0.1757 | 0.8001 | 0.9948 | source design | `F&D` / `F  D 货币票据` |
| FD-en-v2 | 9 | `p9#2`, `p9#5` | abandon/abandon | 0.1812 | 0.6372 | 1.0 | source design | `F&D 标识` / `F&D` |
| Vogue-en | 3 | `p3#36`, `p3#38` | plain text/plain text | 0.01 | 0.7211 | 1.0 | below the bound | `e` / `无论你是乘火车、骑自行车、滑滑板，还是步行，轻便的层次和` |
| Vogue-en | 3 | `p3#37`, `p3#38` | title/plain text | 0.0171 | 0.7211 | 1.0 | below the bound | `th` / `无论你是乘火车、骑自行车、滑滑板，还是步行，轻便的层次和` |
| Vogue-en | 3 | `p3#35`, `p3#38` | title/plain text | 0.0269 | 0.7178 | 0.457 | source design | `Wh` / `无论你是乘火车、骑自行车、滑滑板，还是步行，轻便的层次和` |
| Vogue-en | 3 | `p3#18`, `p3#19` | title/plain text | 0.1031 | 0.5458 | 0.5144 | below the bound | `46T` / `测试场 Sanaz Toossi（Sanaz Toossi）带来` |

### The pages behind the three cases this batch was asked to sort

Read against the tables above. The imposition slugs a printer's file carries are painted twice and are exempt by the source comparison; a contents page prints its folio inside the entry it numbers, and the measure the detector is bounded by does not see it; and a page the earlier review recorded as carrying three layers of text carries no overlapping pair at all in this build.

- `CERNCourier-en` page 3: `examples/output/b9_5/raster/CERNCourier-en.p3.census.png`
- `Courier-zh` page 8: `examples/output/b9_5/raster/Courier-zh.p8.census.png`
- `Vogue-en` page 3: `examples/output/b9_5/raster/Vogue-en.p3.census.png`

## The out of page inventory

Every out of page finding on the corpus, with what the same paragraph's source counterpart did against the same frame. `induced` is ink the source kept inside and the translation put out; `bleed the translation deepened` is a paragraph the source already ran past the trim and the translation ran further; `bleed` is one the translation did not worsen.

| sample | page | paragraph | label | side | past the frame | share | the source | added | class | text |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| AramcoWorld-en-v2 | 1 | `p1#1` | fallback_line | left | 603.5539 | 0.99357 | 604.1599 | -0.606 | bleed | `16344araD1R1.Cvr.indd 1-3` |
| AramcoWorld-en-v2 | 1 | `p1#2` | fallback_line | bottom | 18.0 | 0.022989 | 18.0 | 0.0 | bleed | `(cid:25)(cid:18)(cid:23)(cid:18)(cid:21)` |
| AramcoWorld-en-v2 | 5 | `p5#16` | fallback_line | left | 307.3494 | 0.486697 | 313.6014 | -6.252 | bleed | `希贾兹` |
| CERNCourier-en | 1 | `p1#2` | title | top | 36.6881 | 0.047771 | 16.07 | 20.6181 | bleed the translation deepened | `欧洲核子研究中心快报2026年7月/8月 CERNCOURIER.COM 国际高` |
| Courier-en | 1 | `p1#10` | title | top | 11.5863 | 0.013762 | 0.0 | 11.5863 | induced | `信使T H E 联合国教科文组织` |
| FD-en-v2 | 2 | `p2#8` | fallback_line | right | 30.96 | 0.05375 | 30.96 | -0.0 | bleed | `BRIANSTAUFFER` |
| FD-en-v2 | 4 | `p4#3` | fallback_line | left | 32.685 | 0.056745 | 32.685 | 0.0 | bleed | `PORTERGIFFORD,CHANTALJAHCHAN` |

## c. What containment did, site by site

The first instrument is the fourth arm. Its decision is scripted rather than sampled -- it names every out of page finding and lets the action's own rule decide which of them may be touched -- and everything downstream of the decision is the shipped path: the rule, the guard, the transform and the writer. It is the arm the pixels below come from, and it is not evidence about what the model chooses.

### CERNCourier-en

| paragraph | iteration | accepted | reason | state | scale | shift | box before | box after | worst overflow after |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `p1#2` | 1 | True | accepted | translated | 1.0 | [0.0, -34.0135] | [521.0887, 754.9809, 1008.4199, 794.3335] | [521.0887, 720.9675, 1008.4199, 760.32] | 0.0 |

- `p1#2` page 1: before `examples/output/b9_5/raster/CERNCourier-en.p1_2.before.png`, after `examples/output/b9_5/raster/CERNCourier-en.p1_2.after.png`; the whole page before `examples/output/b9_5/raster/CERNCourier-en.p1.before.png`, after `examples/output/b9_5/raster/CERNCourier-en.p1.after.png`

### Courier-en

| paragraph | iteration | accepted | reason | state | scale | shift | box before | box after | worst overflow after |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `p1#10` | 1 | True | accepted | translated | 1.0 | [0.0, -20.0052] | [373.3852, 811.992, 510.2606, 853.4763] | [373.3852, 791.9867, 510.2606, 833.4711] | 0.0 |

- `p1#10` page 1: before `examples/output/b9_5/raster/Courier-en.p1_10.before.png`, after `examples/output/b9_5/raster/Courier-en.p1_10.after.png`; the whole page before `examples/output/b9_5/raster/Courier-en.p1.before.png`, after `examples/output/b9_5/raster/Courier-en.p1.after.png`

### The same action driven over every finding of the corpus

The second instrument, which reaches the findings the arm's own run did not: the action driven from `analyze_b9_5.py` over every out of page finding, each held against its own rule first. What it applied:

| sample | page | paragraph | label | state | scale | shift | box before | box after | worst overflow after | worst overlap after |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CERNCourier-en | 1 | `p1#2` | title | translated | 1.0 | [0.0, -44.3681] | [521.0887, 677.6131, 978.5587, 804.6881] | [521.0887, 633.245, 978.5587, 760.32] | 0.0 | 0.0207 |
| Courier-en | 1 | `p1#10` | title | translated | 1.0 | [0.0, -20.0052] | [373.3852, 811.992, 509.1913, 853.4763] | [373.3852, 791.9867, 509.1913, 833.4711] | 0.0 | 0.0 |

What it escalated:

Nothing was escalated.

What its rule refused before it looked at the geometry:

| sample | page | paragraph | label | overflow ratio | reason |
| --- | --- | --- | --- | --- | --- |
| AramcoWorld-en-v2 | 1 | `p1#1` | fallback_line | 0.99357 | layout_label_outside_the_containment_classes |
| AramcoWorld-en-v2 | 1 | `p1#2` | fallback_line | 0.022989 | layout_label_outside_the_containment_classes |
| AramcoWorld-en-v2 | 5 | `p5#16` | fallback_line | 0.486697 | layout_label_outside_the_containment_classes |
| FD-en-v2 | 2 | `p2#8` | fallback_line | 0.05375 | layout_label_outside_the_containment_classes |
| FD-en-v2 | 4 | `p4#3` | fallback_line | 0.056745 | layout_label_outside_the_containment_classes |

### What the arm's own loop refused, which is the escalation list

| sample | paragraph | finding | reason |
| --- | --- | --- | --- |
| AramcoWorld-en-v2 | `p1#1` | `out_of_page:p1:p1#1` | layout_label_outside_the_containment_classes |
| AramcoWorld-en-v2 | `p1#2` | `out_of_page:p1:p1#2` | layout_label_outside_the_containment_classes |
| AramcoWorld-en-v2 | `p5#16` | `out_of_page:p5:p5#16` | layout_label_outside_the_containment_classes |
| FD-en-v2 | `p2#8` | `out_of_page:p2:p2#8` | layout_label_outside_the_containment_classes |
| FD-en-v2 | `p4#3` | `out_of_page:p4:p4#3` | layout_label_outside_the_containment_classes |

### The guard

Every plan measured against the page it would be applied to, before it was applied: what the paragraph stands on now, what each plan would newly stand on, and what the applied transform actually landed on.

| sample | paragraph | bound | standing on before | the slide would induce | worst iou it would induce | the fallback would induce | refused | induced after applying |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CERNCourier-en | `p1#2` | 0.2 | 0 | 0 | 0.0 | n/a | none | 0 |
| Courier-en | `p1#10` | 0.2 | 0 | 0 | 0.0 | n/a | none | 0 |

The guard refused nothing on this corpus: 0 of the containments planned here had a plan turned down, because neither heading had anything standing where it was going. That is the corpus answering rather than the mechanism being untested -- the fallback chain is driven end to end by the synthetic cases in `spec_checks/spec_check_b9_5.py`, which build a page where the slide lands on a neighbour and the shrink in place does not, and one where neither is clear and the finding is escalated with the paragraph left exactly as it was.

### What the loop itself did

The arms, for comparison: the loop asks a model which findings to act on and that request is not served from the cache, so this is what was sampled on these runs rather than what the loop will do on the next one.

| sample | arm | iterations | action and findings chosen | applications | stopped because |
| --- | --- | --- | --- | --- | --- |
| AramcoWorld-en-v2 | off | loop down | - | - | - |
| AramcoWorld-en-v2 | control | loop down | - | - | - |
| AramcoWorld-en-v2 | on | 1 | translate_orphan_lines(3) | 0 | no_paragraph_was_written |
| AramcoWorld-en-v2 | contain | 1 | contain_in_page(3) | 0 | no_finding_the_action_may_act_on |
| CERNCourier-en | off | loop down | - | - | - |
| CERNCourier-en | control | loop down | - | - | - |
| CERNCourier-en | on | 2 | translate_orphan_lines(2); translate_orphan_lines(1) | 1 | no_paragraph_was_written |
| CERNCourier-en | contain | 2 | contain_in_page(1); none(0) | 1 | decision_applied_nothing |
| Courier-en | off | loop down | - | - | - |
| Courier-en | control | loop down | - | - | - |
| Courier-en | on | 1 | none(0) | 0 | decision_applied_nothing |
| Courier-en | contain | 2 | contain_in_page(1); none(0) | 1 | decision_applied_nothing |
| Courier-zh | off | loop down | - | - | - |
| Courier-zh | control | loop down | - | - | - |
| Courier-zh | on | 1 | translate_orphan_lines(1) | 0 | no_paragraph_was_written |
| Courier-zh | contain | 1 | none(0) | 0 | decision_applied_nothing |
| FD-en-v2 | off | loop down | - | - | - |
| FD-en-v2 | control | loop down | - | - | - |
| FD-en-v2 | on | 1 | translate_orphan_lines(1) | 0 | no_finding_the_action_may_act_on |
| FD-en-v2 | contain | 1 | contain_in_page(2) | 0 | no_finding_the_action_may_act_on |
| Vogue-en | off | loop down | - | - | - |
| Vogue-en | control | loop down | - | - | - |
| Vogue-en | on | 1 | none(0) | 0 | decision_applied_nothing |
| Vogue-en | contain | 1 | none(0) | 0 | decision_applied_nothing |

Containments the loop carried out end to end:

| arm | iteration | paragraph | accepted | reason |
| --- | --- | --- | --- | --- |
| contain | 1 | `p1#2` | True | accepted |

## d. Outside the contained paragraphs

The soul assertion, on three channels, because they fail differently and only one of them is clean of the sampling.

**In the run.** Each arm's loop compares the document it received against the document it produced and writes the verdict into its own sidecar. Nothing about a request's answer can move this: it is one document measured against itself inside one process.

| sample | arm | verdict | touched | changed outside the touched set | paragraphs before | paragraphs after |
| --- | --- | --- | --- | --- | --- | --- |
| AramcoWorld-en-v2 | on | conserved | none | none | 176 | 176 |
| AramcoWorld-en-v2 | contain | conserved | none | none | 176 | 176 |
| CERNCourier-en | on | conserved | `p2#39` | none | 255 | 255 |
| CERNCourier-en | contain | conserved | `p1#2` | none | 255 | 255 |
| Courier-en | on | conserved | none | none | 147 | 147 |
| Courier-en | contain | conserved | `p1#10` | none | 147 | 147 |
| Courier-zh | on | conserved | none | none | 135 | 135 |
| Courier-zh | contain | conserved | none | none | 135 | 135 |
| FD-en-v2 | on | conserved | none | none | 218 | 218 |
| FD-en-v2 | contain | conserved | none | none | 218 | 218 |
| Vogue-en | on | conserved | none | none | 94 | 94 |
| Vogue-en | contain | conserved | none | none | 94 | 94 |

**On the intermediate language, outside the loop.** One digest per paragraph before and after the action was driven over the base arm's document by `analyze_b9_5.py`, so the claim covers the findings the arm's own run did not reach.

| sample | paragraphs | contained | which | paragraphs changed | changed outside the contained set |
| --- | --- | --- | --- | --- | --- |
| AramcoWorld-en-v2 | 176 | 0 | none | 0 | none |
| CERNCourier-en | 255 | 1 | `p1#2` | 1 | none |
| Courier-en | 147 | 1 | `p1#10` | 1 | none |
| Courier-zh | 135 | 0 | none | 0 | none |
| FD-en-v2 | 218 | 0 | none | 0 | none |
| Vogue-en | 94 | 0 | none | 0 | none |

**On the page, with the attribution floor.** What the scripted arm renders differently from the base arm, against what the control arm -- which repeats the base arm exactly -- renders differently from it. The last three columns are why a floor is needed at all: a request the cache could not answer is sampled again, and a resampled translation is a page that renders differently for a reason that is not this batch's. The unexplained column is the one that would be a finding, and the report says plainly where a sample's floor is too wide for this channel to attribute anything.

| sample | pages contained on | moved, control vs off | moved, contain vs off | moved and neither contained nor within the floor | API calls, off | control | contain |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AramcoWorld-en-v2 | none | none | [2, 3, 4, 5, 6, 7, 8] | [2, 3, 4, 5, 6, 7, 8] | 17 | 0 | 5 |
| CERNCourier-en | [1] | [1, 2, 3, 4] | [1, 2, 3, 4] | none | 62 | 13 | 0 |
| Courier-en | [1] | none | [1] | none | 0 | 0 | 0 |
| Courier-zh | none | none | none | none | 0 | 0 | 0 |
| FD-en-v2 | none | none | none | none | 0 | 0 | 0 |
| Vogue-en | none | none | none | none | 0 | 0 | 0 |

- `AramcoWorld-en-v2` pages [2, 3, 4, 5, 6, 7, 8]: the scripted arm contained nothing on this sample -- its loop's own record names no paragraph as touched -- and it made 5 request(s) the cache could not answer. A resampled translation is what these pages differ by, and it is the channel the evaluation protocol already records as unreplayable.

## e. The frozen fixture

The documents every geometric number above was computed from, so the census and the containment can be replayed from committed files rather than from a run.

- `examples/output/b9_5/fixtures/CERNCourier-en.checkpoints.zip`
- `examples/output/b9_5/fixtures/CERNCourier-en.issues.json`
- `examples/output/b9_5/fixtures/CERNCourier-en.containment.json`

