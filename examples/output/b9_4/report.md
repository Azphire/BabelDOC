# B9.4 acceptance: the drop cap ruling, consumed

Three arms per sample, the same stack in all three. Two of them differ in one attribute, `magazine_drop_cap_apply`; the third repeats the first and is what says how much a run differs from itself.

## Cost

| arm | requests | cache hits | API calls | prompt tokens | completion tokens | seconds |
| --- | --- | --- | --- | --- | --- | --- |
| off | 125 | 122 | 3 | 14371 | 198 | 570.2 |
| control | 125 | 122 | 3 | 14355 | 227 | 635.3 |
| on | 125 | 118 | 7 | 19913 | 1339 | 339.9 |

## a. Every site a verdict reached

What each request carried, read out of the translator's own tracking file.

| sample | paragraph | verdict | from | initial | ratio | merged | separator dropped | offered, off | offered, on |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Courier-en | `p4#3` | flatten | ruled | `L` | 6.6683 | True | 1 | `<style id='1'>L </style>ong before satellites ` | `Long before satellites orbited Earth, Polynesi` |
| Courier-en | `p5#5` | flatten | ruled | `O` | 6.6683 | True | 1 | `<style id='1'>O </style>n the Purus River, as ` | `On the Purus River, as the light fades and the` |
| Courier-en | `p7#8` | flatten | ruled | `T` | 6.6683 | True | 1 | `<style id='1'>T </style>here is a huge diversi` | `There is a huge diversity of Indigenous People` |
| FD-en-v2 | `p8#9` | flatten | default | `W` | 4.255 | True | 0 | `{v1}it comes to international trade, countries` | `When it comes to international trade, countrie` |

What came back, and how large the paragraph's opening glyph is once the document has been laid out. The last three columns are the typographic claim: an initial that survived is several times the body size, and the median column is the body size of that same paragraph.

| sample | paragraph | translated, off | opens in | translated, on | opens in | opening glyph, off | opening glyph, on | median glyph, on |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Courier-en | `p4#3` | `<style id='1'>很 </style>久以前，在卫星环绕地球之前，波利尼西亚航海家` | target | `早在卫星环绕地球运行之前，波利尼西亚航海家就通过观察星星、海浪、生物发光现象和海鸟飞行模式，` | target | 55.21 | 9.2 | 9.2 |
| Courier-en | `p5#5` | `<style id='1'>在</style>普鲁斯河上，当光线渐渐消退，热气仍在水面上徘徊` | target | `在普鲁斯河上，光线渐渐消退，热气仍然笼罩着水面，一条巨骨舌鱼浮出水面，吸了一口空气。这种声音` | target | 55.21 | 9.2 | 9.2 |
| Courier-en | `p7#8` | `<style id='1'>T </style>世界上有着多样化的土著人民、文化、语言和知识` | target | `世界上有着多样化的土著人民、文化、语言和知识体系。这些体系经过数百年或数千年的发展，对我们所` | target | 61.35 | 9.2 | 9.2 |
| FD-en-v2 | `p8#9` | `{v1}在国际贸易方面，各国一直在经济效率与国家安全之间进行权衡。第二次世界大战后，他们通过` | target | `在国际贸易方面，各国一直在经济效率与国家安全之间进行权衡。第二次世界大战后，他们通过低关税追` | target | 39.36 | 9.25 | 9.25 |

The crops, one pair per site:

- `Courier-en` `p4#3` page 4: off `examples/output/b9_4/raster/Courier-en.p4_3.off.png`, on `examples/output/b9_4/raster/Courier-en.p4_3.on.png`
- `Courier-en` `p5#5` page 5: off `examples/output/b9_4/raster/Courier-en.p5_5.off.png`, on `examples/output/b9_4/raster/Courier-en.p5_5.on.png`
- `Courier-en` `p7#8` page 7: off `examples/output/b9_4/raster/Courier-en.p7_8.off.png`, on `examples/output/b9_4/raster/Courier-en.p7_8.on.png`
- `FD-en-v2` `p8#9` page 8: off `examples/output/b9_4/raster/FD-en-v2.p8_9.off.png`, on `examples/output/b9_4/raster/FD-en-v2.p8_9.on.png`

## b. Outside the paragraphs a verdict reached

The soul assertion, and the two channels b9.3 found carrying a page level change out of the page it happened on. Both are measured here rather than assumed: the merge runs after the term extractor has read the document, so the automatic glossary is built from the same text in every arm, and the merge changes no paragraph count, so the requests are composed the same way.

| sample | pages | ruled pages | text moved | outside ruled | control moved | raster moved | outside ruled | control raster moved |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Courier-en | 8 | [4, 5, 7] | [4, 5, 7] | none | none | [4, 5, 7] | none | none |
| FD-en-v2 | 9 | [8] | [8] | none | none | [5, 8] | [5] | none |

One page rendered differently outside a ruled page, and it is accounted for rather than smoothed away. The repair loop asks a model which findings to act on, that request is not served from the cache, and the three arms chose differently; a finding the loop resolved in one arm and not in another is a rendered difference on a page the merge never touched. The control arm chose a third set and happened to resolve the same findings as the base arm, which is why the floor did not reveal the variance and why the mechanism is read out of the loop's own record.

| sample | page | translated text moved | resolved, base arm | resolved, subject arm | attribution |
| --- | --- | --- | --- | --- | --- |
| FD-en-v2 | 5 | False | 2 | 1 | the translated document is identical on this page; the repair loop resolved ['untranslated_residue:p5:p5#24'] in the base arm and [] in the subject arm, on an uncached decision |

And the two channels, entry by entry and request by request:

| sample | glossary entries, off | on | identical | entries differing | requests, off | on | composition identical |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Courier-en | 146 | 146 | True | 0 | 27 | 27 | True |
| FD-en-v2 | 149 | 149 | True | 0 | 25 | 25 | True |

The repair loop's own answer, arm by arm:

| sample | arm | iterations | action and findings chosen | resolved | from cache |
| --- | --- | --- | --- | --- | --- |
| Courier-en | off | 1 | none(0) | 0 | [False] |
| Courier-en | control | 1 | translate_orphan_lines(1) | 0 | [False] |
| Courier-en | on | 1 | none(0) | 0 | [False] |
| FD-en-v2 | off | 2 | translate_orphan_lines(2); none(0) | 2 | [False] |
| FD-en-v2 | control | 2 | translate_orphan_lines(3); translate_orphan_lines(1) | 2 | [False] |
| FD-en-v2 | on | 2 | translate_orphan_lines(1); none(0) | 1 | [False] |

### What the detectors see

The F1 review recorded these defects by eye. Whether this project's own detectors see them is a different question, and the answer is on the record either way: a collision between an oversized initial and the text beside it is not a kind any shipped detector reports, so the counts below are the surrounding findings rather than the defect itself.

| sample | arm | issues | by kind | on ruled pages | naming a ruled paragraph |
| --- | --- | --- | --- | --- | --- |
| Courier-en | off | 13 | {"fragment_cluster": 1, "untranslated_residue": 12} | {"untranslated_residue": 3} | 0 |
| Courier-en | control | 13 | {"fragment_cluster": 1, "untranslated_residue": 12} | {"untranslated_residue": 3} | 0 |
| Courier-en | on | 13 | {"fragment_cluster": 1, "untranslated_residue": 12} | {"untranslated_residue": 3} | 0 |
| FD-en-v2 | off | 41 | {"fragment_cluster": 9, "untranslated_residue": 32} | {"untranslated_residue": 2} | 0 |
| FD-en-v2 | control | 41 | {"fragment_cluster": 9, "untranslated_residue": 32} | {"untranslated_residue": 2} | 0 |
| FD-en-v2 | on | 42 | {"fragment_cluster": 9, "untranslated_residue": 33} | {"untranslated_residue": 2} | 0 |

## c. The candidates, and the one F1 found that the signal used to miss

| sample | paragraph | page | article | rank | opens article | ratio | initial | ruled |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Courier-en | `p4#3` | 4 | wMG4a | 3 | False | 6.6683 | `L` | flatten |
| Courier-en | `p5#5` | 5 | RyecR | 5 | True | 6.6683 | `O` | flatten |
| Courier-en | `p7#8` | 7 | 8MdmY | 5 | True | 6.6683 | `T` | flatten |
| FD-en-v2 | `p8#9` | 8 | SgQhb | 2 | True | 4.255 | `W` | unruled |

An unruled candidate is acted on under the default its target language declares, which is what the `from` column of section a records as `default`. The ruling on such a candidate is the user's, and the draft for it is `examples/output/b9_4/reviews/FD-en-v2.review.json`.

## d. Vogue-en page 3, where F1 recorded two Latin residues

Read from the frozen `examples/output/b9_3/on/Vogue-en/work/Vogue-en`, which is the last run that put the line structure switch up on this sample. Candidates the signal finds on the page: none. Pages that run declared for line splitting: [3].

| paragraph | text | label | characters | candidate | why not |
| --- | --- | --- | --- | --- | --- |
| `p3#10` | `NAD` | title | 3 | False | labelled title; page belongs to no article; ratio 1.0 below 2.0 |
| `p3#12` | `i` | title | 1 | False | labelled title; page belongs to no article; ratio 1.0 below 2.0 |
| `p3#13` | `n` | plain text | 1 | False | page belongs to no article; ratio 1.0 below 2.0 |
| `p3#14` | `f` | title | 1 | False | labelled title; page belongs to no article; ratio 1.0 below 2.0 |
| `p3#15` | `us` | plain text | 2 | False | page belongs to no article; ratio 1.0 below 2.0 |
| `p3#16` | `i` | title | 1 | False | labelled title; page belongs to no article; ratio 1.0 below 2.0 |
| `p3#35` | `Wh` | title | 2 | False | labelled title; page belongs to no article; ratio 1.0 below 2.0 |
| `p3#36` | `e` | plain text | 1 | False | page belongs to no article; ratio 1.0 below 2.0 |
| `p3#37` | `th` | title | 2 | False | labelled title; page belongs to no article; ratio 1.0 below 2.0 |

These are fragments, not paragraphs opening with an initial: a residue of two characters standing on its own is outside the candidate signal by construction rather than by threshold, because the signal reads a paragraph's opening against that paragraph's own body text and a fragment has none. Nothing in this batch changes them, and the observation is recorded rather than answered.

## The frozen fixture

- `examples/output/b9_4/fixtures/Courier-en.checkpoints.zip`
- `examples/output/b9_4/fixtures/Courier-en.drop_cap.report.json`
- `examples/output/b9_4/fixtures/Courier-en.drop_cap_apply.report.json`
- `examples/output/b9_4/fixtures/FD-en-v2.checkpoints.zip`
- `examples/output/b9_4/fixtures/FD-en-v2.drop_cap.report.json`
- `examples/output/b9_4/fixtures/FD-en-v2.drop_cap_apply.report.json`

