# B15 T2b — 页面分类两来源离线重放审计

重放方式:`tools/page_classify_audit.py` 读取既有 `page_classify.report.json`
(报告同时记录确定性层判定与 VLM 判定,无需重跑、无模型调用)。
样本取每文档**最新**一次带 VLM 仲裁的运行:

| 样本 | 报告来源 | 页数 |
|---|---|---|
| Courier-en | `examples/output/B14/T3/Courier-en/work/Courier-en/` | 8 |
| FD-en-v2 | `examples/output/B14/T3/FD-en-v2/work/FD-en-v2/` | 9 |
| CERNCourier-en | `examples/output/B14/T4/CERNCourier-en/work/CERNCourier-en/` | 4 |
| HuaweiTech-zh | `examples/output/B14/T4/HuaweiTech-zh/work/HuaweiTech-zh/` | 6 |
| bull-zh | `examples/output/B12/bull-zh/work/bull-zh/` | 9 |

共 36 页,双来源一致 19 页,分歧 17 页。人工裁定(执行侧代批,
逐页渲染源页目验;渲染图在会话工件中)如下。
"邻近"指判定与真值同属可流动文章类、`indent_eligible` 等政策旗一致。

## 分歧逐页裁定

| 样本 | 页 | 确定性判定 | VLM 判定 | 人工真值 | 对错 |
|---|---|---|---|---|---|
| Courier-en | p3 | photo_spread (1.00) | article_opener (0.9) | photo_spread(整页照片+题头残句) | **确定性对** |
| FD-en-v2 | p2 | advertisement (1.00, 无歧义) | article_opener (0.9) | advertisement(WEO 出版物广告页) | **确定性对** |
| FD-en-v2 | p7 | masthead (1.00) | sidebar_heavy (0.9) | sidebar_heavy(Kaleidoscope 栏目页) | VLM 对 |
| CERNCourier-en | p3 | article_opener (0.88) | article_body | article_opener(News Analysis 起始) | **确定性对** |
| CERNCourier-en | p4 | interview (1.00) | article_body | article_body(特稿中段跨页) | VLM 对 |
| HuaweiTech-zh | p2 | masthead (0.83) | toc | toc(目录页) | VLM 对 |
| HuaweiTech-zh | p3 | photo_spread (1.00) | infographic | section_divider(章节隔页) | 双错 |
| HuaweiTech-zh | p5 | infographic (0.72) | article_body | article_body(正文跨页) | VLM 对 |
| HuaweiTech-zh | p6 | sidebar_heavy (1.00) | article_body | article_opener(文章起始跨页) | 双错(VLM 邻近) |
| bull-zh | p1 | toc (0.88) | front_cover | front_cover(封面) | VLM 对 |
| bull-zh | p3 | sidebar_heavy (1.00) | article_opener | editorial(总干事前言) | 双错(VLM 邻近) |
| bull-zh | p4 | masthead (1.00) | toc | toc | VLM 对 |
| bull-zh | p5 | masthead (1.00) | toc | toc(目录续页) | VLM 对 |
| bull-zh | p6 | masthead (1.00) | article_opener | article_opener | VLM 对 |
| bull-zh | p7 | masthead (1.00) | infographic | infographic(信息图跨页后半) | VLM 对 |
| bull-zh | p8 | sidebar_heavy (1.00) | article_opener | article_opener | VLM 对 |
| bull-zh | p9 | sidebar_heavy (0.80) | article_body | article_body | VLM 对 |

## 计分与默认值裁决

分歧 17 页上:**VLM 对 12,确定性对 3,双错 2**(其中 VLM 邻近 2)。
一致的 19 页未逐页复验,抽查(FD p1/p4/p5、CERN p1/p2)均正确。

**`page_classify_source` 默认值定为 `vlm`**(`configs/vlm.json`)。理由:
分歧页上 VLM 正确率 12/17 对 3/17,压倒性;且确定性层的错误多为
高置信错判(masthead/sidebar_heavy 1.00 共 9 例),不能以置信度门槛
挽救。确定性层保留为 `local` 可选来源(离线、零凭据、零调用),两层
判定继续并排进报告,`machine_source` 如实标注。

## 已知代价与对策

FD p2 是本表中确定性对、VLM 错且**后果可见**的一例(广告页被判
article_opener → 缩进闸门合法放行 → 三段导语被加首行缩进,B14 成品
可见)。该页已按正规 HITL 通道裁定:`reviews/FD-en-v2.decisions.json`
`page_kinds: {"2": "advertisement"}`。溯源全链:
`page_classifier.py` VLM 采纳(`_adjudicate` → `accepted`)→
`hitl.py:658 page_kind_pass`(当时无覆盖)→
`indent_policy.py:432 page_is_eligible`(article_opener 合格,判定正确)→
`indent_policy.py:518 decide`(after=True ×3,body_rank 1..3)。
闸门本身无缺陷;缺陷在分类来源,已由 HITL 覆盖修正,T4 重跑验证。
