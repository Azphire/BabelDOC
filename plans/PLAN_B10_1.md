# PLAN B10.1 — 几何与显示速修（微批次，1 会话）

前置：batch tag `f2`（6cf99b0）。规格即当次 prompt，本文件是其归档。
本批为五日修复周期（b10.1–b10.5 + f3）第一批；周期级协议减免见 §W（先写入
WAIVERS.md，注明适用范围 b10.1..f3，周期结束失效）。

## 前提校验（file:line，任一不符即停，报告差异，不得自行改道）

1. `babeldoc/magazine/drop_cap.py:723`：`flatten` 以 `box=character_union(merged)`
   重建合并后组合的盒。
2. `babeldoc/magazine/drop_cap.py:647`：`merged_style` 取段级 style（此行为保留，
   本批只动几何不动风格）。
3. `configs/title_typeset.json`：`title_min_scale = 0.55`，`on_floor = "escalate"`，
   `on_floor_vocabulary = ["wrap", "escalate"]`；`wrap` 在词表中但落点未必实现。
4. `babeldoc/magazine/title_typeset.py:617` 起 `process_page` / `_process_title`：
   floor 分支在无 dropped 时 `_restore` 快照；`_fit_single_line` 的实现在本文件内，
   执行时先通读并回答 §T3 的判定问题。
5. F2 运行产物在工作区：`examples/output/F2/AramcoWorld-en-v2/work/` 下有
   title-typeset sidecar，含 `p5#17` 的记录。若 F2 工作区已清理即停。
6. `X（X）` 案例在 F2 成品中可见：AramcoWorld p4（Khakimov）、pp.8–9（Paul
   Binski、David S. Powers）、FD p3（Josh Lipsky）、Courier-zh p5/p7（David
   Jefferson、Marcelo Silva de Sousa，半角括号）。

## T1 — flatten 后起排边收到正文几何

现象：Courier-en pp.4/5/7、FD p8，flatten 段首行明显高于同页邻栏首段。
成因：`character_union(merged)` 把放大首字的整个字形盒并入组合盒，起排边被首
字盒抬走；正文字号重排后空出的高度成为偏移。

改法：`flatten` 合并后，组合盒与 `paragraph.box` 的**起排边**（竖排方向的开头
一侧）取 **tail 组合字符并集**的对应边；水平方向仍并入 head 的范围。首字字符
本身保留（译后按正文字号重排），只有盒几何不再由它决定。不引入坐标系假设：
以 tail 并集为准写，勿硬编码 y 方向。

sidecar 增记 `box_before` / `box_after` 两组四元组。

## T2 — 标题单行策略按目标语言覆盖

现象：Courier-zh（zh→en）标题被缩到 0.55–0.8 落地，肉眼过小；单行约束是为
en→zh 定的，方向反转后不成立。

改法（声明式，零语言分支进代码）：
- `configs/title_typeset.json` 增 `on_floor_by_target` 与 `title_min_scale_by_target`
  两个映射（键为语言前缀，匹配规则与 chain_translation profiles 相同：最长前缀，
  无匹配回落平键），各带 `_allowed_range` / 词表校验。本批声明
  `on_floor_by_target = {"en": "wrap"}`、`title_min_scale_by_target = {"en": 0.8}`。
- 补全 `wrap` 落点：floor 且 on_floor=wrap 时，恢复快照（即保留 stage 自身的折
  行渲染），disposition 记 `wrap`，不入 escalation 表；有 dropped 的仍先消费去重
  再折行。
- loader 校验：by_target 的每个值都过与平键相同的词表/范围检查。

## T3 — p5#17 双层标题：先判定，后修复

现象：AramcoWorld p5#17 两层同文 run，duplicates 记录了 2 条（similarity 1.0）
而打印仍是双层叠印裁切；`suppressed_paragraphs=0`（该计数只数段层，属口径而
非缺陷）。

判定（写进交付报告）：读 F2 sidecar 中 p5#17 的完整记录（disposition、
duplicates 逐条 layer/run 字段、restored、scale、lines_after），并通读
`_fit_single_line`，回答一个问题：**单行分支在渲染前是否把 `kept` 写回段落
（`_set_runs`）**。已知候选：
- (a) `_fit_single_line` 仅以 `kept` 测量、渲染仍用原组合 → 去重只在 floor 分支
  被消费，单行分支检出而不落地。修法：进入拟合前先 `_set_runs(paragraph, kept)`
  （快照/回滚语义保持：失败仍 `_restore` 整段）。
- (b) disposition 为 floor 且 `_render` 失败走了 `_restore` → 与记录中
  `restored`/`duplicates` 字段核对（该路径按码应清空 duplicates，与报告矛盾，
  预期排除）。
- (c) 其他 → 停，报告实况，不得凭猜施工。

修复以判定结果为准，改动限于 `title_typeset.py` 单文件。

## T4 — 同形括注确定性折叠

现象：`X（X）`/`X (X)`（全半角、可混用）在四份样张复发；措辞修复（b9.1 两轮）
已证不收敛，改为机械后处理。

改法：新模块 `babeldoc/magazine/paren_dedup.py` + `configs/paren_dedup.json` +
开关 `magazine_paren_dedup`（默认开）。在翻译写回之后、typesetting 之前，对已
译段落执行：括注内容与紧邻其前的文本段**规范化后逐字相同**（规范化 = NFKC +
去首尾空白；不做大小写折叠以免误伤缩写）即删除括注及括号。旋钮：
`max_span_chars`（括注内容长度上限，默认 40，带范围）——超长不动，防误伤真
实同位语。`unicode` 与组合文本同步改写，字符对象按被删片段整段移除。sidecar
逐段留痕（before/after 摘录、删除计数）。

注意：只折叠**同形**括注。`哈基莫夫（Khakimov）` 这类"译名（原名）"是角色文
本明许的首现格式，不许动——断言里有负向样例。

## T5 — 字体重排失败入 sidecar

现象：`KeyError: 'NotoSerif-Bold.ttf'` 被捕获后只写 run.log（F2 §c）。
改法：捕获处（搜索日志串 `laying out .* again failed`）在该标题的 sidecar 记录
追加 `relayout_failed: true` 与异常串。一行级改动，不改回退行为本身。

## 验证（目标页局部跑，留档 PDF）

翻译请求全走缓存（本批全部改动在翻译之后），**零新增 API 支出**；`--pages`
只跑下列页：

| 样张 | 页 | 看什么 |
| --- | --- | --- |
| Courier-en | 4,5,7 | T1 三个 flatten 案例 |
| FD-en-v2 | 3,5,8 | T1（p8）、T4（p3）、T5（p5 xuSgG） |
| AramcoWorld-en-v2 | 4,5,8,9 | T3（p5）、T4（p4/8/9） |
| Courier-zh | 1,2,5,7 | T2（标题谱）、T4（p5/p7 半角括注） |

产物入库 `examples/output/b10_1/<sample>/`：局部 PDF、目标页 PNG（raster）、
相关 sidecar。不生成全量产物。

## 门禁 `spec_checks/spec_check_b10_1.py`（单脚本，注册进 run_all）

正向锚点：
1. T1×4：flatten 段首行 ink 顶边与同页邻栏首段 ink 顶边之差 ≤ 该段字号（修复
   类证据须含像素检查：从目标页 PNG 量 ink，不从 IL 盒推断）。
2. T2：Courier-zh 目标页全部标题 `scale ≥ 0.8` 或 `disposition ∈ {wrap, unchanged}`
   且 `lines_after ≥ 1`；escalation 表中不再出现 p7#15。
3. T3：p5#17 提取文本恰含一次 `希贾兹铁路`；目标页 PNG 上该标题区 ink 无双层
   （以判定后确定的可测口径写死，如字符数减半 + 与 F2 同区 ink 像素占比下降）。
4. T4：四样张目标页提取文本 `X（X）` 同形括注计零（全半角两种括号均查）；
   负向样例：构造 `甲（Jiǎ）` 型译名括注经 pass 后原样保留。
5. T5：对 FD p5 复现路径断言 sidecar 出现 `relayout_failed`（若本次局部跑未触
   发 KeyError，以单测桩驱动断言字段写入，不以真实触发为门禁条件）。

负向：改动 ⊆ {`babeldoc/magazine/drop_cap.py`, `babeldoc/magazine/title_typeset.py`,
`babeldoc/magazine/paren_dedup.py`(新), `configs/`, `spec_checks/`, 本文件,
`examples/output/b10_1/`} 加开关注册点；上游目录零改动；prompts/ 不动一字
（断言摘要不变）；真值与裁决只读；`reviews/` 字节不变。

守恒：目标页段数、页数与 F2 一致；除 T1/T3/T4 点名段落外无段文本变化（对
目标页与 F2 checkpoint 逐段 diff）。

## §W — 周期减免（写入 WAIVERS.md）

W-B10-01：b10.1..f3 期间，逐批验证只跑受影响样张目标页；全量六样张回归集中
于 F3。W-B10-02：每批单 spec_check 脚本，断言限四类（锚点正向/范围负向/守恒
/端到端各≥1）；重放矩阵免。W-B10-03：E 系列评测产物本周期只读。

## 明确不做

碰撞判据与动作（b10.2）；碎片缝合、目录模式、切段风格（b10.3）；人名词表化、
HITL 新可裁项（b10.4）；栏级 reflow（b10.5）；gap register 编辑；zh 分类器词
表；上游 typesetting 合同。

单 commit，tag `b10.1`。交付报告含 T3 判定记录与四类断言输出。
