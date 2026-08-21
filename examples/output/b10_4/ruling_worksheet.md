# B10.4 ruling worksheet

Machine written. Nothing here is a ruling: the ruling is `reviews/<sample>.decisions.json`, which only you write.


## 1. Courier-zh page kinds

| page | machine kind | conf | ambiguous | corpus/page_labels.json accepts |
| --- | --- | --- | --- | --- |
| 1 | `sidebar_heavy` | 1.0 | False | `toc`, `editorial`  <-- disagrees |
| 2 | `article_opener` | 0.8125 | True | `article_opener` |
| 3 | `advertisement` | 1.0 | False | `photo_spread`  <-- disagrees |
| 4 | `sidebar_heavy` | 1.0 | True | `article_body`  <-- disagrees |
| 5 | `article_opener` | 1.0 | True | `article_opener` |
| 6 | `sidebar_heavy` | 1.0 | True | `article_body`  <-- disagrees |
| 7 | `sidebar_heavy` | 1.0 | True | `article_opener`  <-- disagrees |
| 8 | `sidebar_heavy` | 1.0 | True | `article_body`  <-- disagrees |

## 2. Harvested personal names, by sample


### Courier-zh — 23 candidates, 15 the model called a person

| source | offered target | model says person | first page |
| --- | --- | --- | --- |
| `Agnès Bardon` | `Agnes Bardon` | yes | 1 |
| `Anna Ruohonen` | `Anna Ruohonen` | yes | 1 |
| `Anuliina Savolainen` | `Anuliina Savolainen` | yes | 1 |
| `Daniel Robinson` | `Daniel Robinson` | yes | 1 |
| `David Jefferson` | `David Jefferson` | yes | 1 |
| `Indigenous Peoples` | -- | no | 1 |
| `Intangible Cultural Heritage` | -- | no | 1 |
| `Jim Al-Khalili` | `Jim Al-Khalili` | yes | 1 |
| `Katerina Markelova` | `Katerina Markelova` | yes | 1 |
| `Laetitia Kaci` | `Laetitia Kaci` | yes | 1 |
| `Lagipoiva Cherelle Jackson` | `Lagipoiva Cherelle Jackson` | yes | 1 |
| `Marcelo Silva de Sousa` | `Marcelo Silva de Sousa` | yes | 1 |
| `Sisco Auala` | `Sisco Auala` | yes | 1 |
| `Zam Caro` | `Zam Caro` | yes | 3 |
| `Delsie Betty Bosi` | `Delsie Betty Bosi` | yes | 4 |
| `Hindou Oumarou Ibrahim` | `Hindou Oumarou Ibrahim` | yes | 4 |
| `Salanieta Kitolelei` | `Salanieta Kitolelei` | yes | 4 |
| `Associated Traditional Knowledge` | -- | no | 8 |
| `Benefit Sharing` | -- | no | 8 |
| `Biological Diversity` | -- | no | 8 |
| `Genetic Resources` | -- | no | 8 |
| `Intellectual Property` | -- | no | 8 |
| `Nagoya Protocol` | -- | no | 8 |

### AramcoWorld-en-v2 — 11 candidates, 1 the model called a person

| source | offered target | model says person | first page |
| --- | --- | --- | --- |
| `Contracts Support` | -- | no | 2 |
| `Martinez Print` | -- | no | 2 |
| `Public Affairs` | -- | no | 2 |
| `RR Donnelley` | -- | no | 2 |
| `Wetmore Web` | -- | no | 2 |
| `Author’s Corner` | -- | no | 3 |
| `DANIIL USM` | `达尼尔·乌斯姆` | yes | 3 |
| `Early America’s Love` | -- | no | 3 |
| `FRONT COVE` | -- | no | 3 |
| `Safeguarding Samarkand’s Monuments` | -- | no | 3 |
| `What’s Online` | -- | no | 3 |

### FD-en-v2 — 14 candidates, 2 the model called a person

| source | offered target | model says person | first page |
| --- | --- | --- | --- |
| `COMMODITIES Critical` | -- | no | 1 |
| `ECONOMIC THEORY Robert Skidelsky` | -- | no | 1 |
| `TA RY` | -- | no | 1 |
| `TRADE POLICY Jamieson Greer` | -- | no | 1 |
| `FFER STAU` | -- | no | 2 |
| `Macroeconomic Consequences` | -- | no | 2 |
| `Trade-Offs Defense` | -- | no | 2 |
| `Adam Smith’s` | `亚当·斯密` | yes | 3 |
| `Quarterly Publication` | -- | no | 3 |
| `Righting Globalization’s Wrongs` | -- | no | 3 |
| `Trade Cooperation` | -- | no | 3 |
| `Understanding Geoeconomics` | -- | no | 3 |
| `RD IFFO` | -- | no | 4 |
| `Ali Abbas` | `阿里·阿巴斯` | yes | 5 |

### Vogue-en — 11 candidates, 5 the model called a person

| source | offered target | model says person | first page |
| --- | --- | --- | --- |
| `American Olympic` | -- | no | 3 |
| `FLEX PACE` | -- | no | 3 |
| `Go Time` | -- | no | 3 |
| `Ground Sanaz Toossi` | `萨纳兹·图西` | yes | 3 |
| `Looking Glass Sam McKinniss’s` | `萨姆·麦金尼斯` | yes | 3 |
| `McGirr’s McQueen Seán McGirr` | `肖恩·麦吉尔` | yes | 3 |
| `Miracle Drip` | -- | no | 3 |
| `PROP STYLIST` | -- | no | 3 |
| `VO GU` | -- | no | 3 |
| `Wire Adrien Brody` | `艾德里安·布罗迪` | yes | 3 |
| `Zac Zac Posen’s` | `扎克·波森` | yes | 3 |
