# NEA Arts whole-issue proxy review

## Run identity and review gate

- Run HEAD: `5b30d60a377bdd15650e33481b5d9eab53e52d93`
- Input: `examples/input/NEA_Arts-whole-en.pdf`
- Direction/config: English to Chinese (`en` to `zh`), `minimal.en-zh.toml`
- Input pages: 24
- Input size: 5,294,257 bytes
- Input SHA-256: `91c8dacf4096d86fbccc964cbcd624ccdd499bb49d02bd0864f5e76fe3da67f9`
- Pages with at least 20 extractable characters: 24/24 (100%); automatic OCR was not enabled.
- Review export exit code: 0; `minimal_run.report.json` is complete with `translation_performed=false`.
- Review translator, chain-translation, and repair-translation requests: 0/0/0.
- Page classifier: VLM enabled, source `vlm`, model `gpt-4o-mini`, 150 DPI. All 24 VLM calls were accepted; 0 cache hits, 0 rejections, and 0 deterministic fallbacks.
- Element classifier: 24 pages, 242 paragraphs, 193 classified, 49 excluded, and 22 relabelled. Declared vocabulary is exactly title/body/caption/pull_quote/byline/other_display.
- Review draft: format version 3, sample `NEA_Arts-whole-en`, 24 page-kind rows, 0 terms as required by `--skip-translation`, and 1 drop-cap candidate.

## Page-kind adjudication

Every physical page has an explicit proxy decision. `override` is used when the final machine kind would alter article boundaries or record-line handling incorrectly.

| Physical page | Machine kind | Source/confidence | Proxy kind | Disposition | Layout evidence |
| ---: | --- | --- | --- | --- | --- |
| 1 | front_cover | vlm / 1.00 | front_cover | accept_vlm | Opening issue cover with masthead, dominant mask artwork, and cover lines. |
| 2 | editorial | vlm / 0.90 | toc | override | Composite front-of-book page, but the left column is the issue navigation: five article titles paired with page numbers; TOC line preservation is required. |
| 3 | article_opener | vlm / 0.90 | article_opener | accept_vlm | Full headline, deck, byline, lead prose, and hero photograph begin “Options for Healing.” |
| 4 | article_opener | vlm / 0.90 | article_body | override | Internal folio 2, two columns of uninterrupted continuation prose, no new headline or byline. |
| 5 | article_opener | vlm / 0.90 | article_body | override | Internal folio 3 continues the same story with prose and supporting photographs. |
| 6 | article_body | vlm / 0.85 | article_body | accept_vlm | Internal folio 4 closes the same article in continuous columns. |
| 7 | article_opener | vlm / 0.90 | article_opener | accept_vlm | Display title, deck, byline, artwork, and no preceding continuation begin “Advancing Recovery.” |
| 8 | article_opener | vlm / 0.90 | article_body | override | Internal folio 6 starts with a decorative initial but continues the article opened on page 7. |
| 9 | article_opener | vlm / 0.85 | article_body | override | Internal folio 7 is dense continuation prose and captioned art, without a new article apparatus. |
| 10 | article_opener | vlm / 0.85 | article_body | override | Internal folio 8 continues the disaster-recovery story across columns. |
| 11 | article_body | vlm / 0.90 | article_body | accept_vlm | Internal folio 9 is the closing page of the same article. |
| 12 | article_opener | vlm / 0.90 | article_opener | accept_vlm | Hand-lettered headline, subtitle, byline, lead prose, and feature image begin “Ask the Question.” |
| 13 | article_opener | vlm / 0.85 | article_body | override | Internal folio 11 continues page 12 with running prose and exhibit photographs. |
| 14 | article_body | vlm / 0.85 | article_body | accept_vlm | Internal folio 12 is continuous body text and a supporting photograph. |
| 15 | article_body | vlm / 0.85 | article_body | accept_vlm | Internal folio 13 closes the “Ask the Question” feature. |
| 16 | article_opener | vlm / 0.90 | article_opener | accept_vlm | Hero image, headline, subtitle, byline, lead prose, and a real decorative T begin “Music as Medicine.” |
| 17 | article_opener | vlm / 0.85 | article_body | override | Internal folio 15 continues page 16 in columns with no new headline or byline. |
| 18 | article_opener | vlm / 0.85 | article_body | override | Internal folio 16 closes the music-and-health article in running prose. |
| 19 | article_opener | vlm / 0.90 | article_opener | accept_vlm | Headline, deck, byline, lead prose, and feature image begin “Only Connect.” |
| 20 | article_opener | vlm / 0.85 | article_body | override | Internal folio 18 continues the Shakespeare story without new article apparatus. |
| 21 | article_opener | vlm / 0.85 | article_body | override | Internal folio 19 is continuation prose with a captioned performance photograph. |
| 22 | article_body | vlm / 0.90 | article_body | accept_vlm | Internal folio 20 continues the same urban-rural feature. |
| 23 | article_body | vlm / 0.90 | article_body | accept_vlm | Internal folio 21 closes the same feature. |
| 24 | photo_spread | vlm / 0.90 | back_cover | override | Last physical page is an image-led institutional back cover with address/social footer and short online-feature promotion. |

Totals: 24 explicit page-kind rulings; 12 accepted from VLM, 0 accepted fallbacks, and 12 overrides.

## Terminology adjudication

The 37 exact source strings below were normalized with the repository glossary rule and found in the captured source text. Article titles are included because they recur in the TOC and opener; institutions, programs, works, and technical terms are included where cross-page consistency matters.

| Source | Fixed Chinese | First page | Rationale |
| --- | --- | ---: | --- |
| NEA Arts | 《NEA艺术》 | 2 | Publication title. |
| National Endowment for the Arts | 美国国家艺术基金会 | 1 | Publisher and recurring federal institution. |
| Arts Endowment | 美国国家艺术基金会 | 2 | Recurring short form of the same institution. |
| National Council on the Arts | 国家艺术委员会 | 2 | Governing body in the masthead. |
| Creative Forces | “创意力量”计划 | 2 | Recurring NEA initiative across features. |
| Community Connections | “社区联结”项目 | 2 | Recurring Creative Forces program component. |
| clinic-to-community continuum | 临床到社区连续服务体系 | 6 | Recurring program model and specialist term. |
| creative arts therapy | 创意艺术疗法 | 2 | Recurring clinical arts term. |
| post-traumatic stress disorder | 创伤后应激障碍 | 3 | Clinical term used across pages; acronym remains PTSD. |
| traumatic brain injury | 创伤性脑损伤 | 3 | Clinical term used across pages; acronym remains TBI. |
| Resounding Joy | 回响之乐 | 4 | Recurring partner organization. |
| Semper Sound | 恒久之声 | 4 | Named music program/band. |
| National Coalition for Arts Preparedness and Emergency Response | 全国艺术备灾与应急响应联盟 | 8 | National emergency-arts coalition. |
| Heritage Emergency National Task Force | 国家遗产应急工作组 | 8 | Federal heritage-emergency group. |
| Natural and Cultural Resources Recovery Support Function | 自然与文化资源恢复支持职能 | 8 | Formal disaster-recovery function. |
| Federal Emergency Management Agency | 联邦紧急事务管理局 | 8 | Recurring federal agency; acronym remains FEMA. |
| Ask the Question | “问出那个问题” | 2 | Article, project, and exhibition name repeated across four pages. |
| Clackamas County Arts Alliance | 克拉克默斯县艺术联盟 | 12 | Project partner organization. |
| Live Through This | “活着走过” | 13 | Referenced suicide-survivor project. |
| Sound Health | “声音健康”计划 | 16 | Named music-and-health initiative. |
| John F. Kennedy Center for Performing Arts | 约翰·F·肯尼迪表演艺术中心 | 16 | Partner institution. |
| National Institutes of Health | 美国国立卫生研究院 | 16 | Partner institution. |
| Music as Medicine | “音乐即良药” | 2 | Article and recurring program name. |
| South Dakota Symphony Orchestra | 南达科他交响乐团 | 16 | Recurring orchestra; acronym remains SDSO. |
| Creativity Connects | “创意联结” | 17 | NEA grant program repeated in two features. |
| Shakespeare Festival St. Louis | 圣路易斯莎士比亚戏剧节 | 19 | Recurring producing organization. |
| Shakespeare in the Streets | “街头莎士比亚”项目 | 19 | Recurring community-theater program. |
| As You Like It | 《皆大欢喜》 | 20 | Shakespeare work adapted by the project. |
| Options for Healing | “疗愈之选” | 2 | TOC/opener article title. |
| Advancing Recovery | “推进复原” | 2 | TOC/opener article title. |
| The Arts and Culture in Disaster Relief | “灾害救援中的艺术与文化” | 2 | TOC/opener article subtitle. |
| A Public Health and Art Initiative to Help Prevent Suicide | “一项助力预防自杀的公共卫生与艺术倡议” | 2 | TOC/opener article subtitle. |
| The Power of Music in a Healthcare Setting | “医疗环境中的音乐力量” | 2 | TOC/opener article subtitle. |
| Only Connect | “唯有联结” | 2 | TOC/opener article title. |
| Bridging the Urban-Rural Divide through Theater | “以戏剧弥合城乡鸿沟” | 2 | TOC/opener article subtitle. |
| The Healing Power of the Arts | “艺术的疗愈力量” | 1 | Issue theme on the cover. |
| NEA Office of Public Affairs | NEA公共事务办公室 | 11 | Repeated contributor affiliation. |

## Drop-cap adjudication

One candidate was reviewed and fully bound. `p16#5` is a genuine oversized decorative T at the beginning of the “Music as Medicine” lead paragraph, not a title glyph or image text. Decision: `keep`, so the Chinese target uses the configured two-line initial policy. Candidate ID, source reference, text fingerprint, style hash, and both version fields are copied unchanged from the v3 review draft.

## Proxy conclusion

The no-translation machine gate and full visual proxy review passed. The decisions file contains 24/24 page kinds, 37 source-attested terms, and 1/1 fully bound drop-cap ruling. It is ready for the single formal whole-issue translation run.
