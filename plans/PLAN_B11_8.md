# PLAN B11.8 rev2 — 双向首字处理：keep 语义重定义（zh 下沉 / en 放大），无全量 sweep

本文件**取代**初版。用户三项裁决：(1) 不新增 sink 词表值——`keep` 重定义为
"按目标语言排印惯例重现首字放大"，双向各有几何规则；(2) 既有 flatten 人工裁
定清除，由用户改裁为 keep；(3) **禁止全量 sweep**（耗时不可接受），W-B11-23
完成权改挂性能批。初版留档，此段即作废记录。

前置：batch tag `b11.7`。单臂默认适用。

## 本 PLAN 依裁决落定的值（开工前用户过目，异议即改）

- 词表维持 `{flatten, keep}`；`default_decision_by_target` 两方向均改
  **keep**（依"所有 flatten 裁定改 keep"的裁决意图推定同向默认；不同意在
  premise 阶段否决）。
- `reviews/*.decisions.json` 的 drop_caps 段：全部 flatten 裁定改写为 keep
  （执行方按本裁决改写并重钉哈希，改写清单入报告）。

## 前提校验（任一不符即停）

1. drop_cap 词表现为 `{flatten, keep}`；既有 flatten 裁定逐条列出（样张/页/
   段/现值）。
2. 现行 keep 的行为在案：保留放大风格 run 存活入请求（b11.5 的"当 + 空洞"形
   态即其产物）——本批**废除**该行为，语义变更记入 config 描述与报告（决策
   语义变更，非 IL 类型变更，不触发 §4.18；旧 keep 的唯一下游是排版渲染，无
   其他消费者，核实此点，若另有消费者即停）。
3. flatten 译前链路在案（合并、风格归一、纯文本送译）；keep 复用之。
4. 各样张 drop_cap sidecar 可枚举候选：逐样张逐方向列候选数（en→zh 与
   zh→en 两侧），此清单决定验证范围与正锚。zh→en 侧（Courier-zh）候选数未
   知，为零则 en 放大规则以桩验证并登记零受理（首字放大邻接规则先例同款）。
5. 正文行距可取（首字字号依据）。
6. b11.5 错形数据在案（负向基准：39.36pt 字、27.5pt 空洞、hen 残片）；
   b11.7 旋转车道的"专用试装 + 作用面排除断言"模式在案。
7. W-B11-23 在案；本批不跑全量 sweep（用户裁决），修订该 waiver。

## T1 — keep 语义重定义与裁定改写

`keep` = 译前与 flatten **逐字节等价**（合并、归一、纯文本送译），译后按目标
语言几何规则重现首字放大。裁定改写：全部 flatten → keep，哈希重钉，改写记录
入报告。默认档按落定值改 keep；en 目标默认同 keep（zh 源有下沉即在 en 侧放
大——双向对称即本批命题）。

## T2 — 译前等价断言

同一候选在 keep 与 flatten 两档下翻译请求**逐字节相同**（零翻译路径触碰的直
接证明）；缓存全命中，§Cost 为零（无新增请求）。

## T3 — 双向渲染规则（专用试装，最小化）

配置 `drop_cap_render_by_target`，两套几何、共用一个试装骨架：

- **zh 目标（sink，方形块）**：首字字号 = `sink_lines`（默认 2，range 2..3）
  × 行距；保留区 = 首字宽 + `sink_gutter_em`（默认 0.25，带范围）；首
  `sink_lines` 行右移保留区宽，其后满行；CJK 等宽整数字位装箱。
- **en 目标（initial，高形）**：首字母字号 = `initial_lines`（默认 2，range
  2..3）× 行距；保留区 = 该字母**实际字宽**（拉丁字形高瘦，按 advance 取）+
  gutter；首 `initial_lines` 行绕排，其后满行；断行按 en break_rule（词界）。
- 共同约束：候选集不变（源有 drop cap 才做）；链续段不做；**不接通用
  packer**；column_reflow / typeset_hang 对本车道段显式排除或显式兼容（择一
  断言）；fail-plain 两分支——首字为标点/引号 → 不放大、登记；盒宽不足容纳
  保留区 + 最小行容量 → 回退 flatten 渲染、记 `dropcap_reverted` 与原因；任
  何回退不得产生空洞或残片（负向基准断言）。

## T4 — sweep 债务改挂（W-B11-23 修订）

本批**不跑全量 sweep**（用户裁决）。两项替代：

1. W-B11-23 修订：完成权由"b11.8 收口"改为"性能批使 sweep 耗时可接受后执
   行"；b11.7 第 40 门禁维持 SKIPPED-with-cause，引修订后条款。
2. **把已知的 sweep-only 违规类降成 fast 检查**：b11.7 全量 sweep 抓到的两类
   （源码 CJK 字面量、模块纯度/越界导入）都是**静态检查**，与流水线重跑无
   关——为其建 fast 集廉价变体（AST/grep 级，秒级），此后该两类违规逐批可
   见。sweep 集其余断言的覆盖缺口如实挂账，性能批清偿。

## 验证（单臂，范围由前提 4 的候选清单决定）

- en→zh 侧：候选数 ≥ 1 的样张各跑一次（预期含 FD、Courier-en、CERN），FD
  p8 为主锚（裁定已改 keep，源三行 W → 译两行方形"当"）。
- zh→en 侧：Courier-zh 候选数 ≥ 1 则跑并取主锚；为零则桩验证 + 零受理登记。
- 产物入库 `examples/output/b11_8/`：受影响样张完整 PDF、目标页 PNG、
  drop_cap sidecar（逐候选：决策、方向、字号、保留区、回退原因）。

## 门禁 `spec_check_b11_8.py`（fast）

1. zh 主锚**矩形块四联**（像素+几何）：首字盒高 ≈ sink_lines×行距（容差
   内）；首 `sink_lines` 行右移量相等且 = 保留区宽；其后首行回满行起点；全
   段无超行距空洞。
2. en 侧：有锚则同款四联按 initial 几何；无锚则桩断言 + 零受理登记在册。
3. 负向基准：主锚页不复现 b11.5 形态（无 >1.5 行距段内空洞、无游离拉丁残
   片）。
4. T2：keep/flatten 请求逐字节相同；`api_calls` = 归因行数（预期零新增）。
5. fail-plain：引号起头桩、窄盒桩各触发对应回退且留痕。
6. 裁定改写：drop_caps 段无残留 flatten 值；哈希重钉记录在案。
7. 静态廉价检查落地：CJK 字面量与纯度两查在 fast 集注册且对构造桩各红一次
   （自证有效）。
8. 守恒：段数页数 `pN#k` 不变；detector 计数不升。
9. `run_all --set fast` 全绿。**无 sweep 门禁。**

## 负向范围

改动 ⊆ {`babeldoc/magazine/drop_cap.py`、双向试装模块(新)、`configs/`、
`spec_checks/`（新门禁 + 两个静态 fast 检查）、`reviews/*.decisions.json`
（drop_caps 段改写）、`docs/eval/gap_register.md`、`WAIVERS.md`（W-B11-23 修
订）、本文件、`examples/output/b11_8/`}。上游零改动；`prompts/` 不动一字；翻
译路径零触碰（T2 背书）。

## 明确不做

全量 sweep（裁决禁止）；通用 packer 改造；候选集扩展（源无 drop cap 处不发
明）；sink/initial 行数超 3 的形态；性能批本体（靶单已备：gate cache 失效成
本、b3_3 318s、并行化、sweep 分段续跑——单独 PLAN 待命）。

执行序：落定值过目 → T1→T2→T3 → 候选清单定范围 → 跑 → 门禁 → T4 登记。
单 commit，tag `b11.8`（裁决后打）。交付报告须含：裁定改写清单、候选枚举
表、两侧主锚四联数据、回退逐例、W-B11-23 修订文、methodology 第 3/7 节补句
行号。
