# B16 T0 前提复核记录

复核于 2026-08-31,HEAD `ca9fb3e`(b15)。逐条实测,证据均为本地工件或源码 file:line。

## 结论:全部前提落定,两处偏差不破坏任务设计,继续执行

| # | 判定 | 实测证据 |
|---|---|---|
| P1 | **部分不符** | Courier-en issues.before.json 确为 tfo/ttc 零检出;**ITU-zh 基线本有 3 条**:`text_figure_overlap:p1:p1#1`(封面 xobject, iou 0.56)、`text_figure_overlap:p3:p3#24`(iou 0.20)、`text_text_collision:p2:p2#10+p2#11`(pull_quote, coverage 0.57)。termination 两样本均 `all_candidates_refused` ✓。三处装饰物压字(Courier p2/p8、ITU p5)确未检出——检测盲区本体成立 |
| P2 | ✓,并补齐 | pymupdf get_drawings 实测:Courier p2 fill (275.9,784.5,281.6,790.2) area 32.1;**p8 压字三角落定 (416.2,50.3,421.9,56.0)** area 32.1(p8 另有 (467.0,770.6) 三角与 (438.0,120.4) 路径,均不压字);ITU p5 开引号 (109.8,219.7,128.9,233.9) area 269.6,**另有闭引号 (275.0,353.0,294.0,367.2) 不压字** |
| P3 | ✓ | `ARTWORK_COLLECTIONS = ("pdf_figure", "pdf_xobject")` @ fixed_assets.py:24 |
| P4 | ✓ | `pdf_curve` @ il_version_1.py:1001, 1354 |
| P5 | ✓(结构) | drop_cap_render.py 有 reserve_box/BoxEvidence 挂排机制(:917-929, :1317);具体复用入口 T3 落定 |
| P6 | ✓ | B15 输出 PDF 墨迹实测:Courier p2 译文首词起 x=276.2 压三角 (275.9..281.6);p8 首词起 x=416.3 压三角 (416.2..421.9);ITU p5 "The World" 起 x=91.3 压引号 (109.8..128.9)。三处全部相交 |
| P7 | ✓ | minimal_run.report.json 含 `repair` 决策链 + `repair_evidence{before_pdf,pages,pairs}` 键;minimal_repair.py REFIT_OWNED 准入在位 |
| P8 | ✓,与推定一致 | B12–B15 运行史 union = {Courier-en, bull-zh, FD-en-v2, CERNCourier-en, HuaweiTech-zh, ITU-zh, Vogue-en}。未经当前管线:en 侧仅 **AramcoWorld-en-v2**;zh 侧 **Courier-zh / ABB-zh / WIPO-zh / fd-zh**(b11.12/b11.14 跑过 AramcoWorld/Courier-zh/WIPO-zh 但为 B12 前旧管线;fix0829 为旧 commit 全样本,只作翻译缓存) |
| P9 | ✓,机制二分 | 上游测量 paragraph_finder.py:160-170(>1pt 即 True);写入点唯一 indent_policy.py:531;排版消费 typesetting.py:2050-2051(`space_width * 4` 粗值)。B15 Courier 实录 6 处 True→False 剥除(页 1/2/3/5/5/8),碰撞页 p2#4、p8#14 均为 figure_caption。**新发现:ITU p5#1(pull_quote 页 plain text)标志未被剥除**(before=True→after=True,skipped=mode_decides_nothing),压字源自 4 空格粗值 ≪ 实测让开宽 ~37.6pt(box.x=91.3 → 引号右缘 128.9) |

## 对任务设计的影响

1. **T1 两分支各有实样**:剥除禁令分支治 Courier p2/p8(figure_caption 被政策清除);实测宽度分支治 ITU p5(标志在但 4 空格不够宽)。
2. **T2 基线断言修正**:ITU-zh 的"与 B15 基线一致"= 保留 {tfo p1#1, tfo p3#24, ttc p2#10+11},p5 检出为**新增**恰一条;Courier-en 从零新增恰两条(p2/p8)。
3. p8 断言坐标用 (416.2,50.3,421.9,56.0);ITU p5 的闭引号 (275.0,353.0) 不得产生检出(反向断言素材)。
