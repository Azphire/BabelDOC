# M10 splice point annotation (batch-e2.2)

Judge `gpt-5.6-terra`, transport `{"max_output_tokens": 1024, "temperature": null, "token_parameter": "max_completion_tokens"}`, prompt `prompts/splice_judge_mqm.md` (`d62069c3b348`). Produced by `tools/splice_judge.py`; the protocol is `docs/eval/splice_protocol.md`.

## Per point, per arm

| point | arm | path | status | errors | categories |
| --- | --- | --- | --- | ---: | --- |
| AramcoWorld-en-v2 6->7 | `upstream` | pdf_extraction | annotated | 2 | accuracy/omission (major), accuracy/mistranslation (major) |
| AramcoWorld-en-v2 6->7 | `fork_full` | intermediate_language | annotated | 0 | -- |
| Courier-en 2->3 | `upstream` | pdf_extraction | annotated | 1 | accuracy/omission (minor) |
| Courier-en 2->3 | `chain_off_1` | intermediate_language | annotated | 0 | -- |
| Courier-en 2->3 | `chain_off_2` | intermediate_language | annotated | 0 | -- |
| Courier-en 2->3 | `chain_on` | intermediate_language | annotated | 1 | accuracy/addition (minor) |
| Courier-en 7->8 | `upstream` | pdf_extraction | annotated | 1 | accuracy/mistranslation (critical) |
| Courier-en 7->8 | `chain_off_1` | intermediate_language | annotated | 1 | accuracy/mistranslation (critical) |
| Courier-en 7->8 | `chain_off_2` | intermediate_language | annotated | 1 | accuracy/mistranslation (critical) |
| Courier-en 7->8 | `chain_on` | intermediate_language | annotated | 1 | accuracy/mistranslation (critical) |
| Courier-zh 2->3 | `upstream` | pdf_extraction | annotated | 1 | accuracy/untranslated (major) |
| Courier-zh 2->3 | `fork_full` | intermediate_language | annotated | 0 | -- |
| Courier-zh 7->8 | `upstream` | pdf_extraction | annotated | 1 | fluency/grammar (major) |
| Courier-zh 7->8 | `fork_full` | intermediate_language | annotated | 0 | -- |

## Readings

| point | arm | what a reader gets across the boundary |
| --- | --- | --- |
| AramcoWorld-en-v2 6->7 | `upstream` | 读者读到的是一句在“水哈兰以南的路线”处断裂且不合语法的陈述，随后提到当地燃料资源严重短缺。 |
| AramcoWorld-en-v2 6->7 | `fork_full` | 读者读到的是 Nicholson 对铁路工人技术难题的引述，随后说明这些难题还包括豪兰以南沿线大部分地区缺水和当地燃料严重短缺。 |
| Courier-en 2->3 | `upstream` | 读者读到一则关于厄瓜多尔摄影师卡罗琳娜·萨姆布拉诺作品的说明，随后看到“科学发现”标题。 |
| Courier-en 2->3 | `chain_off_1` | 读者读到的是对Carolina Zambrano作品及其所用chambira棕榈纤维刺绣的说明，随后进入“科学发现”栏目。 |
| Courier-en 2->3 | `chain_off_2` | 读者读到的是对Carolina Zambrano作品及其所用chambira棕榈纤维刺绣的说明，随后进入“科学发现”栏目。 |
| Courier-en 2->3 | `chain_on` | 读者先读到一则完整的摄影作品说明，随后看到不通顺的标题“动科学发现”。 |
| Courier-en 7->8 | `upstream` | 读者读到一家公司开发医用凝胶和一种复合材料，随后却被告知草地本身已经申请了专利。 |
| Courier-en 7->8 | `chain_off_1` | 读者读到一家公司开发医用凝胶和一种复合材料，随后得知这种草本身已被申请专利。 |
| Courier-en 7->8 | `chain_off_2` | 读者读到的是一项从针茅制成的复合材料，随后被告知这种草本身已经申请了专利。 |
| Courier-en 7->8 | `chain_on` | 译文在分页处连贯地继续说明协议下已分享的利益，但将复合材料已获专利误写成申请专利。 |
| Courier-zh 2->3 | `upstream` | The reader gets a complete English sentence about Zambrano's embroidery followed by an untranslated Chinese heading. |
| Courier-zh 2->3 | `fork_full` | 读者读到一则关于厄瓜多尔摄影师卡洛丽娜·赞布拉诺使用昌比拉棕榈纤维创作刺绣作品的说明，随后看到“土著知识”标题。 |
| Courier-zh 7->8 | `upstream` | The passage is generally clear, but the agreement sentence becomes ungrammatical across the page boundary as “included to include benefit-sharing clauses.” |
| Courier-zh 7->8 | `fork_full` | 读者读到的是一段连贯的中文说明，页面边界处“包—包含”自然衔接为“合作研究协议中包含惠益分享条款”。 |

## Error tally

| category/severity | count |
| --- | ---: |
| `accuracy/addition/minor` | 1 |
| `accuracy/mistranslation/critical` | 4 |
| `accuracy/mistranslation/major` | 1 |
| `accuracy/omission/major` | 1 |
| `accuracy/omission/minor` | 1 |
| `accuracy/untranslated/major` | 1 |
| `fluency/grammar/major` | 1 |

## Windows

### AramcoWorld-en-v2 6->7 [upstream]

- origin `examples/baseline/pdf/AramcoWorld-en-v2/AramcoWorld-en-v2.no_watermark.zh.mono.pdf`
- tail: 具有讽刺意味的是，这些难题还包括沿途大部分地区水
- head: 哈兰以南的路线以及当地可用燃料资源的严重短缺。

### AramcoWorld-en-v2 6->7 [fork_full]

- origin `examples/output/b8_4/smoke/AramcoWorld-en-v2/work/AramcoWorld-en-v2`
- tail: Nicholson 写道：“铁路工人必须克服许多 技术难题。”
- head: 具有讽刺意味的是，这些难题还包括豪兰以南沿线大部 分地区水源稀缺，以及当地可用燃料资源的严重短缺。

### Courier-en 2->3 [upstream]

- origin `examples/baseline/pdf/Courier-en/Courier-en.no_watermark.zh.mono.pdf`
- tail: 厄瓜多尔摄影师卡罗琳娜·萨姆布拉诺的作品，使用象征亚马逊土著工艺的棕榈 树纤维刺绣而成。
- head: 科学发现

### Courier-en 2->3 [chain_off_1]

- origin `examples/output/e2/r1/chain_off_1/work/Courier-en`
- tail: 厄瓜多尔摄影师Carolina Zambrano的作品，采用象征亚马逊土著工艺的棕榈 树chambira纤维刺绣而成。
- head: 科学发现

### Courier-en 2->3 [chain_off_2]

- origin `examples/output/e2/r1/chain_off_2/work/Courier-en`
- tail: 厄瓜多尔摄影师Carolina Zambrano的作品，采用象征亚马逊土著工艺的棕榈 树chambira纤维刺绣而成。
- head: 科学发现

### Courier-en 2->3 [chain_on]

- origin `examples/output/e2/r1/chain_on/work/Courier-en`
- tail: 由厄瓜多尔摄影师Carolina Zambrano创作，使用chambira纤维刺绣，这是 一种象征亚马逊土著工艺的棕榈树材料。
- head: 动科学发现

### Courier-en 7->8 [upstream]

- origin `examples/baseline/pdf/Courier-en/Courier-en.no_watermark.zh.mono.pdf`
- tail: 研究。该合作研究协议包括利益分享 的条款。一家衍生公司目前正在开发 从spinifex中提取的纤维素纳米纤维 制成的医用凝胶，以及一种复合材料。
- head: 草地已经被申请了专利。根据协议， 已经共享的利益包括为第一民族青年

### Courier-en 7->8 [chain_off_1]

- origin `examples/output/e2/r1/chain_off_1/work/Courier-en`
- tail: 并非所有与遗传资源相关的土著 知识的商业使用都构成生物盗窃；有 些项目是互惠互利的。例如，澳大利 亚的Indjalandji-Dhidhanu人就与昆 士兰大学的研究人员合作，基于他们 对针茅的土著知识进行研究，这种耐 旱的多年生丛生草传统上用于多种用 途。该合作研究协议包括利益分享的 条款。一家衍生公司现在正在开发从 针茅中提取的纤维素纳米纤维制成的 医用凝胶，以及一种复合材料。
- head: 这种草已经被申请了专利。根据协议， 已经分享的利益包括为第一民族青年 提供的就业机会，以及为澳大利亚土 著提供的培训和教育机会的资金。

### Courier-en 7->8 [chain_off_2]

- origin `examples/output/e2/r1/chain_off_2/work/Courier-en`
- tail: 并非所有与遗传资源相关的土著 知识的商业使用都构成生物盗窃；有 些项目是互惠互利的。例如，澳大利 亚的Indjalandji-Dhidhanu人就与昆 士兰大学的研究人员合作，基于他们 对传统上用于多种用途的耐旱多年生 丛生草——针茅的土著知识进行研究。 该合作研究协议包括利益分享的条款。 一家衍生公司现在正在开发从针茅中 提取的纤维素纳米纤维制成的医用凝 胶，以及一种复合材料。
- head: 这种草已经被申请了专利。根据协议， 已经分享的利益包括为第一民族青年 提供的就业机会，以及为澳大利亚土 著提供的培训和教育机会的资金。

### Courier-en 7->8 [chain_on]

- origin `examples/output/e2/r1/chain_on/work/Courier-en`
- tail: 并非所有与遗传资源相关的土著 知识的商业使用都构成生物盗窃；有 些项目是互利的。例如，澳大利亚的 Indjalandji-Dhidhanu人就与昆士兰 大学的研究人员合作，基于他们对传 统上用于多种用途的耐旱多年生丛生 草——针茅的土著知识进行研究。该 合作研究协议包括利益分享的条款。 现在，一家衍生公司正在开发从针茅 中提取的纤维素纳米纤维制成的医用 凝胶，并已为这种草的复合材料申请 了专利。
- head: 根据协议，已经分享的利益包括为第 一民族青年提供就业机会，以及为澳 大利亚土著提供培训和教育机会的资 金。

### Courier-zh 2->3 [upstream]

- origin `examples/baseline/pdf/Courier-zh/Courier-zh.no_watermark.en.mono.pdf`
- tail: The embroidery work of Ecuadorian photographer Carolina Zambrano, made with chambira palm fibers—this palm is a symbol of Amazonian indigenous craftsmanship.
- head: 土著知识

### Courier-zh 2->3 [fork_full]

- origin `examples/output/b8_4/smoke/Courier-zh/work/Courier-zh`
- tail: 厄瓜多尔摄影师卡洛丽娜·赞布拉诺的刺绣作品，采用昌比拉棕榈纤维制作—— 这种棕榈是亚马孙土著手工艺的象征。
- head: 土著知识

### Courier-zh 7->8 [upstream]

- origin `examples/baseline/pdf/Courier-zh/Courier-zh.no_watermark.en.mono.pdf`
- tail: Not all commercial uses of indigenous knowledge related to genetic resources constitute biopiracy; some projects achieve mutual benefits. For example, the Indjalandji-Dhidhanu tribe i n Australia c...
- head: to include benefit-sharing clauses. A spin-off company is currently using cellulose nanofibers extracted from Triodia to develop medical gels, and composite materials made from this herb have also ...

### Courier-zh 7->8 [fork_full]

- origin `examples/output/b8_4/smoke/Courier-zh/work/Courier-zh`
- tail: 并非所有与遗传资源相关的土著知 识商业化利用行为都构成生物剽窃；部 分项目实现了互利共赢。以澳大利亚的 印贾兰吉-迪达努（ Indjalandji-Dhidhanu）部族为例，该 部族与昆士兰大学的研究人员合作，根 据其关于三齿稃（一种多年生丛生草本 植物，传统用途广泛）的土著知识开展 研究。双方签订的合作研究协议中包
- head: 包含惠益分享条款。一家衍生企业目前 正利用从三齿稃中提取的纤维素纳米纤 维开发医用凝胶，同时，该草本植物制 成的复合材料也已获得专利。根据该协 议，已实现的惠益分享包括为第一民族 青年提供就业机会，并为澳大利亚土著 群体提供培训与教育相关的资金支持。

