# PLAN B11.1 — 恒等写回、悬挂标点越界、人名档切至 translate（FD 单样张，1 会话）

前置：batch tag `f3`（b63d043）。规格即当次 prompt，本文件是其归档。

**本批的验证范围与协议偏离，先声明**：五日周期的 W-B10-01..04 已随 F3 失效。
本批按用户裁决另立范围：**只在 FD-en-v2 上验证、只产出 FD 的 PDF，不跑
sweep、不跑其余五样张、不做 F2/F3 可比性保全**。F2 对照自本批起不再是约束
（论文不使用）。范围以 waiver 记（§W）。

改动会改变全部翻译请求（人名档切换即换 system prompt），FD 缓存全体失效，
预计真实调用约 80 次（F3 的 FD 为 79 请求）。这是本批唯一的 API 支出。

---

## 前提校验（对 b63d043，逐条核实并把行号写进交付报告；任一不符即停）

1. `il_translator.py:999-1003`：`post_translate_paragraph` 的恒等短路写作
   `if translated_text == translate_input:`，而三个调用点
   （`il_translator.py:1266`、`il_translator_llm_only.py:896`、
   `magazine/short_unit.py:534`、`magazine/chain_translation.py:595`）传入的
   第三参数是 **`TranslateInput` 对象**（类定义 `il_translator.py:483`，无
   `__eq__`）。故该比较恒为 False，短路是**死代码**。
   —— 若实测为真，记入报告；若某调用点传的是字符串，停并报告。
2. `typesetting.py:1407`：换行判据以 `not unit.is_hung_punctuation and (...)`
   开头，即悬挂标点**完全短路宽度检查**，无任何悬挂上限；`”` 在
   `calc_is_hung_punctuation` 的集合内（:345）。
3. `configs/translation_style.json`：`person_names = "transliterate"`；四档
   `transliterate / translate / keep / annotate` 齐备；`translate` 档 zh 文本
   SHA `faf20db8…`，其文本含"Write the Chinese form and nothing else"；
   `person_names_policy_sha256` 为逐档钉住表。
4. FD f3 证据在案（本批基线）：`short_unit` 五处 `F&D`（p3#0、p5#3、p6#1、
   p7#1、p8#1）`source == translated == "F&D"`；页 5/6/8 页眉渲染为
   `F&`+`D` 两行（Noto Serif Bold 7.8pt，x 37.0→48.0 与 37.0→42.9）。
5. FD p3 拉引号越界在案：末行文本止于 x=373.4，`”` 占 373.4→383.6，矢量分栏
   描边在 x=378.5（y 24.5→720.5）；`issues.json` 的
   `pages_by_detector.text_figure_overlap` **不含页 3**。

---

## T1 — 恒等写回不得触发重排（回归根因）

**缺陷**：b10.4 的地板例外让 `F&D` 这类三字符标签首次进入翻译；译文与源逐
字节相同，但恒等短路是死代码（前提 1），于是段落照常经
`parse_translate_output` 重组并按映射字体（Noto Serif Bold）重排，而源盒宽
只容得下源 logo 字体的 `F&D`，遂折行。b10.4 之前它低于地板、从不进翻译、
也就从不重排。

**修法（上游一处，登记入 UPSTREAM_DIFF.md）**：把恒等比较改为对
`translate_input.unicode` 取值，语义即该行原本要表达的意思：

- 比较对象：`translated_text` 与 `translate_input.unicode`。
- 恒等判定用**规范化后逐字节相等**（NFKC + 去首尾空白）；规范化仅用于**判
  定**，不改写任何文本。
- 恒等成立时保持既有分支行为：置 `placeholder_full_match`、`return False`、
  **不触碰** `paragraph.unicode` 与 `pdf_paragraph_composition`（即不重排）。
- 兼容：`translate_input` 若不是 `TranslateInput`（防御），退回原比较，不抛异常。

**副作用面必须实测并记录**：该短路复活后，凡"译文与源相同"的段落一律不再重
排。在 FD 上逐段列出受影响段（本批预期 ≥5 处 `F&D`），报告给出前后对照。

## T2 — 悬挂标点的有界化

**缺陷**：`”` 与 `。` 均属悬挂集，连续两个悬挂单元各自短路宽度检查，累计越
出段盒并压上矢量分栏线（前提 5）。

**先做判定（写入报告，判定前不得改代码）**：从 f3 的 typesetting checkpoint
读出 FD p3 该段的 `box.x2` 精确值，给出四个数——`box.x2`、末行文本止点
373.4、`”` 止点 383.6、描边 x 378.5——并算出该行的实际越界量与该段其余各
行的越界量。**若实测 `box.x2` ≥ 378.5**（即盒本身就跨过了描边），则根因是
盒宽而非悬挂，停并报告，本 T 改期。

**修法（判定为悬挂越界时；上游一处，登记）**：给悬挂引入声明式上限，配置放
`configs/typeset_hang.json`（新），上游只读值不含常数：

- `hang_max_em`（默认 0.5，range 0.0..2.0）：**一行内**所有悬挂单元累计越出
  `box.x2` 的宽度上限，以该段字号为 1 em。
- 判据改为：悬挂单元仍免于常规宽度检查，但须满足
  `(current_x + unit_width) − box.x2 ≤ hang_max_em × font_size × scale`；
  超出即**回退当前悬挂串**——把本行末尾连续悬挂单元连同其**前一个非悬挂单
  元**一并移至下一行（保证新行不以标点起首，避免造出避头点违例）。
- 回退实现为对 `typesetting_units` 索引的有界回溯：回溯长度 ≤ 当前悬挂串长
  度 + 1，禁止无界回溯；回溯失败（例如整行只有悬挂单元）时保持现行为并记录。
- 逐次悬挂与回退写入 sidecar `typeset_hang.report.json`：页、段、行序、越界
  量、判定（`hung` / `pulled_back` / `unchanged`）。

## T3 — 人名档切至 `translate`

`configs/translation_style.json` 的 `person_names` 由 `transliterate` 改为
`translate`。**只改这一个值**：四档文本、逐档 SHA 表、编译逻辑全部字节不变
（b10.4 已建成矩阵，本批只是选档）。

预期行为：人名一律音译、**不再附原文括注**（`translate` 档文本明令
"do not put the source form after it, in brackets of any kind or without
them"）。FD 的验证锚点为 f3 在案的四处括注形：p3 `乔什·利普斯基 (Josh
Lipsky)`、p3 `尼古拉斯·穆尔德 (Nicholas Mulder)`、p8 `金·鲁尔 (Kim Ruhl)`、
p8 `尚塔尔·贾赫昌 (Chantal Jahchan)`、p9 `安德烈亚斯·阿德里亚诺 (Andreas
Adriano)`。

**与 T1 的交互须在报告中说明**：词表条目本身是纯音译（`name_harvest` 在案
`Kim Ruhl → 金·鲁尔`），故本档切换动的是模型的自由附注行为，不动词表。

**与 paren_dedup 的交互**：`translate` 档下不应再产生任何"译名（原名）"形；
若仍出现，属模型不服从，据实记录，不得靠 paren_dedup 掩盖（后者只折叠**同
形**括注，异形括注不在其射程内）。

---

## 验证（FD-en-v2 单样张，全文档跑，产出完整 PDF）

- 运行：`FD-en-v2.pdf`，en→zh，全开关同 f3 的 `run.json`（照抄该文件的
  `switches`，不得自行增减），`person_names` 为本批新值。
- 产出入库 `examples/output/b11_1/FD-en-v2/`：**完整 PDF**（九页）、
  九页栅格 PNG、`run.json`、本批新增与受影响 sidecar
  （`short_unit`、`title_typeset`、`typeset_hang`、`name_harvest`、
  `hitl_apply`、`issues.json`）、`conservation.json`。
- 基线：f3 的 FD 产物（`examples/output/F3/FD-en-v2/`）。**不跑其余样张，
  不跑 sweep。**

## 门禁 `spec_check_b11_1.py`（标注 fast）

1. **T1 正向（像素）**：页 5、6、8 的页眉 `F&D` 在栅格上为**单行**——`F&D`
   三字形的 ink 包围盒高度 ≤ 单行行高容差，且不存在 y 相差 ≥ 8pt 的两段
   `F&`/`D` 文本；提取文本中 `F&D` 三页各恰现一次且不含换行。
2. **T1 机制**：`short_unit` 五处 `F&D` 的记录含 `identity_skipped: true`
   （新字段），且这五段的 `pdf_paragraph_composition` 与译前逐字节相同
   （不重排的直接证明）。
3. **T1 副作用面**：报告列出的全部恒等段，逐段断言其渲染与 f3 基线的差异
   只发生在"由折行变单行"这一类；出现任何文本内容差异即失败。
4. **T2 正向（像素 + 几何）**：页 3 该段末行的最右 ink x 坐标 < 378.5（不触
   描边）；`typeset_hang` sidecar 记该行判定；全文档任一行的悬挂越界量
   ≤ `hang_max_em × font_size`。
5. **T2 负向**：构造一行只含悬挂单元的桩，断言保持现行为且记录
   `unchanged`；构造越界量恰在界内的桩，断言仍悬挂（不误回退）。
6. **T2 无新伤**：FD 九页与 f3 基线相比，`issues.json` 的
   `out_of_page` 与 `text_text_collision` 计数不增。
7. **T3 正向**：提取文本中，前提 T3 点名的五处人名**只有中文形**，
   `(拉丁名)` 形零出现；全文档正则 `[\u4e00-\u9fff·]{2,}\s*[(（][A-Za-z]`
   命中数为 0（机构名、URL、邮箱等非人名括注不在此正则射程，若误伤则收窄
   正则并在报告说明）。
8. **T3 机制**：`run.json` 的 `translation_style.person_names == "translate"`
   且 `system_prompt_sha256` 等于 `translate` 档 zh 文本的钉住值；四档 SHA
   表与 f3 逐字节相同（只选档不改文本的直接证明）。
9. **守恒**：FD 页数 9、段数与 f3 相同；`pN#k` 不移；`api_calls` = 归因行数。
10. **范围负向**：改动 ⊆ 下列负向范围；`prompts/` 不动一字；`reviews/` 与
    `corpus/` 只读。

**不跑** `run_all --set fast`（本批范围内无历史门禁的锚点变更；若实现过程中
触碰了任何既有门禁读取的文件，则该门禁必须单独跑并在报告说明）。

## 负向范围

改动 ⊆ {
`babeldoc/format/pdf/document_il/midend/il_translator.py`（T1 一处比较）、
`babeldoc/format/pdf/document_il/midend/typesetting.py`（T2 悬挂界）、
`babeldoc/magazine/short_unit.py`（仅 `identity_skipped` 记录字段）、
`configs/translation_style.json`（仅 `person_names` 一个值）、
`configs/typeset_hang.json`（新）、
`spec_checks/spec_check_b11_1.py`（新）+ run_all 注册、
`UPSTREAM_DIFF.md`、`WAIVERS.md`、本文件、`examples/output/b11_1/`
}。

上游改动两处（T1、T2），**必须逐函数登记入 `UPSTREAM_DIFF.md`**，并在报告
中给出改动前后的最小 diff。

## §W — 本批 waiver

- W-B11-01：验证范围限 FD-en-v2 单样张，不跑 sweep、不跑其余样张。理由：
  用户裁决，本批三项改动的证据面全部落在 FD；代价是其余五样张的回归要到下
  一次全量跑才暴露，尤其 **T1 与 T2 是上游行为变更，影响面是全语料**。失效
  条件：下一次全量跑绿。
- W-B11-02：F2/F3 可比性不再保全（人名档切换即全量重采）。理由：用户裁决，
  论文不使用 F2 对照。永久。

## 明确不做

其余五样张、sweep 集、词界修复（`MANAGINGEDITOR` 粘连类，属 b11.2）、
修复层受理面扩类、首行缩进开关（b11.3）、gate cache LRU 根修、
checkpoint I/O 优化。

单 commit，tag `b11.1`（**裁决后打**）。交付报告须含：前提逐条行号表、
T1 死代码判定记录、T2 判定四数与越界量表、T1 副作用段全集、T3 五处锚点前后
对照、上游两处最小 diff、API 实际调用数与归因。
