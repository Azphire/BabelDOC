# B9.3 acceptance: line structure preservation over three samples

Three arms per sample, the same stack in all three. Two of them differ in one attribute; the third repeats the first, and is what says how much a run differs from itself.

## The arms

| sample | declared pages | split paragraphs | line paragraphs | exempt | IL pages differing | attributable | undeclared attributable |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Courier-en | [1] | 12 | 27 | 7 | [1, 2, 4, 7, 8] | [1, 2, 4, 7, 8] | [2, 4, 7, 8] |
| FD-en-v2 | [3, 5, 7] | 15 | 44 | 18 | [2, 3, 5, 6] | [2, 3, 5, 6] | [2, 6] |
| Vogue-en | [3] | 11 | 66 | 11 | [3] | [3] | none |

## Cost

| arm | requests | cache hits | API calls | prompt tokens | completion tokens | seconds |
| --- | --- | --- | --- | --- | --- | --- |
| off | 131 | 126 | 5 | 14479 | 765 | 147.4 |
| control | 131 | 126 | 5 | 14507 | 789 | 188.4 |
| on | 160 | 75 | 85 | 89077 | 11667 | 183.9 |

## The calibration

Measured on Courier-en page 1, classified `toc`: 19 paragraph(s) hold more than one line. The widest the measure bound admits is 39.0 non-space characters per line; the narrowest column it exempts is 55.6. The bound ships at 47.0, 8.0 above the first and 8.6 below the second.

The setting bound ships up. Every paragraph admitted is set in more than one face: True. It exempts 1 paragraph(s) the measure bound would have admitted: ['p1#11'].

| paragraph | lines | mean line chars | heterogeneous | verdict | text |
| --- | --- | --- | --- | --- | --- |
| p1#2 | 5 | 63.6 | False | long_lines | Indigenous knowledge has long been ignored, and sometimes ev |
| p1#3 | 6 | 58.8 | False | long_lines | Rooted in the careful observation of ecosystems and passed d |
| p1#4 | 8 | 86.1 | False | long_lines | UNESCO has long been a pioneer in this field. Through its Lo |
| p1#5 | 5 | 72.2 | False | long_lines | Beyond providing empirical data, Indigenous knowledge challe |
| p1#6 | 3 | 89.0 | False | long_lines | But this recognition must be accompanied by guarantees — the |
| p1#7 | 5 | 55.6 | False | long_lines | By promoting this knowledge, UNESCO is reminding us of the o |
| p1#8 | 2 | 13.0 | True | split | Agnès Bardon Editor-in-Chief |
| p1#11 | 3 | 15.3 | False | uniform_styling | How Indigenous knowledge drives scientific discovery |
| p1#12 | 2 | 39.0 | True | split | A changing climate for Indigenous knowledge ................ |
| p1#14 | 2 | 28.5 | True | split | Brazil: lessons from the water people ..... 9 Marcelo Silva  |
| p1#15 | 2 | 36.0 | True | split | When biopiracy takes root .................. 12 Daniel Robin |
| p1#16 | 3 | 28.0 | True | split | China: the radiant health of traditional Dai medicine ...... |
| p1#17 | 2 | 26.5 | True | split | The secret skies of Kalahari ................. 17 Sisco Aual |
| p1#18 | 3 | 26.7 | True | split | The Sámi people, indispensable guardians of climate change . |
| p1#19 | 2 | 35.0 | True | split | “Our knowledge has long been regarded as folklore” ......... |
| p1#22 | 2 | 33.0 | True | split | Exile through a child’s eyes ................. 26 Photos: Fo |
| p1#24 | 2 | 38.5 | True | split | Welcome to the second quantum revolution ................... |
| p1#27 | 3 | 37.7 | True | split | “Fiction is humanity’s last collective frontier in honest st |
| p1#29 | 2 | 32.0 | True | split | Africa’s book industry: a new page is turning .............. |

## a. The five defects, measured on the page

Courier-en page 1: 12 paragraph(s) cut into 27 record line(s).

| measurement | off | on |
| --- | --- | --- |
| rendered lines in the column | 34 | 42 |
| lines carrying a leader run | 5 | 5 |
| 3: another record continues after the folio | 7 | 0 |
| 3: orphan lines left by that wrap | 2 | 0 |
| 4: latin words broken across lines | 1 | 0 |
| 2: spread of the leader right edges (pt) | 54.56 | 36.19 |


Defects 1 and 3 are what this batch closes and the table above is the measurement. Defect 2 is not closed and is not closeable here: the source fills its leaders to a common right edge -- 11 leader line(s), spreading 0.39pt -- and nothing in the intermediate language carries a fill rule, so a line laid out again is laid out from its left edge with the font's own advances. Defect 4 is a line breaking rule inside the typesetting stage rather than a paragraph boundary, and is untouched by a pass that decides what a paragraph is.

- off glued: ['巴西：水上人家的教训.....9马塞洛·席尔瓦·德·索', '当生物盗窃生根时.12丹尼尔·罗宾逊和大卫·杰斐', '中国：传统傣族医学的光辉健康.14杨沙和', '卡拉哈里的秘密天空.................17西斯科·阿瓦拉', '20安娜·罗霍宁', '通过孩子的眼睛看流亡.................26照片：']; orphans: ['萨', '逊']; broken: ['·恩戈兹·阿迪契（Chi | mamandaNgozi']
- on glued: none; orphans: none; broken: none

- off_page: `examples/output/b9_3/raster/Courier-en.p1.off.png`
- on_page: `examples/output/b9_3/raster/Courier-en.p1.on.png`
- off_column: `examples/output/b9_3/raster/Courier-en.p1.off.crop.png`
- on_column: `examples/output/b9_3/raster/Courier-en.p1.on.crop.png`

## b. The editorial column of the same page

6 paragraph(s), all exempted by the measure bound. 6 of them were offered to the translator as one whole text, which is what the exemption is for; without the bounds the same paragraphs would have been cut into 32 requests, each of them a fragment of a sentence. 3 came back as exactly the text the arm with the switch down produced -- the rest were resampled because the shared glossary changed, which is the channel measured in d and not a difference in what was asked.

| paragraph | lines | mean line chars | source chars | offered whole | translated off | translated on | identical | requests without the bounds | first fragment without them |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| p1#2 | 5 | 63.6 | 373 | True | 101 | 101 | True | 5 | Indigenous knowledge has long  been ignored, |
| p1#3 | 6 | 58.8 | 414 | True | 109 | 109 | False | 6 | Rooted  in  the  careful  observation of  ec |
| p1#4 | 8 | 86.1 | 806 | True | 225 | 222 | False | 8 | UNESCO has long been a pioneer in this field |
| p1#5 | 5 | 72.2 | 416 | True | 110 | 110 | True | 5 | Beyond providing empirical data, Indigenous  |
| p1#6 | 3 | 89.0 | 314 | True | 79 | 79 | True | 3 | But this recognition must be accompanied by  |
| p1#7 | 5 | 55.6 | 332 | True | 114 | 109 | False | 5 | By  promoting  this  knowledge,  UNESCO  is  |

## c. The lines the length floor skipped

- Courier-en: 0 line(s)
- FD-en-v2: 0 line(s)
- Vogue-en: 6 line(s): p3#10 'NAD', p3#25 '56', p3#35 'Wh', p3#40 '74', p3#58 '88', p3#71 '94'

### What a smaller unit costs

| sample | units on the declared pages, off | returned untranslated, off | units, on | returned untranslated, on |
| --- | --- | --- | --- | --- |
| Courier-en | 30 | 2 (6.7%) | 45 | 3 (6.7%) |
| FD-en-v2 | 93 | 28 (30.1%) | 122 | 44 (36.1%) |
| Vogue-en | 34 | 10 (29.4%) | 85 | 13 (15.3%) |

A record line is a smaller unit than the paragraph it came out of, and a smaller unit carries less of what a translator needs: a personal name standing alone on its own line is a request with nothing around it, and the engine more often hands it back as it stands. The examples are in the evidence file per arm.

## d. Outside a declared page

Two levels, and they do not say the same thing. The first is the pass itself: the document as it stands when the split has run and before a single request has been built. There the claim is exact and it holds -- every page that differs between the arms is a declared page, and the control differs on none of them. A declared page can also stand unchanged, and one does: a page whose paragraphs the bounds all exempt is a page the pass looked at and left.

| sample | declared | pages differing before translation | confined to declared | declared but unchanged | control differing | splits outside declared |
| --- | --- | --- | --- | --- | --- | --- |
| Courier-en | [1] | [1] | True | none | none | none |
| FD-en-v2 | [3, 5, 7] | [3, 5] | True | [7] | none | none |
| Vogue-en | [3] | [3] | True | none | none | none |

The second is the finished document, and there it does not hold: pages the split never touched are translated differently. That is a real finding rather than noise -- the control reproduced those pages exactly -- and the two channels that carry it are measured below.

| sample | undeclared pages | translated identical | undeclared attributable | raster differing | raster attributable | undeclared attributable (raster) |
| --- | --- | --- | --- | --- | --- | --- |
| Courier-en | [2, 3, 4, 5, 6, 7, 8] | False | [2, 4, 7, 8] | [1, 2, 4, 7, 8] | [1, 2, 4, 7, 8] | [2, 4, 7, 8] |
| FD-en-v2 | [1, 2, 4, 6, 8, 9] | False | [2, 6] | [2, 3, 5, 6] | [2, 3, 5, 6] | [2, 6] |
| Vogue-en | [1, 2] | True | none | [3] | [3] | none |

### How a change reaches a page the split never touched

| sample | pages that moved | reached by the shared glossary | reached by cross page pairing | unexplained | glossary entries changed | changed by the control alone |
| --- | --- | --- | --- | --- | --- | --- |
| Courier-en | [2, 4, 7, 8] | [2, 4, 5, 7, 8] | [2] | none | 7 | 0 |
| FD-en-v2 | [2, 6] | none | [2, 4, 6, 8] | none | 18 | 0 |
| Vogue-en | none | none | none | none | 26 | 0 |

The term extractor reads the whole document and writes one glossary that every prompt draws on, and the cross page and cross column pairing puts a paragraph of one page and a paragraph of another into a single request. Either channel is enough to carry a change off the page it happened on. Neither is this batch's to close, and both are on the record here rather than smoothed into the attribution floor.

## Every declared page, before and after

| sample | page | glued after folio, off | on | orphan lines, off | on | off raster | on raster |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Courier-en | 1 | 7 | 0 | 2 | 0 | `examples/output/b9_3/raster/Courier-en.p1.off.crop.png` | `examples/output/b9_3/raster/Courier-en.p1.on.crop.png` |
| FD-en-v2 | 3 | 0 | 0 | 0 | 0 | `examples/output/b9_3/raster/FD-en-v2.p3.off.crop.png` | `examples/output/b9_3/raster/FD-en-v2.p3.on.crop.png` |
| FD-en-v2 | 5 | 1 | 1 | 0 | 0 | `examples/output/b9_3/raster/FD-en-v2.p5.off.crop.png` | `examples/output/b9_3/raster/FD-en-v2.p5.on.crop.png` |
| FD-en-v2 | 7 | 0 | 0 | 0 | 0 | `examples/output/b9_3/raster/FD-en-v2.p7.off.crop.png` | `examples/output/b9_3/raster/FD-en-v2.p7.on.crop.png` |
| Vogue-en | 3 | 8 | 8 | 0 | 0 | `examples/output/b9_3/raster/Vogue-en.p3.off.crop.png` | `examples/output/b9_3/raster/Vogue-en.p3.on.crop.png` |

The glue count reads a folio followed by more text on one line, which is a defect only where the design puts the folio at the end of the record. A contents page that sets the folio at the head of its entry scores on it in both arms and the equal counts are the tell; the crops are what to read for those pages.

## e. The recovery against the finder's own lines

| sample | paragraphs | exact | under split | over split |
| --- | --- | --- | --- | --- |
| Courier-en | 35 | 29 | 6 | 0 |
| FD-en-v2 | 117 | 109 | 8 | 0 |
| Vogue-en | 38 | 28 | 5 | 5 |

## f. The ruled names against the split surface

14 ruled pair(s). Reached no request with the switch down: ['CourierT H E UNESCO', 'Katerina Markelova']; with it up: ['CourierT H E UNESCO', 'Katerina Markelova']. Lost by the split: none; gained: none.

12 of them stand on a declared page: ['Anna Ruohonen', 'Chimamanda Ngozi Adichie', 'CourierT H E UNESCO', 'Daniel Robinson', 'David Jefferson', 'Du Junzhi', 'Jim Al-Khalili', 'Lagipoiva Cherelle Jackson', 'Marcelo Silva de Sousa', 'Ora Marek-Martinez', 'Sisco Auala', 'Yang Sha']. Set across a source line boundary, and so never one string for the matcher to find either before or after the split: ['CourierT H E UNESCO'].

| ruled pair | requests reached, off | requests reached, on |
| --- | --- | --- |
| Anna Ruohonen | 1 | 1 |
| Chimamanda Ngozi Adichie | 1 | 1 |
| CourierT H E UNESCO | 0 | 0 |
| Daniel Robinson | 2 | 2 |
| David Jefferson | 2 | 2 |
| Du Junzhi | 1 | 1 |
| Jim Al-Khalili | 1 | 1 |
| Katerina Markelova | 0 | 0 |
| Lagipoiva Cherelle Jackson | 2 | 2 |
| Marcelo Silva de Sousa | 2 | 2 |
| Ora Marek-Martinez | 1 | 1 |
| Sisco Auala | 1 | 1 |
| The UNESCO Courier | 5 | 4 |
| Yang Sha | 1 | 1 |

## The fifth defect, as an observation

Paragraph labels on the diagnosed page: {'abandon': 3, 'fallback_line': 3, 'plain text': 34, 'title': 10}; 11 curve(s) drawn. The split writes no grouping field, so which entry belongs under which section rule is as unrecoverable from the layout as it was.

## For the next batch: where the ruled drop caps stand

3 paragraph(s) the ruling flattened, 0 of them on a page this batch declares. Pages the heading policy changed something on: [1, 4, 5, 6, 7, 8].

| paragraph | page | ruling | page declared | page split | heading policy touched the page | still a candidate |
| --- | --- | --- | --- | --- | --- | --- |
| p4#3 | 4 | flatten | False | False | True | True |
| p5#5 | 5 | flatten | False | False | True | True |
| p7#8 | 7 | flatten | False | False | True | True |

## The frozen fixture

- `examples/output/b9_3/fixtures/Courier-en.p1.checkpoints.zip` (35 paragraphs)
- `examples/output/b9_3/fixtures/Courier-en.line_split.report.json`
- `examples/output/b9_3/fixtures/FD-en-v2.line_split.report.json`
- `examples/output/b9_3/fixtures/Vogue-en.line_split.report.json`
