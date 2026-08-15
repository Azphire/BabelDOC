# batch-e1.2 evaluation results

Computed by `tools/eval_report.py --corpus` over frozen artefacts. No translation was run and no model request was made.

## 1. Headline table

| sample | run | path | MBR linkable | MBR all | inherited open | conserved | LTCR | Overlap delta | Alignment delta | image IoU | page delta |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Courier-en.pdf | upstream | pdf_extraction | 0.2000 | 0.4286 | 2 | yes | - | -0.0399 | 0.0031 | 1.0000 | 0 |
| Courier-en.pdf | fork_full_il | intermediate_language | 0.4000 | 0.5714 | 2 | yes | 0.4464 | 0.0000 | 0.0000 | 1.0000 | 0 |
| Courier-en.pdf | fork_full_pdf | pdf_extraction | 0.2000 | 0.4286 | 2 | yes | - | -0.0410 | 0.0034 | 1.0000 | 0 |
| Vogue-en.pdf | upstream | pdf_extraction | - | 0.0000 | 0 | yes | - | 0.0000 | 0.0000 | 1.0000 | 0 |
| Vogue-en.pdf | fork_full_il | intermediate_language | - | 0.0000 | 0 | yes | - | 0.0000 | 0.0000 | 1.0000 | 0 |
| Vogue-en.pdf | fork_full_pdf | pdf_extraction | - | 0.0000 | 0 | yes | - | 0.0000 | 0.0000 | 1.0000 | 0 |
| CERNCourier-en.pdf | upstream | pdf_extraction | 0.6667 | 0.6667 | 0 | yes | - | -0.0469 | -0.0000 | 0.9997 | 0 |
| CERNCourier-en.pdf | fork_full_il | intermediate_language | 0.6667 | 0.6667 | 0 | yes | 0.8182 | 0.0001 | 0.0000 | 1.0000 | 0 |
| CERNCourier-en.pdf | fork_full_pdf | pdf_extraction | 0.6667 | 0.6667 | 0 | yes | - | -0.0570 | -0.0000 | 0.9997 | 0 |
| AramcoWorld-en-v2.pdf | upstream | pdf_extraction | 0.2857 | 0.3750 | 1 | yes | - | 0.1197 | 0.0005 | 0.9606 | 0 |
| AramcoWorld-en-v2.pdf | fork_full_il | intermediate_language | 0.0000 | 0.1250 | 1 | yes | 0.7246 | 0.0000 | 0.0000 | 1.0000 | 0 |
| AramcoWorld-en-v2.pdf | fork_full_pdf | pdf_extraction | 0.1429 | 0.2500 | 1 | yes | - | 0.1157 | 0.0004 | 0.9606 | 0 |
| FD-en-v2.pdf | upstream | pdf_extraction | 0.6250 | 0.6250 | 0 | yes | - | -0.0587 | 0.0030 | 1.0000 | 0 |
| FD-en-v2.pdf | fork_full_il | intermediate_language | 0.2857 | 0.2500 | 0 | yes | 0.0833 | 0.0006 | 0.0000 | 1.0000 | 0 |
| FD-en-v2.pdf | fork_full_pdf | pdf_extraction | 0.6250 | 0.6250 | 0 | yes | - | -0.0596 | 0.0015 | 1.0000 | 0 |
| Courier-zh.pdf | upstream | pdf_extraction | 0.3333 | 0.2857 | 0 | yes | - | 0.0084 | 0.0017 | 1.0000 | 0 |
| Courier-zh.pdf | fork_full_il | intermediate_language | 0.5000 | 0.5714 | 1 | yes | - | -0.0000 | 0.0000 | 1.0000 | 0 |
| Courier-zh.pdf | fork_full_pdf | pdf_extraction | 0.5000 | 0.5714 | 1 | yes | - | 0.0000 | 0.0012 | 1.0000 | 0 |

## 2. Mid-unit page-break rate, stratum by stratum

`linked` is a boundary the corpus adjudicated as cutting a semantic unit, `trap` one whose continuation is outside the excerpt and which therefore no producer can close, `clean` the rest.

| sample | run | linked open/answerable | trap open/answerable | clean open/answerable | axis unsupported | vertical paragraphs | no tail |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Courier-en.pdf | upstream | 0/2 | 2/2 | 1/3 | 0 | 3 | 0 |
| Courier-en.pdf | fork_full_il | 0/2 | 2/2 | 2/3 | 0 | 3 | 0 |
| Courier-en.pdf | fork_full_pdf | 0/2 | 2/2 | 1/3 | 0 | 3 | 0 |
| Vogue-en.pdf | upstream | 0/0 | 0/0 | 0/0 | 0 | 3 | 2 |
| Vogue-en.pdf | fork_full_il | 0/0 | 0/0 | 0/0 | 0 | 2 | 2 |
| Vogue-en.pdf | fork_full_pdf | 0/0 | 0/0 | 0/0 | 0 | 3 | 2 |
| CERNCourier-en.pdf | upstream | 0/0 | 0/0 | 2/3 | 0 | 3 | 0 |
| CERNCourier-en.pdf | fork_full_il | 0/0 | 0/0 | 2/3 | 0 | 3 | 0 |
| CERNCourier-en.pdf | fork_full_pdf | 0/0 | 0/0 | 2/3 | 0 | 3 | 0 |
| AramcoWorld-en-v2.pdf | upstream | 1/1 | 1/1 | 1/6 | 0 | 3 | 0 |
| AramcoWorld-en-v2.pdf | fork_full_il | 0/1 | 1/1 | 0/5 | 0 | 3 | 1 |
| AramcoWorld-en-v2.pdf | fork_full_pdf | 0/1 | 1/1 | 1/6 | 0 | 3 | 0 |
| FD-en-v2.pdf | upstream | 0/0 | 0/0 | 5/8 | 0 | 3 | 0 |
| FD-en-v2.pdf | fork_full_il | 0/0 | 0/0 | 2/7 | 0 | 5 | 1 |
| FD-en-v2.pdf | fork_full_pdf | 0/0 | 0/0 | 5/8 | 0 | 3 | 0 |
| Courier-zh.pdf | upstream | 1/2 | 0/1 | 1/4 | 0 | 3 | 0 |
| Courier-zh.pdf | fork_full_il | 1/2 | 1/1 | 2/4 | 0 | 6 | 0 |
| Courier-zh.pdf | fork_full_pdf | 1/2 | 1/1 | 2/4 | 0 | 3 | 0 |

## 3. Every adjudicated boundary, verdict by verdict

| sample | boundary | truth | upstream | fork_full_il | fork_full_pdf |
| --- | --- | --- | --- | --- | --- |
| Courier-en.pdf | 1->2 | clean | closed | open | closed |
| Courier-en.pdf | 2->3 | linked | closed | closed | closed |
| Courier-en.pdf | 3->4 | clean | open | open | open |
| Courier-en.pdf | 4->5 | clean | closed | closed | closed |
| Courier-en.pdf | 5->6 | trap | open | open | open |
| Courier-en.pdf | 6->7 | trap | open | open | open |
| Courier-en.pdf | 7->8 | linked | closed | closed | closed |
| Vogue-en.pdf | 1->2 | clean | no_tail | no_tail | no_tail |
| Vogue-en.pdf | 2->3 | clean | no_tail | no_tail | no_tail |
| CERNCourier-en.pdf | 1->2 | clean | open | open | open |
| CERNCourier-en.pdf | 2->3 | clean | open | open | open |
| CERNCourier-en.pdf | 3->4 | clean | closed | closed | closed |
| AramcoWorld-en-v2.pdf | 1->2 | clean | open | no_tail | open |
| AramcoWorld-en-v2.pdf | 2->3 | clean | closed | closed | closed |
| AramcoWorld-en-v2.pdf | 3->4 | clean | closed | closed | closed |
| AramcoWorld-en-v2.pdf | 4->5 | clean | closed | closed | closed |
| AramcoWorld-en-v2.pdf | 5->6 | clean | closed | closed | closed |
| AramcoWorld-en-v2.pdf | 6->7 | linked | open | closed | closed |
| AramcoWorld-en-v2.pdf | 7->8 | trap | open | open | open |
| AramcoWorld-en-v2.pdf | 8->9 | clean | closed | closed | closed |
| FD-en-v2.pdf | 1->2 | clean | open | no_tail | open |
| FD-en-v2.pdf | 2->3 | clean | open | open | open |
| FD-en-v2.pdf | 3->4 | clean | open | open | open |
| FD-en-v2.pdf | 4->5 | clean | closed | closed | closed |
| FD-en-v2.pdf | 5->6 | clean | open | closed | open |
| FD-en-v2.pdf | 6->7 | clean | closed | closed | closed |
| FD-en-v2.pdf | 7->8 | clean | open | closed | open |
| FD-en-v2.pdf | 8->9 | clean | closed | closed | closed |
| Courier-zh.pdf | 1->2 | clean | closed | open | open |
| Courier-zh.pdf | 2->3 | linked | closed | closed | closed |
| Courier-zh.pdf | 3->4 | clean | open | open | open |
| Courier-zh.pdf | 4->5 | clean | closed | closed | closed |
| Courier-zh.pdf | 5->6 | trap | closed | open | open |
| Courier-zh.pdf | 6->7 | clean | closed | closed | closed |
| Courier-zh.pdf | 7->8 | linked | open | open | open |

## 4. Geometry method difference, on the fork product

The same produced PDF measured down both paths. `comparable` is the relative deviation against the declared bound; a metric that fails it may not be read across the two paths.

| sample | metric | IL path | PDF path | relative delta | comparable |
| --- | --- | --- | --- | --- | --- |
| Courier-en.pdf | alignment_delta | 0.0000 | 0.0034 | 1.0000 | no |
| Courier-en.pdf | alignment_produced | 0.0026 | 0.0059 | 0.5499 | no |
| Courier-en.pdf | alignment_source | 0.0026 | 0.0024 | 0.0759 | yes |
| Courier-en.pdf | image_area_delta | 0.0000 | -0.0000 | 0.0000 | yes |
| Courier-en.pdf | image_placement_iou | 1.0000 | 1.0000 | 0.0000 | yes |
| Courier-en.pdf | overlap_delta | 0.0000 | -0.0410 | 1.0000 | no |
| Courier-en.pdf | overlap_produced | 0.0188 | 0.0030 | 0.8426 | no |
| Courier-en.pdf | overlap_source | 0.0188 | 0.0439 | 0.5714 | no |
| Courier-en.pdf | mid_break_rate.rate | 0.5714 | 0.4286 | 0.2500 | no |
| Vogue-en.pdf | alignment_delta | 0.0000 | 0.0000 | 1.0000 | no |
| Vogue-en.pdf | alignment_produced | 0.0028 | 0.0003 | 0.8994 | no |
| Vogue-en.pdf | alignment_source | 0.0028 | 0.0002 | 0.9126 | no |
| Vogue-en.pdf | image_area_delta | 0.0000 | -0.0000 | 0.0000 | yes |
| Vogue-en.pdf | image_placement_iou | 1.0000 | 1.0000 | 0.0000 | yes |
| Vogue-en.pdf | overlap_delta | 0.0000 | 0.0000 | 0.0000 | yes |
| Vogue-en.pdf | overlap_produced | 0.1258 | 0.0000 | 1.0000 | no |
| Vogue-en.pdf | overlap_source | 0.1258 | 0.0000 | 1.0000 | no |
| Vogue-en.pdf | mid_break_rate.rate | 0.0000 | 0.0000 | 0.0000 | yes |
| CERNCourier-en.pdf | alignment_delta | 0.0000 | -0.0000 | 1.2000 | no |
| CERNCourier-en.pdf | alignment_produced | 0.0001 | 0.0002 | 0.3984 | no |
| CERNCourier-en.pdf | alignment_source | 0.0001 | 0.0003 | 0.4549 | no |
| CERNCourier-en.pdf | image_area_delta | 0.0000 | 0.0003 | 1.0000 | no |
| CERNCourier-en.pdf | image_placement_iou | 1.0000 | 0.9997 | 0.0003 | yes |
| CERNCourier-en.pdf | overlap_delta | 0.0001 | -0.0570 | 1.0021 | no |
| CERNCourier-en.pdf | overlap_produced | 0.1635 | 0.3401 | 0.5191 | no |
| CERNCourier-en.pdf | overlap_source | 0.1634 | 0.3970 | 0.5884 | no |
| CERNCourier-en.pdf | mid_break_rate.rate | 0.6667 | 0.6667 | 0.0000 | yes |
| AramcoWorld-en-v2.pdf | alignment_delta | 0.0000 | 0.0004 | 1.0000 | no |
| AramcoWorld-en-v2.pdf | alignment_produced | 0.0022 | 0.0011 | 0.4891 | no |
| AramcoWorld-en-v2.pdf | alignment_source | 0.0022 | 0.0007 | 0.6802 | no |
| AramcoWorld-en-v2.pdf | image_area_delta | 0.0000 | -0.0045 | 1.0000 | no |
| AramcoWorld-en-v2.pdf | image_placement_iou | 1.0000 | 0.9606 | 0.0394 | yes |
| AramcoWorld-en-v2.pdf | overlap_delta | 0.0000 | 0.1157 | 1.0000 | no |
| AramcoWorld-en-v2.pdf | overlap_produced | 0.0491 | 0.4323 | 0.8865 | no |
| AramcoWorld-en-v2.pdf | overlap_source | 0.0491 | 0.3166 | 0.8451 | no |
| AramcoWorld-en-v2.pdf | mid_break_rate.rate | 0.1250 | 0.2500 | 0.5000 | no |
| FD-en-v2.pdf | alignment_delta | 0.0000 | 0.0015 | 0.9960 | no |
| FD-en-v2.pdf | alignment_produced | 0.0013 | 0.0021 | 0.4063 | no |
| FD-en-v2.pdf | alignment_source | 0.0013 | 0.0006 | 0.4940 | no |
| FD-en-v2.pdf | image_area_delta | 0.0000 | -0.0000 | 0.0000 | yes |
| FD-en-v2.pdf | image_placement_iou | 1.0000 | 1.0000 | 0.0000 | yes |
| FD-en-v2.pdf | overlap_delta | 0.0006 | -0.0596 | 1.0101 | no |
| FD-en-v2.pdf | overlap_produced | 0.1532 | 0.2994 | 0.4882 | no |
| FD-en-v2.pdf | overlap_source | 0.1526 | 0.3589 | 0.5748 | no |
| FD-en-v2.pdf | mid_break_rate.rate | 0.2500 | 0.6250 | 0.6000 | no |
| Courier-zh.pdf | alignment_delta | 0.0000 | 0.0012 | 1.0000 | no |
| Courier-zh.pdf | alignment_produced | 0.0037 | 0.0049 | 0.2453 | no |
| Courier-zh.pdf | alignment_source | 0.0037 | 0.0037 | 0.0000 | yes |
| Courier-zh.pdf | image_area_delta | 0.0000 | -0.0000 | 0.0000 | yes |
| Courier-zh.pdf | image_placement_iou | 1.0000 | 1.0000 | 0.0000 | yes |
| Courier-zh.pdf | overlap_delta | -0.0000 | 0.0000 | 1.0000 | no |
| Courier-zh.pdf | overlap_produced | 0.0258 | 0.0000 | 1.0000 | no |
| Courier-zh.pdf | overlap_source | 0.0258 | 0.0000 | 1.0000 | no |
| Courier-zh.pdf | mid_break_rate.rate | 0.5714 | 0.5714 | 0.0000 | yes |

| sample | boundary verdict agreement | IL elements | PDF elements |
| --- | --- | --- | --- |
| Courier-en.pdf | 6/7 | 140 | 199 |
| Vogue-en.pdf | 2/2 | 43 | 62 |
| CERNCourier-en.pdf | 3/3 | 217 | 255 |
| AramcoWorld-en-v2.pdf | 7/8 | 165 | 283 |
| FD-en-v2.pdf | 5/8 | 211 | 210 |
| Courier-zh.pdf | 7/7 | 142 | 154 |
