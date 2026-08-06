# PLAN B2.3 — 评分证据守卫 + 两项收尾(1 会话,微批次)

前置:B2.2 全绿已提交(batch-b2.2)。本批次是调参会话(LOPO)的最后一个机制前置。

## 目标

1. 查明 B2.2 报告的证据矛盾:Vogue-en PDF p2(0-based p1,OMEGA 整版广告)被描述为"零段落、全部原始特征为 0",但 pctl 摘要表中该页 image_area_ratio 分位为 .833(三页最高)。两者不相容。
2. 评分语义补洞:类型得分要求正向证据,杜绝全零/低证据向量靠 `le/lt` 谓词满分。
3. 历史门禁 diff 基准统一为 tag 锚定。

## 任务

### T2.3a 证据取证(先于一切修改)

从 batch-b2.2 的 Vogue-en checkpoint 与 `page_classify.report.json` 提取该页完整原始特征向量与逐类型得分,给出结论:report 表述错误(该页 image_area_ratio 实为正)、或 pctl 表转录/生成错误、或存在真实缺陷(如 midrank 对全零列的处理异常)。若是真实缺陷,停止并报告,不在本批次顺手修。

### T2.3b 正向证据守卫(声明式)

`taxonomy.py` 评分语义修订:一个类型对某页的得分为 0,除非该页至少满足该类型的一条 `ge`/`gt` 型正权重谓词("正向证据")。`configs/page_types.json` 顶层加开关 `require_positive_evidence: true`(布尔,记入 config 哈希清单)。校验器同步:任何类型若不含至少一条 ge/gt 正权重规则,校验报错(现场检查 15 型种子词表是否都满足;不满足者本批次允许为其添加一条结构合理的 ge 规则,属机制配套,不算调参,逐条在交付报告注明)。

### T2.3c 门禁锚定统一

锚定改造对象为 spec_check_b0/b1/b2/b2_2 四个门禁,统一为:对应 tag 存在时读
`batch-<n>^..batch-<n>` 增量(文件内容经 `git show batch-<n>:<path>` 读取),否则读工作区对 HEAD。
四个历史门禁 + spec_check_b2_2 复跑全绿。

> 计划修订(B2.3 会话内,由计划作者裁决):初稿只点名 b0/b1/b2,漏了 batch-b2.2 亦按
> "工作区对 HEAD" 提交,复跑时必然把 B2.3 的未提交改动误判为越界,使负向断言 7 与正向
> 断言 5 互斥。修订后两者重新一致,不构成实现偏离,故不登记 WAIVERS。

## 门禁 `spec_checks/spec_check_b2_3.py`

正向:1) T2.3a 结论以数据形式断言(按取证结果写具体断言);2) 零段落合成页在全部 15 型上得分为 0,判定落 `default_type` 且 conf=0;3) 全语料重分类:每页仍有判定、conf ∈ [0,1];守卫开启前后,**有正向证据的页判定不变**(回归断言);4) 校验器拒绝无 ge/gt 正权重规则的类型;5) 四历史门禁 + b2_2 复跑全绿。

负向:6) 除 T2.3b 允许的"补一条 ge 规则"外,page_types.json 既有阈值/权重零改动(diff 白名单核对);7) 改动文件 ⊆ {taxonomy.py, page_types.json, 三个历史 spec_check, spec_checks/spec_check_b2_2.py, spec_check_b2_3.py};上游零改动;注释无中文。计划修订文本(plans/PLAN_B2_3.md、CLAUDE.md §5 追加)不计入白名单核对。

## 明确不做

不做拼版检测;不调参;不填 page_labels.json;不动特征提取。
