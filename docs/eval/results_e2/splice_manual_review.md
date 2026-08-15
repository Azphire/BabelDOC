# Manual spot check of the splice judge (batch-e2.2)

One item per splice point and arm. Read the three windows, then the judge's annotation. Set human_agrees to true or false; where it is false, put the annotation you would have given in human_errors, in the same shape as judge_errors and using the same two vocabularies; human_note is free text. Leave nothing at null in a filled copy.

Selection rule: every point on every arm. 14 items.

The machine readable copy is `splice_manual_review.json`; fill that one and keep this as the reading copy.

## AramcoWorld-en-v2 6->7 [upstream]

- adjudication: MID-SENTENCE SPLIT #2: issue p34->p35 adjacent, 'a scarcity of water along much of' -> 'the route south of the Hauran...'

**Source across the boundary**

```
“The railway workers had to overcome many  
technical difficulties,” writes Nicholson. These, iron-
ically, also included a scarcity of water along much of

the route south of the Hauran and a severe shortage 
of locally available fuel sources.
```

**Tail (end of the page being left)**

```
具有讽刺意味的是，这些难题还包括沿途大部分地区水
```

**Head (start of the page being entered)**

```
哈兰以南的路线以及当地可用燃料资源的严重短缺。
```

**Judge (gpt-5.6-terra, annotated)**

- reading: 读者读到的是一句在“水哈兰以南的路线”处断裂且不合语法的陈述，随后提到当地燃料资源严重短缺。
- `accuracy/omission` / `major` in source: "“The railway workers had to overcome many technical difficulties,” writes Nicholson." -- 源文中尼科尔森关于铁路工人必须克服许多技术困难的引述在两个译文窗口中均未呈现。
- `accuracy/mistranslation` / `major` in tail: "沿途大部分地区水" -- 该尾部与页首的“哈兰以南的路线”拼接成“水哈兰以南的路线”，边界造成语法断裂，并未表达哈兰以南大部分路段缺水。

**Your verdict**

- human_agrees: [ ] yes  [ ] no
- human_errors (if no):
- human_note:

## AramcoWorld-en-v2 6->7 [fork_full]

- adjudication: MID-SENTENCE SPLIT #2: issue p34->p35 adjacent, 'a scarcity of water along much of' -> 'the route south of the Hauran...'

**Source across the boundary**

```
“The railway workers had to overcome many  
technical difficulties,” writes Nicholson. These, iron-
ically, also included a scarcity of water along much of

the route south of the Hauran and a severe shortage 
of locally available fuel sources.
```

**Tail (end of the page being left)**

```
Nicholson 写道：“铁路工人必须克服许多
技术难题。”
```

**Head (start of the page being entered)**

```
具有讽刺意味的是，这些难题还包括豪兰以南沿线大部
分地区水源稀缺，以及当地可用燃料资源的严重短缺。
```

**Judge (gpt-5.6-terra, annotated)**

- reading: 读者读到的是 Nicholson 对铁路工人技术难题的引述，随后说明这些难题还包括豪兰以南沿线大部分地区缺水和当地燃料严重短缺。
- no error reported

**Your verdict**

- human_agrees: [ ] yes  [ ] no
- human_errors (if no):
- human_note:

## Courier-en 2->3 [upstream]

- adjudication: DISPLAY-TITLE SPLIT: 'How Indigenous knowledge drives' / 'scientific discovery' is one phrase cut across the spread; a split semantic unit, same class as a mid-sentence body split

**Source across the boundary**

```
Work by Ecuadorian photographer Carolina Zambrano, embroidered with chambira
fibres, a palm tree emblematic of Indigenous Amazonian craftsmanship.

scientific discover y
```

**Tail (end of the page being left)**

```
厄瓜多尔摄影师卡罗琳娜·萨姆布拉诺的作品，使用象征亚马逊土著工艺的棕榈
树纤维刺绣而成。
```

**Head (start of the page being entered)**

```
科学发现
```

**Judge (gpt-5.6-terra, annotated)**

- reading: 读者读到一则关于厄瓜多尔摄影师卡罗琳娜·萨姆布拉诺作品的说明，随后看到“科学发现”标题。
- `accuracy/omission` / `minor` in tail: "棕榈
树纤维" -- 译文未保留纤维名称“chambira”，只笼统译为棕榈树纤维。

**Your verdict**

- human_agrees: [ ] yes  [ ] no
- human_errors (if no):
- human_note:

## Courier-en 2->3 [chain_off_1]

- adjudication: DISPLAY-TITLE SPLIT: 'How Indigenous knowledge drives' / 'scientific discovery' is one phrase cut across the spread; a split semantic unit, same class as a mid-sentence body split

**Source across the boundary**

```
Work by Ecuadorian photographer Carolina Zambrano, embroidered with chambira
fibres, a palm tree emblematic of Indigenous Amazonian craftsmanship.

scientific discover y
```

**Tail (end of the page being left)**

```
厄瓜多尔摄影师Carolina Zambrano的作品，采用象征亚马逊土著工艺的棕榈
树chambira纤维刺绣而成。
```

**Head (start of the page being entered)**

```
科学发现
```

**Judge (gpt-5.6-terra, annotated)**

- reading: 读者读到的是对Carolina Zambrano作品及其所用chambira棕榈纤维刺绣的说明，随后进入“科学发现”栏目。
- no error reported

**Your verdict**

- human_agrees: [ ] yes  [ ] no
- human_errors (if no):
- human_note:

## Courier-en 2->3 [chain_off_2]

- adjudication: DISPLAY-TITLE SPLIT: 'How Indigenous knowledge drives' / 'scientific discovery' is one phrase cut across the spread; a split semantic unit, same class as a mid-sentence body split

**Source across the boundary**

```
Work by Ecuadorian photographer Carolina Zambrano, embroidered with chambira
fibres, a palm tree emblematic of Indigenous Amazonian craftsmanship.

scientific discover y
```

**Tail (end of the page being left)**

```
厄瓜多尔摄影师Carolina Zambrano的作品，采用象征亚马逊土著工艺的棕榈
树chambira纤维刺绣而成。
```

**Head (start of the page being entered)**

```
科学发现
```

**Judge (gpt-5.6-terra, annotated)**

- reading: 读者读到的是对Carolina Zambrano作品及其所用chambira棕榈纤维刺绣的说明，随后进入“科学发现”栏目。
- no error reported

**Your verdict**

- human_agrees: [ ] yes  [ ] no
- human_errors (if no):
- human_note:

## Courier-en 2->3 [chain_on]

- adjudication: DISPLAY-TITLE SPLIT: 'How Indigenous knowledge drives' / 'scientific discovery' is one phrase cut across the spread; a split semantic unit, same class as a mid-sentence body split

**Source across the boundary**

```
Work by Ecuadorian photographer Carolina Zambrano, embroidered with chambira
fibres, a palm tree emblematic of Indigenous Amazonian craftsmanship.

scientific discover y
```

**Tail (end of the page being left)**

```
由厄瓜多尔摄影师Carolina Zambrano创作，使用chambira纤维刺绣，这是
一种象征亚马逊土著工艺的棕榈树材料。
```

**Head (start of the page being entered)**

```
动科学发现
```

**Judge (gpt-5.6-terra, annotated)**

- reading: 读者先读到一则完整的摄影作品说明，随后看到不通顺的标题“动科学发现”。
- `accuracy/addition` / `minor` in head: "动" -- 源文的“scientific discovery”不支持标题开头额外出现的“动”，使译文标题不自然。

**Your verdict**

- human_agrees: [ ] yes  [ ] no
- human_errors (if no):
- human_note:

## Courier-en 7->8 [upstream]

- adjudication: MID-SENTENCE BODY SPLIT: 'a composite material from' -> 'the grass has been patented'; issue pp.12-13

**Source across the boundary**

```
pinifex,
a hardy perennial tussock grass tradition-
ally used  for a  variety  of  purposes. The
collaborative research agreement includes
provisions for benefit sharing. A spinoff
company is now developing medical gels
from cellulose nanofibers extracted from
spinifex, and a composite material from

the grass has been  patented. Benefits
that have already been shared  under
the agreement include  employment
opportunities  for  First  Nations youth
and funding for training and educational
opportunities for Indigenous Australians.
```

**Tail (end of the page being left)**

```
研究。该合作研究协议包括利益分享
的条款。一家衍生公司目前正在开发
从spinifex中提取的纤维素纳米纤维
制成的医用凝胶，以及一种复合材料。
```

**Head (start of the page being entered)**

```
草地已经被申请了专利。根据协议，
已经共享的利益包括为第一民族青年
```

**Judge (gpt-5.6-terra, annotated)**

- reading: 读者读到一家公司开发医用凝胶和一种复合材料，随后却被告知草地本身已经申请了专利。
- `accuracy/mistranslation` / `critical` in head: "草地已经被申请了专利。" -- 原文说明由这种草制成的复合材料获得了专利，而译文错误地说草地本身申请了专利，这一错误由跨页处将未完短语断开后重启造成。

**Your verdict**

- human_agrees: [ ] yes  [ ] no
- human_errors (if no):
- human_note:

## Courier-en 7->8 [chain_off_1]

- adjudication: MID-SENTENCE BODY SPLIT: 'a composite material from' -> 'the grass has been patented'; issue pp.12-13

**Source across the boundary**

```
pinifex,
a hardy perennial tussock grass tradition-
ally used  for a  variety  of  purposes. The
collaborative research agreement includes
provisions for benefit sharing. A spinoff
company is now developing medical gels
from cellulose nanofibers extracted from
spinifex, and a composite material from

the grass has been  patented. Benefits
that have already been shared  under
the agreement include  employment
opportunities  for  First  Nations youth
and funding for training and educational
opportunities for Indigenous Australians.
```

**Tail (end of the page being left)**

```
并非所有与遗传资源相关的土著
知识的商业使用都构成生物盗窃；有
些项目是互惠互利的。例如，澳大利
亚的Indjalandji-Dhidhanu人就与昆
士兰大学的研究人员合作，基于他们
对针茅的土著知识进行研究，这种耐
旱的多年生丛生草传统上用于多种用
途。该合作研究协议包括利益分享的
条款。一家衍生公司现在正在开发从
针茅中提取的纤维素纳米纤维制成的
医用凝胶，以及一种复合材料。
```

**Head (start of the page being entered)**

```
这种草已经被申请了专利。根据协议，
已经分享的利益包括为第一民族青年
提供的就业机会，以及为澳大利亚土
著提供的培训和教育机会的资金。
```

**Judge (gpt-5.6-terra, annotated)**

- reading: 读者读到一家公司开发医用凝胶和一种复合材料，随后得知这种草本身已被申请专利。
- `accuracy/mistranslation` / `critical` in head: "这种草已经被申请了专利。" -- 源文说的是由这种草制成的复合材料已经获得专利，而译文错误地说这种草本身被申请专利，并将已获专利弱化为申请。

**Your verdict**

- human_agrees: [ ] yes  [ ] no
- human_errors (if no):
- human_note:

## Courier-en 7->8 [chain_off_2]

- adjudication: MID-SENTENCE BODY SPLIT: 'a composite material from' -> 'the grass has been patented'; issue pp.12-13

**Source across the boundary**

```
pinifex,
a hardy perennial tussock grass tradition-
ally used  for a  variety  of  purposes. The
collaborative research agreement includes
provisions for benefit sharing. A spinoff
company is now developing medical gels
from cellulose nanofibers extracted from
spinifex, and a composite material from

the grass has been  patented. Benefits
that have already been shared  under
the agreement include  employment
opportunities  for  First  Nations youth
and funding for training and educational
opportunities for Indigenous Australians.
```

**Tail (end of the page being left)**

```
并非所有与遗传资源相关的土著
知识的商业使用都构成生物盗窃；有
些项目是互惠互利的。例如，澳大利
亚的Indjalandji-Dhidhanu人就与昆
士兰大学的研究人员合作，基于他们
对传统上用于多种用途的耐旱多年生
丛生草——针茅的土著知识进行研究。
该合作研究协议包括利益分享的条款。
一家衍生公司现在正在开发从针茅中
提取的纤维素纳米纤维制成的医用凝
胶，以及一种复合材料。
```

**Head (start of the page being entered)**

```
这种草已经被申请了专利。根据协议，
已经分享的利益包括为第一民族青年
提供的就业机会，以及为澳大利亚土
著提供的培训和教育机会的资金。
```

**Judge (gpt-5.6-terra, annotated)**

- reading: 读者读到的是一项从针茅制成的复合材料，随后被告知这种草本身已经申请了专利。
- `accuracy/mistranslation` / `critical` in head: "这种草已经被申请了专利。" -- 源文说的是由该草制成的复合材料已获专利，而跨页后错误地说成这种草申请了专利，并改变了专利状态。

**Your verdict**

- human_agrees: [ ] yes  [ ] no
- human_errors (if no):
- human_note:

## Courier-en 7->8 [chain_on]

- adjudication: MID-SENTENCE BODY SPLIT: 'a composite material from' -> 'the grass has been patented'; issue pp.12-13

**Source across the boundary**

```
pinifex,
a hardy perennial tussock grass tradition-
ally used  for a  variety  of  purposes. The
collaborative research agreement includes
provisions for benefit sharing. A spinoff
company is now developing medical gels
from cellulose nanofibers extracted from
spinifex, and a composite material from

the grass has been  patented. Benefits
that have already been shared  under
the agreement include  employment
opportunities  for  First  Nations youth
and funding for training and educational
opportunities for Indigenous Australians.
```

**Tail (end of the page being left)**

```
并非所有与遗传资源相关的土著
知识的商业使用都构成生物盗窃；有
些项目是互利的。例如，澳大利亚的
Indjalandji-Dhidhanu人就与昆士兰
大学的研究人员合作，基于他们对传
统上用于多种用途的耐旱多年生丛生
草——针茅的土著知识进行研究。该
合作研究协议包括利益分享的条款。
现在，一家衍生公司正在开发从针茅
中提取的纤维素纳米纤维制成的医用
凝胶，并已为这种草的复合材料申请
了专利。
```

**Head (start of the page being entered)**

```
根据协议，已经分享的利益包括为第
一民族青年提供就业机会，以及为澳
大利亚土著提供培训和教育机会的资
金。
```

**Judge (gpt-5.6-terra, annotated)**

- reading: 译文在分页处连贯地继续说明协议下已分享的利益，但将复合材料已获专利误写成申请专利。
- `accuracy/mistranslation` / `critical` in tail: "并已为这种草的复合材料申请了专利。" -- 原文说明该复合材料“has been patented”即已获得专利，译文却称仅申请了专利，错误改变了专利状态这一事实。

**Your verdict**

- human_agrees: [ ] yes  [ ] no
- human_errors (if no):
- human_note:

## Courier-zh 2->3 [upstream]

- adjudication: DISPLAY-TITLE SPLIT (zh): 时代变迁背景下的 / 土著知识 cut across the spread

**Source across the boundary**

```
厄瓜多尔摄影师卡洛丽娜·赞布拉诺的刺绣作品，采用昌比拉棕榈纤维制作—
这种棕榈是亚马孙土著手工艺的象征。

土著知识
```

**Tail (end of the page being left)**

```
The embroidery work of Ecuadorian photographer Carolina Zambrano, made with 
chambira palm fibers—this palm is a symbol of Amazonian indigenous craftsmanship.
```

**Head (start of the page being entered)**

```
土著知识
```

**Judge (gpt-5.6-terra, annotated)**

- reading: The reader gets a complete English sentence about Zambrano's embroidery followed by an untranslated Chinese heading.
- `accuracy/untranslated` / `major` in head: "土著知识" -- The heading is left untranslated instead of rendering the source's “Indigenous knowledge.”

**Your verdict**

- human_agrees: [ ] yes  [ ] no
- human_errors (if no):
- human_note:

## Courier-zh 2->3 [fork_full]

- adjudication: DISPLAY-TITLE SPLIT (zh): 时代变迁背景下的 / 土著知识 cut across the spread

**Source across the boundary**

```
厄瓜多尔摄影师卡洛丽娜·赞布拉诺的刺绣作品，采用昌比拉棕榈纤维制作—
这种棕榈是亚马孙土著手工艺的象征。

土著知识
```

**Tail (end of the page being left)**

```
厄瓜多尔摄影师卡洛丽娜·赞布拉诺的刺绣作品，采用昌比拉棕榈纤维制作——
这种棕榈是亚马孙土著手工艺的象征。
```

**Head (start of the page being entered)**

```
土著知识
```

**Judge (gpt-5.6-terra, annotated)**

- reading: 读者读到一则关于厄瓜多尔摄影师卡洛丽娜·赞布拉诺使用昌比拉棕榈纤维创作刺绣作品的说明，随后看到“土著知识”标题。
- no error reported

**Your verdict**

- human_agrees: [ ] yes  [ ] no
- human_errors (if no):
- human_note:

## Courier-zh 7->8 [upstream]

- adjudication: MID-WORD SPLIT (official): zh p10->p11 adjacent, 协议中包 / 含惠益分享条款 - the acute zh positive, same site as the b5.3 official-edition citation

**Source across the boundary**

```
并非所有与遗传 资源相关的土
著知识商业化利用行为都构成生物剽
窃；部分项目实现了互利共赢。以澳大
利亚的印贾兰吉 - 迪达努（Indjalan-
dji-Dhidhanu） 部族为例，该部族与
昆士兰大学的研究人员合作，根据其
关于三齿稃 （一种多年生丛生草本植
物，传统用途广泛） 的土著知识开展
研究。双方签订的合作研究协议中包

含惠益分享条款。一家衍生企业目前
正利用从三齿稃中提取的纤维素纳米
纤维开发医用凝胶，同时，该草本植
物制成的复合材料也已获得专利。根
据该协议，已实现的惠益分享包括为
第一民族青年提供就业机会，并为澳
大利亚土著群体提供培训与教育相关
的资金支持。
```

**Tail (end of the page being left)**

```
Not all commercial uses of 
indigenous knowledge related to genetic 
resources constitute biopiracy; some 
projects achieve mutual benefits. For 
example, the Indjalandji-Dhidhanu tribe i
n Australia collaborated with researchers 
from the University of Queensland to 
conduct research based on their 
indigenous knowledge of Triodia (a 
perennial tussock grass with various 
traditional uses). The cooperative 
research agreement signed by both 
parties included
```

**Head (start of the page being entered)**

```
to include benefit-sharing clauses. A 
spin-off company is currently using 
cellulose nanofibers extracted from 
Triodia to develop medical gels, and 
composite materials made from this herb 
have also been patented. According to 
the agreement, realized benefits include 
providing employment opportunities for 
First Nations youth and funding support 
for training and education related to 
Australian indigenous communities.
```

**Judge (gpt-5.6-terra, annotated)**

- reading: The passage is generally clear, but the agreement sentence becomes ungrammatical across the page boundary as “included to include benefit-sharing clauses.”
- `fluency/grammar` / `major` in head: "to include benefit-sharing clauses." -- The boundary causes this infinitive phrase to follow the tail's “included,” producing the ungrammatical and duplicative construction “included to include.”

**Your verdict**

- human_agrees: [ ] yes  [ ] no
- human_errors (if no):
- human_note:

## Courier-zh 7->8 [fork_full]

- adjudication: MID-WORD SPLIT (official): zh p10->p11 adjacent, 协议中包 / 含惠益分享条款 - the acute zh positive, same site as the b5.3 official-edition citation

**Source across the boundary**

```
并非所有与遗传 资源相关的土
著知识商业化利用行为都构成生物剽
窃；部分项目实现了互利共赢。以澳大
利亚的印贾兰吉 - 迪达努（Indjalan-
dji-Dhidhanu） 部族为例，该部族与
昆士兰大学的研究人员合作，根据其
关于三齿稃 （一种多年生丛生草本植
物，传统用途广泛） 的土著知识开展
研究。双方签订的合作研究协议中包

含惠益分享条款。一家衍生企业目前
正利用从三齿稃中提取的纤维素纳米
纤维开发医用凝胶，同时，该草本植
物制成的复合材料也已获得专利。根
据该协议，已实现的惠益分享包括为
第一民族青年提供就业机会，并为澳
大利亚土著群体提供培训与教育相关
的资金支持。
```

**Tail (end of the page being left)**

```
并非所有与遗传资源相关的土著知
识商业化利用行为都构成生物剽窃；部
分项目实现了互利共赢。以澳大利亚的
印贾兰吉-迪达努（
Indjalandji-Dhidhanu）部族为例，该
部族与昆士兰大学的研究人员合作，根
据其关于三齿稃（一种多年生丛生草本
植物，传统用途广泛）的土著知识开展
研究。双方签订的合作研究协议中包
```

**Head (start of the page being entered)**

```
包含惠益分享条款。一家衍生企业目前
正利用从三齿稃中提取的纤维素纳米纤
维开发医用凝胶，同时，该草本植物制
成的复合材料也已获得专利。根据该协
议，已实现的惠益分享包括为第一民族
青年提供就业机会，并为澳大利亚土著
群体提供培训与教育相关的资金支持。
```

**Judge (gpt-5.6-terra, annotated)**

- reading: 读者读到的是一段连贯的中文说明，页面边界处“包—包含”自然衔接为“合作研究协议中包含惠益分享条款”。
- no error reported

**Your verdict**

- human_agrees: [ ] yes  [ ] no
- human_errors (if no):
- human_note:

