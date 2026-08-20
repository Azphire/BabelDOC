# PLAN B9.7 — 决策按 detector kind 分轮(微批次,1 会话)

前置:batch-b9.6。规格即当次 prompt,本文件是其归档。

## T0 — .gitattributes 钉 LF

b8.4/b9.6 的 prompt 摘要断言读的是文件字节,`core.autocrlf=true` 的 clone
会把同一份文件摘成另一个值。根目录 `.gitattributes` 钉 LF,至少覆盖
`prompts/ configs/ spec_checks/ docs/`,并覆盖 `examples/output/**/prompt_*/`
下的冻结 prompt 副本(重放据以复现 cache_key)。

一处显式例外:`docs/eval/results_*/` 不钉。那里的每个文件都由工具重算到临时
目录后与在库副本逐字节比对,而工具写的是运行平台的换行;钉死一种换行会让该
比对在其他平台失败。要把它纳入钉法,得先改写工具,不属换行改动。

涉摘要断言在 LF 语义下复验(树上 prompt 摘要 = b9.6 末轮摘要;b9.6 两个重放
点的 cache_key 从冻结输入复现)。

## 机制(GAP-25 剩余修法之一,结构性)

controller 决策改为按 detector kind 分轮:

- 每轮只呈现单一 kind 的 findings 与其适用动作;词表在轮内收窄,轮外动作名
  按违规拒绝。
- kind 迭代序由 `configs/decision_rounds.json` 声明,代码不按 kind 分支。
  声明须恰好覆盖检测器实际抛出的全部 kind,缺项/多项/重复一律报错。
- 无 findings 或无动作应答的 kind 不发请求。
- LLM 仍在轮内自主选择(含 `none`)。
- 总轮数上限与收敛守卫语义不变:一次迭代 = 全部 kind 过一遍;守卫分母仍是
  迭代开始时的全部未处理发现;回滚撤销该迭代所有轮的写入。
- 决策缓存 key 含 kind(经 round identity),旧缓存自然失效属预期。
- 迭代记录保留原有顶层键(`decision`/`request`/`executed`/`applicability`),
  取值为各轮聚合;`rounds` 逐轮完整留痕。

## 验证

- b9.6 三重放点复跑(真实采样,绕缓存):`synthetic_contain`、`courier_p1`、
  `cern_p1`,目标三点全中。
- b8.4 十九发现谱零回归。
- b9.5 守卫合成谱零回归(经完整 loop,桩驱动)。

驱动 `examples/output/b9_7/scripts/replay_b9_7.py` 直接 import b9.6 的驱动,
样本不重建。

## 门禁

`spec_checks/spec_check_b9_7.py`:分轮结构断言、kind 序确定性与完备性、
轮内词表与渲染文本收窄、cache key 含 kind、一次迭代 = 全部轮、重放三点、
两个零回归面、报告与冻结判定一致、范围负向断言。

## 负向

改动 ⊆ `{babeldoc/magazine/react/controller.py, configs/, prompts/,
spec_checks/, .gitattributes}` 加本批证据目录 `examples/output/b9_7/` 与本
文件;上游零改动;真值与裁决只读;prompt 与 `configs/repair_actions.json`
本批不动一字(断言之)。

## 明确不做

检测器改动;`resolve_collision` 自动化;prompt 措辞;gap register 编辑;F2。
