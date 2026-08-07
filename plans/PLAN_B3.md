# PLAN B3 — Prompt 基建 + VLM 分类兜底(2 会话)

前置:batch-b2.7。本批次引入项目首个 LLM/VLM 调用点。设计约束回顾:prompt 一律外置带哈希清单(§4.3);所有调用经缓存,同输入零 API 请求(§4.8);代码零页型名(§4.2);上游零改动(VLM 兜底整体落在 PageClassifier 内部)。

## 规格输入(来自 B2.7 residual)

- opener↔body 判别信号不在几何特征集内,两套词表反向失误共同证明——VLM 的首要任务。
- CERN 拼版页单判定模型先天不适——VLM 输出允许"主判定 + 次判定(拼版另一半)"。
- 路由界面:ambiguous 标记(top1−top2 < ambiguity_margin),实测错误召回率 100%,当前约 17/31 页命中。

## 任务

### T3.1 Prompt 基建

- `prompts/page_classify_vlm.md`:模板变量 `{taxonomy}`(由 page_types.json 的 name+description 注入,不含 policy 与阈值)、`{deterministic_verdict}`(确定性层的 top-3 及得分,供参考不强制)、`{page_context}`(页号/总页数)。要求 VLM 仅从词表内选择,输出严格 JSON:`{"kind": ..., "confidence": 0..1, "secondary_kind": ...|null, "secondary_reason": ...|null}`,secondary 仅用于拼版/复合版面。
- `babeldoc/magazine/prompt_loader.py`:加载 + 变量替换 + 未替换变量报错;每次加载把 (文件路径, SHA-256) 记入 working_dir 的 `prompts.manifest.json`(追加去重)。
- 交付时把 prompt 文件哈希写入交付报告(建立"prompt 版本可审计"的首个实例)。

### T3.2 缓存 VLM 客户端

- `babeldoc/magazine/vlm_client.py`:OpenAI-compatible 多模态调用;配置全部来自 `configs/vlm.json`(model、base_url、max_retries、render_dpi、timeout,各带 allowed_range;enabled 默认 false)。API key 仅从环境变量读取(变量名在 vlm.json 中声明),任何文件不落 key。
- 缓存:项目本地 cache DB(examples/cache),key = SHA-256(model ‖ 参数 ‖ prompt 文件哈希 ‖ 渲染后 prompt ‖ 图像 sha256)。命中零网络请求(计数桩验证)。
- 输出校验:JSON 可解析、kind ∈ 词表、confidence ∈ [0,1];违规重试一次(重试注明前次违规);再违规返回"拒绝"结果,调用方回退确定性判定。VLM 永不越过词表——词表外字符串一律按违规处理。

### T3.3 兜底路由接入 PageClassifier

- `page_classifier.py`:configs/vlm.json enabled 且页被标记 ambiguous 时,渲染该页(pymupdf,render_dpi)调 VLM;成功则 `page_kind` 取 VLM kind、`page_kind_conf` 取其 confidence、`page_kind_source = "vlm"`;拒绝/失败则保留确定性判定(source 仍 deterministic),失败原因入 sidecar。secondary_kind 只进 sidecar(`page_classify.report.json` 增列),不进 IL(schema 冻结)。
- enabled=false(默认)时行为与 batch-b2.7 逐位一致(门禁负向断言)。

### T3.4 评估工具(报告型,非门禁)

`tools/vlm_classify_eval.py`:对全语料以"确定性 + VLM 兜底"完整运行,对 page_labels.json 产出:VLM 回退率、VLM 在被路由页上的一致率、组合系统整体/逐刊一致率(对照纯确定性 0.903)、逐页判定来源表、缓存命中数与估算调用成本。输出 `examples/output/b3/vlm_eval.report.json` + 人读摘要。**结果只入报告,不设硬门禁**——组合系统是否更好由数字说话,写入交付,不许为达标调 prompt 之外的任何东西;prompt 调整允许,每次调整记录哈希与前后数字(prompt 迭代日志)。

### T3.0 积压维护(授权,会话一开始做)

1. 缓存指纹排除 configs/gate_cache.json 与 configs/vlm.json 中不影响产物的键(仅 render_dpi 影响 VLM 缓存 key,由 T3.2 的 key 设计覆盖,不需指纹管)。
2. 退役 spec_check_b2_5 的 EXPECTED_RED 断言 05(前提已随 06c 转绿失效;此为断言命题的显式授权变更,commit message 注明)。
3. 修正 artifacts.py docstring 的门禁计数陈旧表述(重新推导数字或改为不含具体数字的表述)。
4. CLAUDE.md §4 追加(原文照录):「VLM 输出必须约束在声明词表内,越界输出按违规处理并回退确定性判定;VLM 判定只写 pageKindSource="vlm",次判定与失败原因一律走 sidecar。」

## 门禁 `spec_checks/spec_check_b3.py`(全部用桩客户端,无 API key 全绿)

正向:1) prompt loader:变量替换、未替换报错、manifest 记录哈希且与文件实算一致;2) 桩客户端注入合法/越界/坏 JSON/超时四类响应,分别验证:采纳、重试后回退、重试后回退、回退,sidecar 记录原因;3) 缓存:同 (prompt哈希,图像,参数) 二次调用桩计数不增;改 prompt 文件一字节后 key 变化;4) enabled=false 全语料产物与 batch-b2.7 逐位一致(render_diff + checkpoint 属性比对);5) enabled=true + 桩固定应答:被路由页 pageKindSource="vlm",未路由页 deterministic,守恒(页数/段落数不变);6) run_all 全量全绿。

负向:7) grep 全部新增代码零页型名字符串(词表注入只经 JSON 读取);8) 任何文件不含 API key 模式(简单正则扫描 sk- 等);9) 改动 ⊆ {babeldoc/magazine/*, prompts/*, configs/*, tools/*, spec_checks/*, CLAUDE.md, plans/PLAN_B3.md};上游零改动;注释无中文。

## 会话切分建议

会话一:T3.0 + T3.1 + T3.2 + 门禁 1/3/7-9。会话二:T3.3 + T3.4 + 其余门禁 + 真实 API 冒烟(T3.4 报告)。

## 明确不做

不做拼版切分(secondary_kind 是 sidecar 级过渡方案);不迁移术语抽取模板(留给 B4,届时该文件本就要动);不动词表阈值;不让 VLM 结果反写标签或词表。
