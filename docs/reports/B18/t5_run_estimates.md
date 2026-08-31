# T5 全语料十二跑 · 开跑前预估(2026-08-31)

依据:B17 温跑实测(六样本 468s、缓存 100% 命中、零翻译请求)与本批 T1–T4 已跑五单样(ABB/fd/Courier-zh×2/Courier-en,均 complete)。

- **翻译花费**:近零。T1–T4 改动不触源文本与提示词(glossary 注入不变);缓存键不变,预期各样本 ordinary 缓存命中率 ≈100%。新增花费仅两类:
  - T4 级 4 钉裁重译:预算 20/刊,预计实际触发 0–3 次/刊(多数裁定已被注入采纳或落级 3 确定性替换);
  - 决策调用(回路 no_op/修复决断)与 B17 同量级。
- **墙钟**:12 样本顺序温跑,ONNX 布局模型主导,估 25–40 分钟(B17 六样本 468s 外推 + 本批单样实测 4–8 分钟/样)。
- **内存**:峰值 2–3GB/样(ONNX),顺序执行避免并发撞目录(B17 教训)。
- **产出目录**:examples/output/B18/T5/<sample>;方向映射 zh→en:ABB-zh, Courier-zh, HuaweiTech-zh, ITU-zh, WIPO-zh, bull-zh, fd-zh;en→zh:AramcoWorld-en-v2, CERNCourier-en, Courier-en, FD-en-v2, Vogue-en。
- **HITL**:reviews/ 下十二份 decisions 全在,授权代批沿既有通道;T4 违裁清单(term_enforce 报告 escalated 项)随交付报告人工复核。
