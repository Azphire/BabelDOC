# PLAN E1 — 指标实现与冻结产物计算(2 会话,零翻译运行)

前置:batch-e0;metric_contract.md 为合同。本批次实现 D2 表中"需新建/需对齐"的全部确定性指标,并在冻结产物上算出可算的一切;需要新翻译运行的留给 E2。

## T-E1.0 授权维护(会话一先行)

1. GAP-07 分级入库:baseline 的 manifest/report/logs/integrity/cache 备份 db、vlm_ablation 报告与 JSON、三份 sweep 日志、docs/dissertation/background_chapter.tex(用户已置入);六份基线 PDF 不入库。spec_check_e0 改双档断言(tracked 硬断 / workspace 断路径+sha 并列显式清单)。
2. A-15 重锚:台账该条出处改为 examples/input/Courier-zh.pdf + corpus/manifest.json 的 sha。
3. git checkout 还原 examples/ci/test.pdf;examples/output/b8/corpus_detection.json 停止跟踪。
4. E-06 三处落地的样张/段落/光栅证据摘录进台账补一行(承诺 3 证据主角定位)。

## 任务

### T-E1.1 指标工具(babeldoc/magazine/metrics/,全确定性,configs 带 allowed_range)

- `mid_break_rate.py`:mid-unit page-break rate 形式化——对每个链真值正样本位置与全部页/栏边界,判定译文侧末行收束形态(句末标点集 ∪ 成员内延续);输出逐边界判定 + 文档级比率;LaTeX 定义随工具 docstring 给出(E4 收编进论文)。
- `conservation.py`:block conservation invariant 指标化(translated = rendered + explicitly escalated,数据源链/修复 sidecar)。
- `ltcr.py`:term_consistency 按 eq:ltcr 正名——成对一致计数 / C(k,2),词条集 = 文档内重复 ≥ k 次的源词条(k 进 configs);旧指标保留别名一并输出,论文只引 LTCR。
- `layout_geometry.py`:Overlap 与 Alignment 按 Kikuchi 归一化实现(eq:overlap/eq:alignment,含 g(x)=−log(1−x));image-area delta、page-count delta、image placement IoU(源版 IL box 集 vs 译版)。
- 统一入口 `tools/eval_report.py`:对 (样张, 配置产物) 计算全指标,输出 JSON + 表格。

### T-E1.2 冻结产物计算(会话二)

- v2 LOPO:page_classifier + 现词表 + page_labels 按刊物留一重跑(确定性零 API),逐折矩阵**落盘**(B-02 教训:矩阵文件本身入库);
- C-04 前三档 policy 列补算(缓存回复上);
- 全部冻结 PDF/checkpoint 上跑 eval_report:上游基线六份(PDF 需从 IL 重建 box?不可——上游无 IL;几何指标对上游 PDF 走 PyMuPDF 提取的 box 近似,方法差异在指标合同注明)、fork 各配置现存产物;
- 结果汇入 docs/eval/results_e1/(逐样张逐配置 JSON + 汇总表)。

## 门禁 spec_check_e1

指标单元:每指标 ≥3 合成用例(含边界:空页、单元素、恒等对);LTCR 与旧指标在同输入上的关系断言;Alignment 的 g 函数域检查;v2 LOPO 矩阵落盘且逐折可复算(二次运行逐位相等);上游 PDF 几何提取路径与 IL 路径在 fork 产物上的一致性抽验(方法差异定量入合同);零翻译调用;白名单 = metrics/ + tools/ + configs/ + docs/eval/ + spec_checks/ + T-E1.0 清单。

## 明确不做

R1 三跑、R2 判官、terra 补算(均 E2);任何机制/词表改动;论文正文写作。
