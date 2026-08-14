# PLAN B8.4 — 修复落地:读序修正、treated 语义、决策约束注入(1–2 会话)

前置:batch-b8.3。目标单一:让 p6#15 的修复真实落地进成品 PDF,同时不弱化任何守卫。

## 任务

### T8.4a 竖排/旋转段读序

共享工具 `paragraph_reading_text(paragraph)`:按书写方向对 style run 排序(vertical 按 y 还原自下而上阅读序;水平段保持现序),检测器全组与 writeback 的 rendered_text 改经此函数。门禁:p6#15 实测三 run 还原为 `© Boris Séméniako for The UNESCO Courier` 正序(b8.3 冻结 fixture 断言);水平段输出与改前逐字节一致(零外溢)。

### T8.4b treated 语义

动作施加成功的段落记 treated(run 内 sidecar 状态,不进 IL);复检的收敛比较集 = 全部 findings − treated 引用;treated 项终局报告列 residual ratio。守卫对未治集维持严格递减否则回滚终止。门禁:合成场景——治后残留高于检测阈但已 treated → 循环正常终止 `stopped: converged_with_residuals`,不回滚;未治集不减 → 照旧回滚。

### T8.4c 决策约束注入与选择质量

- react_repair_decide.md 注入 `{action_constraints}`(repair_actions.json 的适用条件声明式渲染)与"max_paragraphs 为上限非配额、按证据强度排序、不得点名不满足适用条件的 finding"措辞(prompt 迭代纪律:哈希+前后对照)。
- 选择质量夹具:构造 19-finding 场景(混合合格/不合格/强弱证据),断言决策点名集 = 已知正确集;纳入桩谱。

### T8.4d 杂项

`.partial` 目录纳入体积核算(当前构建以锁文件豁免);孤儿 `.partial` 被 in-sweep trim 可见可清。清理缓存中现存那一个。

### T8.4e 落地冒烟(真实 API)

Courier-en 重跑:p6#15 检出 → 决策(约束注入后应仅点名合格项)→ 送翻 → 正序写回 → treated → `converged_with_residuals` 终止 → **成品 PDF 中 p6 竖排条带渲染出中文刊名**(栅格证据,b8.3 的 e 项对照图);爆炸半径:变化段 == {p6#15, p3#2, p5#10 中实际施治者};刊名终局 5/6(p1#9 维持文档化不可达)。其余五样张回归跑通,决策拒绝浪费(点名即合格)的比率对照 b8.3 呈报。

### T8.4f 存储保留策略:tools/prune_outputs.py(保留 git 跟踪文件 +
manifest 引用基线 + 最近 2 批完整产物,更早批次只留 *.report.md
与 *.log;--dry-run 默认);run_all 收尾自动调用 --apply;基线
checkpoints/ 目录改 zip 存储,load_checkpoint 支持 zip 读,往返
断言在 zip 路径复跑。白名单相应扩 tools/ 与 checkpoint.py。

## 门禁负向

守卫强度零弱化(回滚路径合成用例复跑);检测/动作阈值零改动(0.60/0.90 一个不许调——treated 语义使调阈不必要,这是本批次的设计主张);真值/裁决只读;上游零改动;注释无中文;门禁无 key。

## 明确不做

p1#9(5/6 为 v1 机制诚实上限,评审界面锚定记未来工作);fragment/overlap 实动作;zh 校准;escalation 活证据(继续挂账)。
