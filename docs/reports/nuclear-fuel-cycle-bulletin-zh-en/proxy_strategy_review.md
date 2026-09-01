# Nuclear Fuel Cycle Bulletin whole-issue proxy strategy review

## Scope and run identity

- Status: proxy strategy decisions complete; formal translation not yet started.
- Code HEAD: `f7d0904ca14b9aae07df9d38117867857add9f10` (`docs(nea): record whole-issue recovery run`).
- Branch: `migration/minimal-v0.6.4`.
- Input: `examples/input/nuclear-fuel-cycle-bulletin-zh.pdf`.
- Direction/config: Chinese to English (`zh -> en`), `minimal.zh-en.toml`.
- Input identity: 36 pages, 16,884,507 bytes, SHA-256 `189bff3bf92e359c74476514b47a6608f7ef1a07bc585ff8ede77a356d7c363d`.
- Extractable-text gate: 35/36 pages contain at least 20 extracted characters (97.22%); `--auto-enable-ocr-workaround` was not enabled.
- Review command: `.\.venv\Scripts\babeldoc.exe --config minimal.zh-en.toml --files examples\input\nuclear-fuel-cycle-bulletin-zh.pdf --output examples\output\nuclear-fuel-cycle-bulletin-zh-en\review-export --working-dir examples\output\nuclear-fuel-cycle-bulletin-zh-en\review-export\work --skip-translation`.
- Review timing: 2026-09-01T11:14:53.4545349+01:00 to 2026-09-01T11:17:42.1462914+01:00 (168.69 seconds); exit code 0.
- Review sidecars: complete v3 draft, 36/36 VLM page classifications accepted, 543 classified/excluded elements over 36 pages, 20 chains/40 members, one drop-cap candidate, zero ordinary/chain/repair translation requests, and zero translation/term-extraction tokens.
- Input SHA-256 after review remained unchanged.

The review covered the complete source contact sheet (12 physical pages per sheet) and enlarged source pages where article boundaries, mixed-module layouts, career profiles, news briefs, publication furniture, or the blank rear leaf needed closer inspection. This is a source-structure and translation-strategy review only. It is not a visual or linguistic acceptance of the future translated PDF.

The fixed English terminology was also cross-checked against the IAEA's official English issue and relevant official article pages:

- <https://www.iaea.org/bulletin/67-1>
- <https://www.iaea.org/bulletin/nuclear-fuels-innovation-continues>
- <https://www.iaea.org/bulletin/ensuring-the-safety-of-nuclear-fuel-cycle-facilities>
- <https://www.iaea.org/bulletin/safeguarding-the-nuclear-fuel-cycle>
- <https://www.iaea.org/bulletin/a-sustainable-solution-for-spent-fuel-and-high-level-waste-disposal>

## Page-kind proxy decisions

The decisions cover every physical page. `Machine result` records the final review classifier output; all sources were VLM and none used fallback. Only page 2 reported a secondary kind (`toc`: "The page contains several independent modules and a contents index.").

| Physical page | Machine result | Proxy kind | Disposition | Source-layout evidence |
| ---: | --- | --- | --- | --- |
| 1 | `front_cover`, 1.00 | `front_cover` | `accept_vlm` | Issue masthead, dominant cover artwork and thematic cover lines. |
| 2 | `toc`, 0.90; secondary `toc` | `toc` | `accept_vlm` | Contents entries repeatedly pair titles with page numbers; quiz is a secondary module. |
| 3 | `article_body`, 0.90 | `editorial` | `override` | Signed Director General foreword with portrait, pull quote and one continuous personal argument. |
| 4 | `article_body`, 0.90 | `infographic` | `override` | First half of a labelled nuclear-fuel-cycle process diagram dominates the page. |
| 5 | `infographic`, 0.90 | `infographic` | `accept_vlm` | Second half of the same numbered process diagram and labelled cycle graphic. |
| 6 | `sidebar_heavy`, 0.90 | `sidebar_heavy` | `accept_vlm` | Opening article material shares the page with independent fuel-type and uranium-data modules. |
| 7 | `sidebar_heavy`, 0.90 | `sidebar_heavy` | `accept_vlm` | Continuation is divided among independent fuel briefs and a large uranium-data panel. |
| 8 | `article_opener`, 0.90 | `article_body` | `override` | AI is a subsection without a byline inside the continuing fuel-innovation article. |
| 9 | `article_body`, 0.85 | `sidebar_heavy` | `override` | Independent LEU Bank feature and IAEA publications promotion form two separate modules. |
| 10 | `article_body`, 0.90 | `article_opener` | `override` | New named HALEU story begins with a large headline, byline and opening prose. |
| 11 | `article_body`, 0.85 | `article_body` | `accept_vlm` | Continuous two-column prose carries the HALEU story forward from page 10. |
| 12 | `article_body`, 0.85 | `article_opener` | `override` | New LEU+ story begins with headline, byline and a decorated opening paragraph. |
| 13 | `article_body`, 0.80 | `article_body` | `accept_vlm` | Running prose continues the LEU+ story without a new story header. |
| 14 | `article_body`, 0.80 | `article_opener` | `override` | New spent-fuel recycling story begins with headline, deck, byline and opening prose. |
| 15 | `article_body`, 0.85 | `article_body` | `accept_vlm` | Country sections and running prose continue the recycling story. |
| 16 | `article_body`, 0.90 | `article_opener` | `override` | New disposal story begins with headline, byline and opening prose. |
| 17 | `article_body`, 0.90 | `article_body` | `accept_vlm` | Running prose and a supporting photograph continue the disposal story. |
| 18 | `infographic`, 0.90 | `infographic` | `accept_vlm` | Uranium energy-density comparison is communicated through labelled quantities and icons. |
| 19 | `infographic`, 0.90 | `infographic` | `accept_vlm` | Fuel-mass and carbon-emission comparison chart is the page's central content. |
| 20 | `article_body`, 0.90 | `article_opener` | `override` | New stakeholder-engagement story begins with headline, byline and opening prose. |
| 21 | `infographic`, 0.90 | `article_body` | `override` | Running prose and one documentary photograph continue the page-20 story; no explanatory graphic dominates. |
| 22 | `article_body`, 0.85 | `article_opener` | `override` | New fuel-cycle-facility safety story begins with headline, two bylines and opening prose. |
| 23 | `article_body`, 0.90 | `article_body` | `accept_vlm` | Running prose and mission photograph continue the safety story. |
| 24 | `article_body`, 0.80 | `article_opener` | `override` | New safeguards story begins with headline, deck, byline and opening prose. |
| 25 | `article_body`, 0.85 | `article_body` | `accept_vlm` | Running prose and inspection photograph continue the safeguards story. |
| 26 | `interview`, 0.85 | `article_opener` | `override` | Nuclear Jobs feature begins with section headline, deck and the first narrative career profile, not alternating Q&A. |
| 27 | `article_body`, 0.90 | `article_body` | `accept_vlm` | Second career profile continues the same Nuclear Jobs feature without a new issue-level story header. |
| 28 | `article_body`, 0.85 | `article_opener` | `override` | IAEA News section opens with a named summit story, display headline, image and byline. |
| 29 | `article_body`, 0.90 | `sidebar_heavy` | `override` | Two independent news stories occupy separate modules on the same page. |
| 30 | `article_body`, 0.90 | `sidebar_heavy` | `override` | One news item ends and another begins, separated by headline and byline furniture. |
| 31 | `article_body`, 0.90 | `sidebar_heavy` | `override` | One news item ends and an independent research-reactor brief begins. |
| 32 | `article_body`, 0.90 | `article_opener` | `override` | IAEA Archives feature begins with section headline, named 1977 story and documentary photographs. |
| 33 | `advertisement`, 0.90 | `advertisement` | `accept_vlm` | Full-page international-conference promotion with dates, branding and call to action. |
| 34 | `contributors`, 0.80 | `masthead` | `override` | Publication credits, address, ISSN/legal text and publisher information occupy the page. |
| 35 | `back_cover`, 1.00 | `back_cover` | `accept_vlm` | Intentional blank rear leaf is retained in the machine's terminal cover-family bucket under the closed taxonomy. |
| 36 | `back_cover`, 0.90 | `back_cover` | `accept_vlm` | Final image-led partnership promotion is the physical back cover. |

Conservation: 36 ruled pages = 17 `accept_vlm` + 19 `override`; 0 fallback pages; page keys are exactly `1..36`.

## Fixed terminology

The glossary is deliberately limited to publication and organization names, recurring nuclear-fuel-cycle terms, and safety/safeguards phrases whose inconsistent rendering would be conspicuous. Every source key matches the captured source text after `Glossary.normalize_source` whitespace normalization.

| Source | Fixed English target | First page | Reason |
| --- | --- | ---: | --- |
| 国际原子能机构通报 | IAEA Bulletin | 2 | Official publication title repeated in contents, footers and imprint. |
| 国际原子能机构 | International Atomic Energy Agency | 2 | Official organization name. |
| 原子能机构 | IAEA | 2 | Repeated short-form reference to the same organization. |
| 经合组织核能机构 | OECD Nuclear Energy Agency | 6 | Fixed institutional name in the uranium-data attribution. |
| 核燃料循环 | nuclear fuel cycle | 1 | Issue theme and the core term repeated throughout the publication. |
| 燃料供应链 | nuclear fuel supply chain | 3 | Recurring supply-chain term central to the foreword and issue theme. |
| 核燃料循环设施 | nuclear fuel cycle facilities | 2 | Recurring facility category used across fuel, safety and safeguards articles. |
| 低浓铀 | low enriched uranium (LEU) | 2 | Recurring fuel category with an official abbreviation. |
| 低浓铀+ | LEU+ | 2 | Distinct recurring enrichment/fuel category. |
| 高丰度低浓铀 | high assay low enriched uranium (HALEU) | 2 | Recurring advanced-fuel category and article subject. |
| 高浓铀 | high enriched uranium (HEU) | 6 | Standard enrichment category contrasted with LEU and HALEU. |
| 混合氧化物 | mixed oxide (MOX) | 6 | Standard recycled-fuel material name and abbreviation. |
| 耐事故/ 先进技术燃料 | accident tolerant/advanced technology fuels (ATFs) | 7 | Official compound fuel category used in the innovation article. |
| 乏核燃料 | spent nuclear fuel | 2 | Repeated full-form term and a principal article topic. |
| 乏燃料 | spent fuel | 2 | Repeated short-form term used throughout the back-end discussion. |
| 高放废物 | high level waste | 2 | Recurring waste category in disposal and recycling coverage. |
| 后处理 | reprocessing | 3 | Recurring back-end fuel-cycle process. |
| 闭式燃料循环 | closed fuel cycle | 5 | Recurring named fuel-cycle strategy. |
| 地质处置设施 | geological disposal facility | 2 | Repeated disposal-facility category. |
| 翁卡洛处置库 | Onkalo repository | 16 | Fixed proper name of Finland's repository. |
| 利益相关方参与 | stakeholder engagement | 2 | Repeated cross-page article theme and programme concept. |
| 可合理达到的尽量低水平 | as low as reasonably achievable (ALARA) | 22 | Standard radiation-protection principle and abbreviation. |
| 纵深防御 | defence in depth | 22 | Standard nuclear-safety concept. |
| 原子能机构保障 | IAEA safeguards | 24 | Specific safeguards system; avoids translating the broader word `保障` out of context. |
| 全面保障协定 | comprehensive safeguards agreement (CSA) | 24 | Standard safeguards instrument and abbreviation. |
| 附加议定书 | Additional Protocol (AP) | 2 | Standard safeguards instrument repeated in contents and article text. |
| 小型模块堆 | small modular reactor (SMR) | 10 | Recurring reactor category linked to advanced fuels. |

Term conservation: 27 ruled terms; no source or target is empty or padded; normalized sources are unique and present in the 36-page captured text.

## Drop-cap proxy decision

| Source ref | Candidate ID | Decision | Evidence |
| --- | --- | --- | --- |
| `p3#3` | `dropcap-d63f478b058a4b604f1f5d7f8c1916731ef66e5dcce346e64454fb94836c313c` | `keep` | The enlarged `世` is the first character of the Director General's editorial body and is compositionally bound to the opening paragraph; retain it for the `english_raised_initial` target strategy. |

The decision copies the complete v3 source-bound fields from the review draft unchanged: source text fingerprint `23bb1a4b1a6f0e12b7290d582569e4c47024c96bbfee5f406b61cfae7a917f69`, source style hash `56fb98b5979c8d5968fe52befae9b88b7282afca7d13371ec7c55ac3f18fcb2f`, config version 2, and decision version 1.

Drop-cap conservation: 1 review candidate / 1 ruling (`keep`) / 0 uncovered candidates.

## Boundary of this review

This report records only the proxy approval of `page_kinds`, `terms` and `drop_caps`. No final translated PDF existed during this review. No final-page contact-sheet inspection, translation editing, linguistic sampling, detector override, or visual acceptance was performed. Final machine results and any residual issues will be recorded separately after the single formal whole-issue run; final human review remains with the user.
