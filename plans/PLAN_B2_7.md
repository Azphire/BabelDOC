# PLAN B2.7 — 分位数词表解锁 + 校验规则固化 + 积压维护(1 会话,同会话先完成 b2.6 提交)

前置:LOPO 调参完成,工作区含未提交的 configs/page_types.json diff;用户已将调参会话产出的分位数词表候选拷入 configs/page_types.pctl.json.candidate。

## b2.6(本会话第一个 commit,先行)

提交现有 page_types.json diff:message "batch b2.6: LOPO vocabulary calibration (raw ruleset)",tag batch-b2.6。提交前核对 git status 仅此一文件。

## B2.7 任务

### T2.7a 门禁缺陷修复

spec_check_b2_1.py:373 处(现场定位为准):打分断言改用 `extract_document_features` 产出的文档级向量,与生产路径(page_classifier.py)一致。这是缺陷修复,不受"断言命题零改动"约束——命题本就是"词表可对页打分",喂错向量是实现错误。

### T2.7b 校验规则固化(调参发现 A)

taxonomy 校验器新增:任何 `_pctl` 特征上的正向证据规则(ge/gt 正权重)阈值必须 > 0.5,违者校验报错,错误信息说明依据(常量/全零列的 midrank 恒为 0.5,≤0.5 的 pctl 证据会被空白页满足,击穿正向证据守卫)。`configs/page_features.json` 的 `_allowed_range` 说明同步补述。

### T2.7c 分位数词表采纳

1. 校验 configs/page_types.pctl.json.candidate:通过 T2.7b 新规则与全部既有校验(15 型、policy 齐全、每型有正向 ge/gt);若候选中存在 ≤0.5 的 pctl 证据规则,按调参报告的语义上调至 >0.5 后重测(仅此一类修改,逐条报备)。
2. 以候选词表对全语料重分类,对 page_labels.json 计算一致率(整体 + 分刊物 + LOPO 逐折复算,复用调参会话的折划分);与 raw 词表(0.903 整体 / 0.938 holdout)并列呈报。
3. **采纳判据**:候选整体一致率 ≥ raw 且无任一刊物族下降 > 0.1 → 候选转正为 configs/page_types.json(raw 版本存为 configs/page_types.raw.json 归档);否则保持 raw,候选归档,差异写入交付报告。

### T2.7d 积压维护(均已授权)

1. 缓存指纹收窄:工作区指纹的采集范围从"HEAD + 全部 diff"收窄为 babeldoc/、configs/ 两个路径的内容哈希(git diff 限定 pathspec);门禁脚本与 plans/ 的改动不再作废缓存。b2_5 门禁的指纹敏感性断言同步改为对 configs 内文件生效。
2. gate_cache 治理:run_all 启动时报告缓存体积;超过 configs 中新参数 gate_cache_max_gb(默认 8,带 allowed_range)时按 LRU 清槽;`--clear-cache` 保留。
3. runner 完成标记:run_all 结束时写 working 目录 run_all.done.json(退出码、总耗时、时间戳),供外部轮询判断完成,替代不可靠的后台包装器回执。
4. CLAUDE.md §5 追加两条(原文照录):「plans/PLAN_<batch>.md 默认属于该批次门禁白名单,无须逐批枚举。」「_pctl 特征的正向证据规则阈值必须 > 0.5(常量列 midrank 恒为 0.5)。」

## 门禁 `spec_checks/spec_check_b2_7.py`

正向:1) b2_1 修复后以含 pctl 规则的最小合成词表跑通打分(不再 KeyError);2) T2.7b 规则:≤0.5 的 pctl 证据被校验拒绝、>0.5 被接受;3) 采纳判据的两组一致率数字入断言(按 T2.7c 实测写死为回归基线);4) 指纹收窄:改 spec_checks 任一文件不作废缓存、改 configs 任一文件作废;5) run_all 全量全绿(06c 以当前词表 ≥ 0.7),run_all.done.json 生成且字段齐全。

负向:6) page_labels.json、registry、manifest 零改动;7) 若 T2.7c 判据不满足,configs/page_types.json 与 batch-b2.6 逐字节相同;8) 改动 ⊆ {spec_checks/*, babeldoc/magazine/{taxonomy.py, page_features.json 说明, corpus.py 如需}, configs/{page_types*.json, page_features.json, 新缓存参数}, CLAUDE.md, plans/PLAN_B2_7.md};上游零改动;注释无中文。

## 明确不做

不引入 LLM/VLM(B3);不动特征提取;不再调任何阈值(T2.7c 的 >0.5 上调除外);不动 label_agreement_min。
