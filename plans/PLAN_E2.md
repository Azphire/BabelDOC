# PLAN E2 — 付费运行:三跑归因、拼接点判官、terra 补算(2 会话)

前置:batch-e1.2。本批次是评估阶段全部 API 支出所在;预算量级:R1 约 90 次翻译调用、R2 ≤ 70 次判官调用、terra 18 次。judge 模型由用户在 configs 定稿(建议 gpt-5.6-terra:异族于被测 gpt-4o、传输配置现成;论文三件套声明:异族判官 + 缓存钉版 + 人工抽验)。

## T-E2.1(会话一):R1 三跑与链 A/B

- 运行:Courier-en 全栈配置下 chain_off ×2(ignore_cache,独立采样)+ chain_on ×1(缓存冻结);产物按 E1 保留策略入 docs/eval/results_e2/ 引用、大件留工作区并记 sha。
- 归因表:A-12/A-13 的 15 段邻段漂移逐段三列(off₁ vs off₂ vs on)——off₁≠off₂ 处归采样噪声,off₁=off₂≠on 处归重组批次效应;结论写入台账替换 needs-recompute 状态。
- 链 A/B 指标级:两臂产物过 tools/eval_report.py 全指标(M1 分层、M2、M3、几何组),兑现 E1.2 遗留 1;7→8 边界在两臂的 M1 判定 + A-09 语义证据并列成表(论文表 X-1 的指标级伴表)。
- 门禁:三跑产物存在与 sha 登记;归因表每段判定可从三列复算;零真值/词表改动。

## T-E2.2(会话二):R2 判官与收尾

- 拼接点协议形式化(docs/eval/splice_protocol.md):测试点集 = chain_labels 全部 linked 正样本(5)+ Courier-en 7→8 的三方(上游/off/on);每点提交判官:源文窗口 + 两侧译文窗口,MQM 类别/严重度严格 JSON;prompts/splice_judge_mqm.md 外置,缓存客户端,judge 模型钉版记入每行结果。
- 运行:全部测试点 × 全部可用配置臂(上游基线 PDF 文本提取窗口 + fork off/on),预计 ≤ 70 次;无效输出重试一次后记 judge_refused,不硬凑。
- 人工抽验:输出抽验清单(建议 ≥ 5 点)留给用户逐条核 MQM 标注,用户核验结果以裁决文件形式入库(与 HITL 同族纪律)。
- terra policy 列 18 次补算,C-04 收官四档齐。
- E-09 收官:合成覆盖声明按 gap_register 措辞落台账,不跑 R3。
- 汇总:docs/eval/results_e2/ 全表;台账/缺口登记全面刷新(needs-recompute 清零或降级为声明)。

## 门禁 spec_check_e2

三跑独立性(两 off 臂 cache_key 不同且至少一段译文不同——真采样而非缓存复读);判官输出全谱校验(类别 ∈ MQM 词表、严重度 ∈ 枚举);人工抽验清单存在且非空;台账死链复跑;白名单 = docs/eval/* + prompts/splice_judge_mqm.md + tools/ + configs/(judge 条目)+ spec_checks/*;上游零改动;真值/裁决只读。

## 明确不做

R3 实跑;zh 校准;任何机制改动;论文正文。
