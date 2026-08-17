# B9.2 acceptance: the heading policy over five samples

Three arms per sample, the same stack in all three. Two of them differ in one attribute; the third repeats the first, and is what says how much a run differs from itself.

## The arms

| sample | translated | typeset | control quiet | pages differing | unattributable | stray |
| --- | --- | --- | --- | --- | --- | --- |
| AramcoWorld-en-v2 | DIFFERS | DIFFERS | no | 7 of 9 | [2, 3, 4, 5, 6, 7, 8] | none |
| CERNCourier-en | same | same | no | 3 of 4 | [1, 2, 4] | none |
| Courier-en | same | same | yes | 5 of 8 | none | none |
| FD-en-v2 | same | same | yes | 2 of 9 | [5] | none |
| Vogue-en | same | same | yes | 1 of 3 | none | none |

## Cost

| arm | requests | cache hits | API calls | prompt tokens | completion tokens | seconds |
| --- | --- | --- | --- | --- | --- | --- |
| off | 303 | 103 | 200 | 209672 | 29977 | 1075.6 |
| control | 292 | 266 | 26 | 45249 | 5167 | 1833.7 |
| on | 295 | 274 | 21 | 36415 | 3432 | 2022.1 |

The repair loop's decision bypasses the cache by design and is what the arm with the switch up is charged for: 6 call(s) of 21.

## a. The doubled headline

AramcoWorld-en-v2 page 5, heading(s) ['p5#17'].
- p5#17: laid out as 4 run(s), 2 dropped.

| arm | display band width (pt) | ink pixels in the off arm's band |
| --- | --- | --- |
| off | 519.85 | 28867 |
| on | 259.93 | 28867 |
| f1 | 474.84 | 71691 |

Band with the switch up over band with it down: 0.5. The layer that was dropped was drawing something a reader could see: False. On this page it is painted with a gradient pattern that lands white on white, so the defect it leaves here is doubled text rather than a visible ghost; the F1 raster beside these is the page the visible one was reported from.

What the two layers were: a solid layer under a gradient layer, read as one headline. Kept: the solid layer. Given up: the gradient overlay. The fix that keeps both is deduplicating before the translation, which this batch does not do because it would change the text a heading is translated as.

- off_page: `examples/output/b9_2/raster/ghost.p5.off.png`
- off_crop: `examples/output/b9_2/raster/ghost.p5.off.crop.png`
- on_page: `examples/output/b9_2/raster/ghost.p5.on.png`
- on_crop: `examples/output/b9_2/raster/ghost.p5.on.crop.png`
- f1_page: `examples/output/b9_2/raster/ghost.p5.f1.png`
- f1_crop: `examples/output/b9_2/raster/ghost.p5.f1.crop.png`

## b. The cover headings

CERNCourier-en page 1, frame [0.0, 0.0, 1024.0, 768.0].
Wrapped before: ['p1#2', 'p1#3']. Still wrapped: none.
Glyph boxes past the frame: off 9, on 10; worst overhang off 44.31pt, on 32.3pt.

**Open, not closed by this batch**: a display heading draws past the top edge of the page. the layout anchors a paragraph's first line at the top of its box less the modal height of its units, and this paragraph carries a masthead and the credit line beside it, so the anchor follows the credit and the masthead stands above it. the scale that would bring the glyph box under the edge is far below the floor, and shrinking a masthead to a quarter of its size to fit a frame is not setting a heading; containment against the page edge is a collision question.

- off_page: `examples/output/b9_2/raster/cover.p1.off.png`
- off_crop: `examples/output/b9_2/raster/cover.p1.off.crop.png`
- on_page: `examples/output/b9_2/raster/cover.p1.on.png`
- on_crop: `examples/output/b9_2/raster/cover.p1.on.crop.png`

## c. Every heading of the ruled sample

25 heading(s), 25 accounted for, 0 not.
Ruled terms added by the revision: 8, carried into the glossary: 8, never matched by a request: ['Katerina Markelova'].

| ruled term | prompts matched |
| --- | --- |
| Anna Ruohonen | 1 |
| Chimamanda Ngozi Adichie | 1 |
| Du Junzhi | 1 |
| Jim Al-Khalili | 1 |
| Katerina Markelova | 0 |
| Ora Marek-Martinez | 1 |
| Sisco Auala | 1 |
| Yang Sha | 1 |

## d. Every heading that reached the floor

| sample | page | heading | scale asked for | floor | lines | disposition |
| --- | --- | --- | --- | --- | --- | --- |
| AramcoWorld-en-v2 | 4 | p4#12 | 0.3447 | 0.55 | 3 | escalate |
| AramcoWorld-en-v2 | 8 | p8#11 | 0.3556 | 0.55 | 3 | escalate |
| AramcoWorld-en-v2 | 9 | p9#13 | 0.5245 | 0.55 | 2 | escalate |
| Courier-en | 4 | p4#17 | 0.4583 | 0.55 | 3 | escalate |
| Courier-en | 7 | p7#17 | 0.5428 | 0.55 | 2 | escalate |
| FD-en-v2 | 3 | p3#19 | 0.333 | 0.55 | 3 | escalate |
| FD-en-v2 | 5 | p5#29 | 0.5833 | 0.55 | 2 | escalate |
| FD-en-v2 | 6 | p6#10 | 0.4544 | 0.55 | 3 | escalate |

## e. Does a doubled heading reach M3

Samples carrying a doubled heading: 2. Contaminated: none.

## The frozen fixture

- `examples/output/b9_2/fixtures/AramcoWorld-en-v2.titles.xml`
- `examples/output/b9_2/fixtures/AramcoWorld-en-v2.title_typeset.report.json`

## Faults

- none
