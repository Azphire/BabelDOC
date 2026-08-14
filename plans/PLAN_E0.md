# PLAN E0 — 评估阶段盘点:证据台账、指标合同、缺口登记(1 会话,零新指标零新运行)

前置:batch-b8.4;上游基线冻结于 examples/baseline/(manifest + 六 PDF + 日志 + 缓存备份);背景章 2.7 定稿(评估仪器三层:几何/拼接点标注/文档级一致性)。本批次**只读盘点**,不实现指标、不跑翻译、不改配置——产出三份文档,是 E1–E4 的合同。

## 产出

### D1 证据台账 docs/eval/evidence_ledger.md

逐条清点全部可引冻结数字,每条:数字 / 出处(tag + 文件路径)/ 论文用途 / 状态(直接可引 | 需三跑 | 需重算)。至少覆盖:
- 链线:边界一致 26/26 与零假阳性(b4.2)、守恒实录与 A/B 缺陷对(b5.3)、零外溢像素证据(b5.3 表 3);
- 分类线:LOPO 逐折矩阵与 0.938/0.903 区分(调参会话 + b2.7)、刷新后 0.879/1.000(b7.5.1)、Courier-zh 观察基线 0.250/0.714;
- VLM 线:四点消融曲线与 policy 级零增益结论(两轮消融会话);
- HITL 线:四人名落地、页型传导链、刊名三态(4 统一/1 译对拒放/1 界面不可达)(b7.3/b7.5.2/b8.4);
- ReAct 线:防御纵深实录(b8.3)、拒绝分类学三案例(b8.4 sidecar,含 commit message 措辞出入注记);
- 上游基线:六样张 sha/耗时/五缺陷家族清单(baseline.report.md);
- 方法论:采样方差 0.989/0.995、U+001A 归因修正措辞(基础设施特属,上游无此层)。

### D2 指标合同 docs/eval/metric_contract.md

逐指标一行:名称 / 公式出处(背景章 eq 号或新定义)/ 数据源(冻结产物或 E2 运行)/ 工具状态 / 归属批次。已定条目:
| 指标 | 出处 | 工具状态 | 批次 |
|---|---|---|---|
| mid-unit page-break rate | 新定义(2.7 承诺形式化) | 需新建(排版后末行几何,b5.3 §1b 方法推广) | E1 |
| block conservation invariant | 新定义 | 现成(链 sidecar 断言泛化为指标) | E1 |
| LTCR | eq:ltcr | 需对齐(term_consistency 按 C(k,2) 成对定义正名) | E1 |
| Overlap / Alignment | eq:overlap / eq:alignment | Overlap 近似现成需对齐;Alignment 需新建 | E1 |
| policy 级一致率 | 既有定义 | 现成 | E1 |
| image-area delta / page-count delta / image IoU | 导师图形学指标 | 需新建(IL box 集,确定性) | E1 |
| GEMBA-MQM 拼接点标注 | kocmi2023 + 拼接点协议 | 需新建(缓存判官,模型待用户定) | E2 |
| d-BLEU(诊断) | liu2020mbart | 需新建(脚注级) | E2 |
| BlonDe(诊断,仅 zh→en) | jiang2022blonde | 可选 | E4 |

### D3 缺口登记 docs/eval/gap_register.md

已知缺口逐条:补法 / 成本 / 不补的论文措辞。至少:邻段漂移归因需三跑设计(chain_off ×2 ignore_cache + chain_on;成本约一次 Courier 全跑 ×2);escalation 零活证据(合成覆盖声明);judge 模型同源偏倚(用户决策:异源 judge 或声明+人工抽验);v1 修复零落地的三段式措辞(已定,登记为合同);上游版本对措辞(main-post-v0.6.4,README-only delta);五缺陷家族 → E3 对照轴的映射表。

## 门禁 spec_check_e0

轻量:三文档存在且台账每条含 tag+路径;台账内全部路径实际存在(死链零容忍);D2 表与背景章 eq 标签逐一可解析(grep .tex);零代码零配置改动(diff 白名单 = docs/eval/* + plans/PLAN_E0.md)。

## 明确不做

任何指标实现、任何翻译运行、任何阈值改动;E1–E4 的计划文件由用户与规划侧另出。
