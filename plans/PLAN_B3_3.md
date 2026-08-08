# PLAN B3.3 — 传输层能力配置 + 消融协议落地 + 覆盖率口径(1 会话,微批次)

前置:batch-b3.2;模型消融会话报告(gpt-4o 不达标;5.6 族被传输层阻断)。

## 任务

### T3.3a 传输层能力声明式化

`configs/vlm.json` 新增两键(均入 VLM 缓存 key 的 params 字段):

- `token_parameter`: `"max_tokens" | "max_completion_tokens"`(默认 `max_tokens`,保持既有行为)
- `temperature`: 数值 或 `null`(null = 请求中省略该字段,采用服务端默认;默认保持 0.0)

`vlm_client.py` 按此构造请求,移除硬编码。校验器:token_parameter 限两枚举值;temperature 为 null 或落在 allowed_range。**不做 400 自动改参重试**——参数错配是配置错误,应当显式失败,不许客户端静默换契约。description 补消融协议一句(原文照录):"Ablation protocol: each model runs at its own supported minimum-variance setting; the setting is part of the cache key and must be reported alongside any accuracy figure."

### T3.3b 覆盖率口径

`tools/vlm_classify_eval.py` 新增并列指标 `label_set_coverage`:以 {主判定} ∪ {secondary_kind(非 null 时)} 作为预测集,真值多标签数组作为目标集,预测集 ∩ 目标集 ≠ ∅ 记命中;另单列"secondary 增益页"(仅靠 secondary 才命中的页)。原单点命中指标名义、算法、位置零改动,两列并排输出。确定性层无 secondary,其覆盖率列 = 单点列(自然对照)。

### T3.3c 门禁 `spec_checks/spec_check_b3_3.py`

正向:1) 桩验证 token_parameter 两枚举各自出现在请求形状中、temperature=null 时请求不含该字段;2) 两新键任一变化则缓存 key 变化(既有 key 在默认配置下不变——后向兼容断言:默认配置的 key 与 batch-b3.2 逐字节一致,已缓存应答不作废);3) 覆盖率指标:构造用例(secondary 命中/不命中/null)三态正确,单点指标输出与 batch-b3.2 逐字节一致;4) run_all 全绿。
负向:5) 无 400 自动改参逻辑(grep 重试路径不含参数名切换);6) 改动 ⊆ {babeldoc/magazine/vlm_client.py, configs/vlm.json, tools/vlm_classify_eval.py, spec_checks/*, plans/PLAN_B3_3.md};上游零改动;注释无中文;无 API key。

## 明确不做

不改 prompt(留给随后的评估会话按 T3.4 迭代规则做);不动路由/词表/标签;不为 5.6 族做任何模型特判(能力差异全部经配置表达)。
