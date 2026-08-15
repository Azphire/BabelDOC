# R1 drift attribution (batch-e2.1)

Sample: `Courier-en.pdf`. The three columns are the three runs of `tools/run_drift_trio.py`: two `chain_off` arms drawn independently under one configuration, and the frozen `chain_on` arm replayed from cache.

Matched paragraphs **132**; changed between `chain_off_1` and `chain_on` **59**; the two off arms disagree about **43** of the 132 on their own, which is this configuration's run-to-run variance (0.325758). **27** paragraphs sat in a batch the chain pass recomposed, on pages [2, 3, 7, 8].

`gap01` is the rule D3 GAP-01 states, computed from the three text columns alone and recomputable by any reader from them; `verdict` is that rule with the batch evidence applied, which separates a recomposed batch from a third draw of an identical one.

## 1. The A-12 set

Changed **and** in a recomposed batch. This is the whole of what the shared-cache design of b5.3 could see at all -- there a paragraph whose batch did not move was served from the cache and was identical by construction -- so it is the like-for-like counterpart of ledger row A-12. It has **15** members: `p2#3`, `p2#4`, `p2#7`, `p3#1`, `p7#4`, `p7#5`, `p7#9`, `p7#11`, `p7#14`, `p7#17`, `p8#7`, `p8#8`, `p8#10`, `p8#11`, `p8#14`.

| # | paragraph | label | off1 | off2 | on | off1=off2 | batch moved | gap01 | verdict |
| ---: | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `p2#3` | title | `土著知识如何驱动` | `土著知识如何驱动` | `土著知识如何推` | yes | yes | chain_member | chain_member |
| 2 | `p2#4` | figure_caption | `厄瓜多尔摄影师Carolina Zambrano的作品，采用象征亚马逊土著工艺的棕榈树chamb...` | `厄瓜多尔摄影师Carolina Zambrano的作品，采用象征亚马逊土著工艺的棕榈树chamb...` | `由厄瓜多尔摄影师Carolina Zambrano创作，使用chambira纤维刺绣，这是一种象...` | yes | yes | rebatch_effect | rebatch_effect |
| 3 | `p2#7` | plain text | `来自萨摩亚的土著气候记者，为<style id='1'>卫报</style>报道太平洋岛屿问题，...` | `来自萨摩亚的土著气候记者，为<style id='1'>卫报</style>报道太平洋岛屿问题，...` | `来自萨摩亚的原住民气候记者，为<style id='1'>卫报</style>报道太平洋岛屿问题...` | no | yes | sampling_noise | sampling_noise |
| 4 | `p3#1` | title | `科学发现` | `科学发现` | `动科学发现` | yes | yes | chain_member | chain_member |
| 5 | `p7#4` | plain text | `并非所有与遗传资源相关的土著知识的商业使用都构成生物盗窃；有些项目是互惠互利的。例如，澳大利亚的...` | `并非所有与遗传资源相关的土著知识的商业使用都构成生物盗窃；有些项目是互惠互利的。例如，澳大利亚的...` | `并非所有与遗传资源相关的土著知识的商业使用都构成生物盗窃；有些项目是互利的。例如，澳大利亚的In...` | no | yes | chain_member | chain_member |
| 6 | `p7#5` | plain text | `然而，生物发现被批评为在土著和其他地方人民开发的知识上“搭便车”。当他们的知识在科学研究、产品开...` | `然而，生物发现被批评为对土著和其他地方人民开发的知识的“搭便车”。当他们的知识在科学研究、产品开...` | `然而，生物发现被批评为对土著和其他地方人民所发展的知识的“搭便车”。当他们的知识在科学研究、产品...` | no | yes | sampling_noise | sampling_noise |
| 7 | `p7#9` | plain text | `研究人员和公司常常寻求土著居民对植物、动物及生态系统中其他非人类生物的特性的见解，以开发新技术和...` | `研究人员和公司常常寻求土著居民对植物、动物及生态系统中其他非人类生物的特性的见解，以开发新技术和...` | `研究人员和公司常常寻求土著对植物、动物及生态系统中其他非人类居民特性的见解，以开发新技术和创新。...` | yes | yes | rebatch_effect | rebatch_effect |
| 8 | `p7#11` | title | `当生物盗窃扎根时` | `当生物盗窃扎根时` | `当生物盗窃扎根` | yes | yes | rebatch_effect | rebatch_effect |
| 9 | `p7#14` | plain text | `他是新南威尔士大学（澳大利亚）艺术学院的教授兼研究副院长，他的研究重点是自然和知识的监管。` | `他是新南威尔士大学（澳大利亚）艺术学院的教授兼研究副院长，他的研究重点是自然和知识的监管。` | `他是新南威尔士大学（澳大利亚）艺术学院的教授兼研究副院长，其研究重点是自然和知识的监管。` | yes | yes | rebatch_effect | rebatch_effect |
| 10 | `p7#17` | title | `如今，许多国家要求土著知识的潜在使用者首先获得知识持有者的同意` | `如今，许多国家要求土著知识的潜在使用者首先获得知识持有者的同意` | `如今，许多国家要求潜在的土著知识使用者首先获得知识持有者的同意` | yes | yes | rebatch_effect | rebatch_effect |
| 11 | `p8#7` | plain text | `过去30年间建立的强化国际规则和协议框架，已经带来了一些积极的变化。如今，许多国家` | `过去30年间建立的强化国际规则和协议框架，已经带来了一些积极的变化。如今，许多国家` | `过去30年间建立的强化国际规则和协议框架，带来了一些积极的变化。如今，许多国家` | yes | yes | rebatch_effect | rebatch_effect |
| 12 | `p8#8` | plain text | `这种草已经被申请了专利。根据协议，已经分享的利益包括为第一民族青年提供的就业机会，以及为澳大利亚...` | `这种草已经被申请了专利。根据协议，已经分享的利益包括为第一民族青年提供的就业机会，以及为澳大利亚...` | `根据协议，已经分享的利益包括为第一民族青年提供就业机会，以及为澳大利亚土著提供培训和教育机会的资...` | yes | yes | chain_member | chain_member |
| 13 | `p8#10` | plain text | `生物盗窃问题的根源在于一个历史性的转变：全球社会开始将生物资源视为专有资产，而不是共享遗产的那一...` | `生物盗窃问题的根源在于一个历史性的转变：全球社会开始将生物资源视为专有资产，而不是共享遗产的那一...` | `生物盗窃问题的根源在于一个历史性的转变：全球社会开始将生物资源视为专有资产，而非共享遗产的那一刻...` | yes | yes | rebatch_effect | rebatch_effect |
| 14 | `p8#11` | plain text | `植物、动物和其他生物多样性成分在全球范围内的流通以及不同人群之间相关知识的共享并不是什么新鲜事。...` | `植物、动物和其他生物多样性成分在全球范围内的流通以及不同人群之间相关知识的共享并不是什么新鲜事。...` | `植物、动物和其他生物多样性成分在全球范围内的流通，以及不同人群之间相关知识的共享，并不是新鲜事。...` | no | yes | sampling_noise | sampling_noise |
| 15 | `p8#14` | figure_caption | `在摩洛哥西南部塔夫拉乌特的一个女性合作社的阿甘油生产车间。` | `在摩洛哥西南部塔夫拉乌特的一个女性合作社的阿甘油生产车间。` | `摩洛哥西南部塔夫拉乌特的一家女性合作社的阿甘油生产车间。` | yes | yes | rebatch_effect | rebatch_effect |

Verdicts over this set:

- `chain_member`: 4
- `rebatch_effect`: 8
- `sampling_noise`: 3

## 2. Every changed paragraph

The set above read against the whole document. The rows that are not in it changed without their batch moving, which is what the two off arms measure the size of.

| # | paragraph | label | off1 | off2 | on | off1=off2 | batch moved | gap01 | verdict |
| ---: | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `p1#2` | plain text | `土著知识长期以来被科学忽视，有时甚至遭到反对。然而，现在它重新引起了人们的兴趣——这正是时候：全...` | `土著知识长期以来被科学忽视，有时甚至被反对。然而，现在它重新引起了人们的兴趣——这正是时候：全球...` | `土著知识长期以来被科学忽视，有时甚至受到反对。然而，现在它重新引起了人们的兴趣——这正是时候：全...` | no | no | sampling_noise | sampling_noise |
| 2 | `p1#3` | plain text | `这种知识植根于对生态系统的细致观察，并通过口头方式代代相传，为构建可持续的未来提供了宝贵的钥匙。...` | `这种知识植根于对生态系统的细致观察，并通过口头方式代代相传，为构建可持续的未来提供了宝贵的钥匙。...` | `这种知识植根于对生态系统的细致观察，并通过口头方式代代相传，为构建可持续的未来提供了宝贵的钥匙。...` | no | no | sampling_noise | sampling_noise |
| 3 | `p1#4` | plain text | `联合国教科文组织长期以来在这一领域处于先锋地位。通过其地方和土著知识系统（LINKS）计划，该组...` | `联合国教科文组织长期以来在这一领域处于先锋地位。通过其地方和土著知识系统（LINKS）计划，该组...` | `联合国教科文组织长期以来在这一领域处于先锋地位。通过其地方和土著知识系统 (LINKS) 计划，...` | no | no | sampling_noise | sampling_noise |
| 4 | `p1#5` | plain text | `除了提供实证数据外，土著知识还挑战了科学方法的基础，无论是在伦理的位置、人类与自然的关系，还是观...` | `除了提供实证数据外，土著知识还挑战了科学方法的基础，无论是在伦理的位置、人类与自然的关系，还是观...` | `除了提供实证数据外，土著知识还挑战了科学方法的基础，无论是在伦理的位置、人类与自然的关系，还是观...` | no | no | sampling_noise | sampling_noise |
| 5 | `p1#6` | plain text | `但这种认可必须伴随保障措施——社区的自由和知情同意、利益的公平分享以及防止滥用占有的保护。目标不...` | `但这种认可必须伴随着保障措施——社区的自由和知情同意、利益的公平分享以及防止滥用占有的保护。目标...` | `但这种认可必须伴随着保障措施——社区的自由和知情同意、利益的公平分享以及防止滥用占有的保护。目标...` | no | no | sampling_noise | sampling_noise |
| 6 | `p1#7` | plain text | `通过推广这些知识，联合国教科文组织提醒我们一个显而易见的道理——要理解和保护这个世界，我们可以通...` | `通过推广这些知识，联合国教科文组织提醒我们一个显而易见的道理——要理解和保护这个世界，我们可以通...` | `通过推广这些知识，联合国教科文组织提醒我们一个显而易见的事实——要理解和保护这个世界，我们可以通...` | no | no | sampling_noise | sampling_noise |
| 7 | `p1#16` | plain text | `<style id='1'>中国：传统傣族医学的光辉健康</style><style id='3...` | `<style id='1'>中国：传统傣族医学的光辉健康</style><style id='3...` | `<style id='1'>中国：传统傣族医学的光辉健康</style><style id='3...` | yes | no | rebatch_effect | run_variance |
| 8 | `p1#27` | plain text | `<style id='1'>“小说是人类在诚实叙事中的最后集体边界”</style><style...` | `<style id='1'>“小说是人类在诚实叙事中的最后集体边界”</style><style...` | `<style id='1'>“小说是人类在诚实叙事中的最后集体前沿”</style><style...` | yes | no | rebatch_effect | run_variance |
| 9 | `p2#3` | title | `土著知识如何驱动` | `土著知识如何驱动` | `土著知识如何推` | yes | yes | chain_member | chain_member |
| 10 | `p2#4` | figure_caption | `厄瓜多尔摄影师Carolina Zambrano的作品，采用象征亚马逊土著工艺的棕榈树chamb...` | `厄瓜多尔摄影师Carolina Zambrano的作品，采用象征亚马逊土著工艺的棕榈树chamb...` | `由厄瓜多尔摄影师Carolina Zambrano创作，使用chambira纤维刺绣，这是一种象...` | yes | yes | rebatch_effect | rebatch_effect |
| 11 | `p2#5` | plain text | `从土著的控制燃烧以防止野火的做法，到因纽特人的天气预报，以及一些非洲国家用于蓄水的<style ...` | `从土著的控制燃烧以防止野火的做法，到因纽特人的天气预报，以及一些非洲国家用于蓄水的<style ...` | `从土著的控制燃烧以防止野火的做法，到因纽特人的天气预报，以及一些非洲国家用于蓄水的<style ...` | no | no | sampling_noise | sampling_noise |
| 12 | `p2#7` | plain text | `来自萨摩亚的土著气候记者，为<style id='1'>卫报</style>报道太平洋岛屿问题，...` | `来自萨摩亚的土著气候记者，为<style id='1'>卫报</style>报道太平洋岛屿问题，...` | `来自萨摩亚的原住民气候记者，为<style id='1'>卫报</style>报道太平洋岛屿问题...` | no | yes | sampling_noise | sampling_noise |
| 13 | `p3#1` | title | `科学发现` | `科学发现` | `动科学发现` | yes | yes | chain_member | chain_member |
| 14 | `p4#3` | plain text | `<style id='1'>很 </style>久以前，在卫星绕地球运行之前，波利尼西亚航海家通...` | `<style id='1'>很 </style>久以前，在卫星绕地球运行之前，波利尼西亚航海家通...` | `<style id='1'>很</style>久以前，在卫星绕地球运行之前，波利尼西亚航海家通过...` | no | no | sampling_noise | sampling_noise |
| 15 | `p4#4` | plain text | `还有许多其他例子说明了` | `还有许多其他例子说明` | `还有许多其他例子说明` | no | no | sampling_noise | sampling_noise |
| 16 | `p4#6` | plain text | `在各个不同领域中证明了其价值，` | `在各个领域都证明了其价值，` | `在各个不同领域中证明了其价值` | no | no | sampling_noise | sampling_noise |
| 17 | `p4#7` | fallback_line | `水资源管理，` | `水资源管理，` | `水管理，` | yes | no | rebatch_effect | run_variance |
| 18 | `p4#8` | plain text | `农林业、健康和渔业。这些实践远不止是一系列技术，它们也是一种世界观的表达。例如，纺织品的创作在精...` | `农林业、健康和渔业。这些实践远不止是一系列技术，它们也是一种世界观的表达。例如，纺织品的创作在精...` | `农林业、健康和渔业。这些实践远不止是一系列技术，它们也是一种世界观的表达。例如，纺织品的创作在精...` | no | no | sampling_noise | sampling_noise |
| 19 | `p4#14` | plain text | `随着气候危机加剧和生物多样性崩溃，世界开始转向曾经被忽视的知识体系。根据联合国的数据，土著人民占...` | `随着气候危机加剧和生物多样性崩溃，世界开始转向曾经被忽视的知识体系。根据联合国的数据，土著人民占...` | `随着气候危机加剧和生物多样性崩溃，世界开始转向那些曾经被忽视的知识体系。根据联合国的数据，土著人...` | yes | no | rebatch_effect | run_variance |
| 20 | `p4#15` | plain text | `“我们观察自然，我们的动物和植物。我们是自然的守护者，拥有关于我们环境的大量知识，”乍得的土著M...` | `“我们观察自然，我们的动物和植物。我们是自然的守护者，拥有关于我们环境的大量知识，”乍得的土著M...` | `“我们观察自然，我们的动物和植物。我们是自然的守护者，拥有关于我们环境的大量知识，”乍得的土著姆...` | no | no | sampling_noise | sampling_noise |
| 21 | `p4#16` | plain text | `积累的技能和智慧不仅仅是机械地从一代传递到下一代，还被编纂成复杂的知识体系，正如太平洋和非洲的纺...` | `积累的技能和智慧不仅仅是机械地从一代传递到下一代，还被编纂成复杂的知识体系，正如太平洋和非洲的纺...` | `积累的技能和智慧不仅仅是机械地从一代传递到下一代，还被编纂成复杂的知识体系，如太平洋和非洲的纺织...` | no | no | sampling_noise | sampling_noise |
| 22 | `p4#18` | title | `LINKS计划：推广土著知识` | `LINKS计划：促进土著知识` | `LINKS计划：促进土著知识` | no | no | sampling_noise | sampling_noise |
| 23 | `p4#19` | plain text | `联合国教科文组织的地方和土著知识系统（LINKS）计划成立于2002年，旨在动员地方社区和土著人...` | `联合国教科文组织的地方和土著知识系统（LINKS）计划成立于2002年，旨在动员地方社区和土著人...` | `联合国教科文组织的地方和土著知识系统 (LINKS) 计划成立于2002年，旨在动员地方社区和土...` | yes | no | rebatch_effect | run_variance |
| 24 | `p4#20` | plain text | `LINKS旨在建立土著和地方知识持有者之间的对话，` | `LINKS旨在建立原住民和地方知识持有者之间的对话，` | `LINKS旨在建立原住民和地方知识持有者之间的对话，` | no | no | sampling_noise | sampling_noise |
| 25 | `p4#21` | plain text | `自然和社会科学家、资源管理者和决策者，以确保地方社区在治理中发挥积极和公平的作用。该项目旨在加强...` | `自然和社会科学家、资源管理者和决策者，以确保地方社区在治理中发挥积极和公平的作用。该计划旨在加强...` | `自然和社会科学家、资源管理者和决策者，以确保地方社区在治理中发挥积极和公平的作用。该计划旨在加强...` | no | no | sampling_noise | sampling_noise |
| 26 | `p4#22` | plain text | `LINKS计划目前还承担着其他角色，其中包括主办土著和` | `LINKS计划目前还承担其他角色，其中包括主办土著和` | `LINKS计划目前在其他角色中还负责土著和` | no | no | sampling_noise | sampling_noise |
| 27 | `p5#1` | plain text | `在任何科学教科书中：“我们是水中的人，是唯一真正生活在其中的人。” 当世界上最大的淡水鱼——巨骨...` | `在任何科学教科书中：“我们是水中的人，是唯一真正生活在其中的人。” 当世界上最大的淡水鱼——巨骨...` | `在任何科学教科书中：“我们是水中的人，是唯一真正生活在其中的人。” 当世界上最大的淡水鱼——巨骨...` | yes | no | rebatch_effect | run_variance |
| 28 | `p5#4` | plain text | `黎明散发出一种铁锈般的潮湿气味，夹杂着火盆的烟雾。保马里族是一个约有两千人的土著民族，生活在该国...` | `黎明散发出一种铁锈般的潮湿气味，夹杂着火盆的烟雾。保马里族是一个约有两千人的土著民族，生活在该国...` | `黎明散发着铁锈般的潮湿气味，夹杂着火盆的烟雾。保马里族是一个约有两千人的土著民族，生活在该国西北...` | no | no | sampling_noise | sampling_noise |
| 29 | `p5#5` | plain text | `<style id='1'>在</style>普鲁斯河上，当光线渐渐消退，热气仍在水面上徘徊时，...` | `<style id='1'>在</style>普鲁斯河上，当光线渐渐消退，热气仍在水面上徘徊时，...` | `<style id='1'>在</style>普鲁斯河上，光线渐渐消退，热气仍然笼罩着水面，一条...` | no | no | sampling_noise | sampling_noise |
| 30 | `p5#7` | plain text | `面对对其生存至关重要的鱼类——巨骨舌鱼数量急剧下降的情况，亚马孙州的保马里族参与了一项结合科学与...` | `面对对其生存至关重要的鱼类——巨骨舌鱼数量急剧下降的情况，亚马孙州的保马里族参与了一项结合科学与...` | `面对对其生存至关重要的鱼类——巨骨舌鱼数量的急剧下降，亚马孙州的保马里族参与了一项结合科学与传统...` | no | no | sampling_noise | sampling_noise |
| 31 | `p6#0` | abandon | `{v1}联合国教科文组织《信使》{v2}<style id='3'>2026年1月至3月</st...` | `{v1}联合国教科文组织《信使》{v2}<style id='3'>2026年1月至3月</st...` | `{v1}联合国教科文组织《信使》 {v2}<style id='3'>2026年1月至3月</s...` | yes | no | rebatch_effect | run_variance |
| 32 | `p6#1` | abandon | `IDEAS` | `理念` | `理念` | no | no | sampling_noise | sampling_noise |
| 33 | `p6#3` | plain text | `在一个嘈杂、令人感到幽闭的机器内长时间保持静止。` | `在一个嘈杂、令人感到幽闭的机器内长时间保持静止。` | `在一个嘈杂、令人感到幽闭恐惧的机器内长时间保持静止。` | yes | no | rebatch_effect | run_variance |
| 34 | `p6#5` | plain text | `在量子领域中不断与其他一切纠缠和解纠缠。涉及直接利用量子叠加和纠缠的技术的新量子革命已经在进行中...` | `在量子领域中不断与其他一切纠缠和解纠缠。涉及直接利用量子叠加和纠缠的技术的新量子革命已经在进行中...` | `在量子领域中不断与其他事物纠缠和解纠缠。涉及直接利用量子叠加和纠缠的技术的新量子革命已经在稳步进...` | yes | no | rebatch_effect | run_variance |
| 35 | `p6#6` | title | `传感器读取我们的思想` | `读取我们思想的传感器` | `读取我们思想的传感器` | no | no | sampling_noise | sampling_noise |
| 36 | `p6#7` | plain text | `其中一种技术是量子传感。我们现在拥有可以检测地球重力变化到十亿分之一的量子设备，这不仅有助于研究...` | `其中一项技术是量子传感。我们现在拥有可以感知地球重力变化至十亿分之一的量子设备，这不仅有助于研究...` | `其中一种技术是量子传感。我们现在拥有可以感知地球重力变化到十亿分之一的量子设备，这不仅有助于研究...` | no | no | sampling_noise | sampling_noise |
| 37 | `p6#8` | plain text | `甚至有一些量子传感器可以读取你的想法。一种特殊的脑扫描仪可以像自行车头盔一样佩戴，其灵敏度极高，...` | `甚至还有能够读取你思想的量子传感器。一种可以像自行车头盔一样佩戴的特殊脑扫描仪，其灵敏度高到可以...` | `甚至有量子传感器可以读取你的想法。一种特殊的脑扫描仪，可以像自行车头盔一样佩戴，其灵敏度极高，能...` | no | no | sampling_noise | sampling_noise |
| 38 | `p6#9` | plain text | `同时具有多个数值范围，例如在空间中扩散或同时向两个方向旋转。只有当我们选择测量它们时，才迫使它们...` | `同时具有一系列数值，例如在空间中扩散或同时向两个方向旋转。只有当我们选择测量它们时，才迫使它们在...` | `同时具有多个值，例如在空间中扩展开来或同时向两个方向旋转。只有当我们选择测量它们时，才迫使它们在...` | no | no | sampling_noise | sampling_noise |
| 39 | `p6#10` | plain text | `这种量子纠缠远非自然界中罕见的新现象，也不仅限于两个分离粒子之间“诡异”的心灵感应连接。相反，它...` | `这种量子纠缠远非自然界中罕见的新现象，也不仅限于两个分离粒子之间“诡异”的心灵感应连接。相反，它...` | `这种量子纠缠远非自然界中罕见的新现象，也不仅限于两个分离粒子之间“神秘”的心灵感应连接。相反，它...` | no | no | sampling_noise | sampling_noise |
| 40 | `p6#11` | title | `2025国际量子年` | `2025国际量子年` | `2025年国际量子年` | yes | no | rebatch_effect | run_variance |
| 41 | `p6#13` | plain text | `在这一年中，全球的科学家、教育者和公民被邀请探索和庆祝量子创新。全球活动提升了公众意识并促进了合...` | `在这一年中，全球的科学家、教育者和公民被邀请探索和庆祝量子创新。全球活动提升了公众意识并促进了合...` | `在这一年中，全球的科学家、教育工作者和公民被邀请探索和庆祝量子创新。全球活动提升了公众意识并促进...` | yes | no | rebatch_effect | run_variance |
| 42 | `p7#3` | plain text | `由摩洛哥阿甘树（<style id='1'>阿甘树</style>）的坚果生产的油提供了另一个例...` | `由摩洛哥阿甘树（<style id='1'>阿甘树</style>）的坚果生产的油提供了另一个例...` | `由摩洛哥阿甘树（<style id='1'>阿甘树</style>）的坚果生产的油提供了另一个例...` | no | no | sampling_noise | sampling_noise |
| 43 | `p7#4` | plain text | `并非所有与遗传资源相关的土著知识的商业使用都构成生物盗窃；有些项目是互惠互利的。例如，澳大利亚的...` | `并非所有与遗传资源相关的土著知识的商业使用都构成生物盗窃；有些项目是互惠互利的。例如，澳大利亚的...` | `并非所有与遗传资源相关的土著知识的商业使用都构成生物盗窃；有些项目是互利的。例如，澳大利亚的In...` | no | yes | chain_member | chain_member |
| 44 | `p7#5` | plain text | `然而，生物发现被批评为在土著和其他地方人民开发的知识上“搭便车”。当他们的知识在科学研究、产品开...` | `然而，生物发现被批评为对土著和其他地方人民开发的知识的“搭便车”。当他们的知识在科学研究、产品开...` | `然而，生物发现被批评为对土著和其他地方人民所发展的知识的“搭便车”。当他们的知识在科学研究、产品...` | no | yes | sampling_noise | sampling_noise |
| 45 | `p7#7` | plain text | `卡瓦（<style id='1'>醉椒</style>）是一种原产于太平洋的胡椒科植物，其案例似...` | `卡瓦（<style id='1'>醉椒</style>）是一种原产于太平洋的胡椒科植物，其案例似...` | `卡瓦（<style id='1'>醉椒</style>）是一种原产于太平洋的胡椒科植物，其案例似...` | no | no | sampling_noise | sampling_noise |
| 46 | `p7#8` | plain text | `世界上有着多样的土著人民、文化、语言和知识体系。这些体系经过数百年或数千年的发展，对我们所食用的...` | `<style id='1'>世</style>界上有着多样化的土著人民、文化、语言和知识体系。这...` | `<style id='1'>T </style>世界上有着多样化的土著人民、文化、语言和知识体系...` | no | no | sampling_noise | sampling_noise |
| 47 | `p7#9` | plain text | `研究人员和公司常常寻求土著居民对植物、动物及生态系统中其他非人类生物的特性的见解，以开发新技术和...` | `研究人员和公司常常寻求土著居民对植物、动物及生态系统中其他非人类生物的特性的见解，以开发新技术和...` | `研究人员和公司常常寻求土著对植物、动物及生态系统中其他非人类居民特性的见解，以开发新技术和创新。...` | yes | yes | rebatch_effect | rebatch_effect |
| 48 | `p7#11` | title | `当生物盗窃扎根时` | `当生物盗窃扎根时` | `当生物盗窃扎根` | yes | yes | rebatch_effect | rebatch_effect |
| 49 | `p7#14` | plain text | `他是新南威尔士大学（澳大利亚）艺术学院的教授兼研究副院长，他的研究重点是自然和知识的监管。` | `他是新南威尔士大学（澳大利亚）艺术学院的教授兼研究副院长，他的研究重点是自然和知识的监管。` | `他是新南威尔士大学（澳大利亚）艺术学院的教授兼研究副院长，其研究重点是自然和知识的监管。` | yes | yes | rebatch_effect | rebatch_effect |
| 50 | `p7#17` | title | `如今，许多国家要求土著知识的潜在使用者首先获得知识持有者的同意` | `如今，许多国家要求土著知识的潜在使用者首先获得知识持有者的同意` | `如今，许多国家要求潜在的土著知识使用者首先获得知识持有者的同意` | yes | yes | rebatch_effect | rebatch_effect |
| 51 | `p8#1` | plain text | `要求土著知识的潜在使用者首先从知识持有者那里获得明确的同意，并签署详细说明如何分享利益的协议。` | `要求土著知识的潜在使用者首先获得知识持有者的明确同意，并签署详细说明如何分享利益的协议。` | `要求土著知识的潜在使用者首先获得知识持有者的明确同意，并签署详细说明利益分享方式的协议。` | no | no | sampling_noise | sampling_noise |
| 52 | `p8#2` | plain text | `此外，越来越多的法律要求知识产权申请者——尤其是专利申请者——披露任何用于创造发明的遗传资源或传...` | `此外，越来越多的法律要求知识产权申请者——尤其是专利——披露任何用于创造发明的遗传资源或传统知识...` | `此外，越来越多的法律要求知识产权申请者——尤其是专利申请者——披露任何用于创造发明的遗传资源或传...` | no | no | sampling_noise | sampling_noise |
| 53 | `p8#3` | plain text | `但尽管采取了这些措施，由于系统中存在可被利用的漏洞，生物盗窃仍然时有发生。例如，可以通过从未采纳...` | `但尽管采取了这些措施，由于系统中存在可利用的漏洞，生物盗窃仍然发生。例如，可以通过从未采纳限制性...` | `然而，尽管采取了这些措施，由于系统中存在可利用的漏洞，生物盗窃仍然时有发生。例如，可以通过从未采...` | no | no | sampling_noise | sampling_noise |
| 54 | `p8#5` | plain text | `20世纪90年代，随着一些发展，情况发生了巨大变化。首先，知识产权在世界贸易组织（WTO）协议下...` | `20世纪90年代，随着一些发展，情况发生了巨大变化。首先，知识产权在世界贸易组织（WTO）协议下...` | `在1990年代，随着一些发展，情况发生了显著变化。首先，知识产权在世界贸易组织（WTO）协议下得...` | no | no | sampling_noise | sampling_noise |
| 55 | `p8#7` | plain text | `过去30年间建立的强化国际规则和协议框架，已经带来了一些积极的变化。如今，许多国家` | `过去30年间建立的强化国际规则和协议框架，已经带来了一些积极的变化。如今，许多国家` | `过去30年间建立的强化国际规则和协议框架，带来了一些积极的变化。如今，许多国家` | yes | yes | rebatch_effect | rebatch_effect |
| 56 | `p8#8` | plain text | `这种草已经被申请了专利。根据协议，已经分享的利益包括为第一民族青年提供的就业机会，以及为澳大利亚...` | `这种草已经被申请了专利。根据协议，已经分享的利益包括为第一民族青年提供的就业机会，以及为澳大利亚...` | `根据协议，已经分享的利益包括为第一民族青年提供就业机会，以及为澳大利亚土著提供培训和教育机会的资...` | yes | yes | chain_member | chain_member |
| 57 | `p8#10` | plain text | `生物盗窃问题的根源在于一个历史性的转变：全球社会开始将生物资源视为专有资产，而不是共享遗产的那一...` | `生物盗窃问题的根源在于一个历史性的转变：全球社会开始将生物资源视为专有资产，而不是共享遗产的那一...` | `生物盗窃问题的根源在于一个历史性的转变：全球社会开始将生物资源视为专有资产，而非共享遗产的那一刻...` | yes | yes | rebatch_effect | rebatch_effect |
| 58 | `p8#11` | plain text | `植物、动物和其他生物多样性成分在全球范围内的流通以及不同人群之间相关知识的共享并不是什么新鲜事。...` | `植物、动物和其他生物多样性成分在全球范围内的流通以及不同人群之间相关知识的共享并不是什么新鲜事。...` | `植物、动物和其他生物多样性成分在全球范围内的流通，以及不同人群之间相关知识的共享，并不是新鲜事。...` | no | yes | sampling_noise | sampling_noise |
| 59 | `p8#14` | figure_caption | `在摩洛哥西南部塔夫拉乌特的一个女性合作社的阿甘油生产车间。` | `在摩洛哥西南部塔夫拉乌特的一个女性合作社的阿甘油生产车间。` | `摩洛哥西南部塔夫拉乌特的一家女性合作社的阿甘油生产车间。` | yes | yes | rebatch_effect | rebatch_effect |

Verdict counts over this table:

- `chain_member`: 4 (GAP-01 rule: 4)
- `rebatch_effect`: 8 (GAP-01 rule: 19)
- `run_variance`: 11 (GAP-01 rule: 0)
- `sampling_noise`: 36 (GAP-01 rule: 36)
