# B19 T0 前提复核

复核日期 2026-08-31,HEAD `77e62f9`(b18)。证据基线:B18 T5 温跑工件
(`examples/output/B18/T5/`)与用户源文件。结论:**P1–P5 全部实质证实**,
P4、P5 各带一处精确化修正,均不改变任务方向,逐条如下。

## P1 幻觉成品 + tracking 标记 —— 证实,通道已现形

- CERN p3 页脚成品(`CERNCourier-en.no_watermark.zh.mono.pdf` 物理 p3,
  block y0=700.6)逐字含幻觉整段:`在现代物流行业中,ERNCOURIER 作为一个领先
  的快递服务提供商…`。附带发现:该页部分汉字用了 CJK 兼容表意字
  (如 U+FA08「行」),直接以常用码位 grep 成品会漏检,扫描器需 NFKC 归一。
- Courier p1 封面成品含幻觉句 `《信使》是由联合国教科文组织《信使》出版的
  杂志,旨在传播文化和教育的价值。`(块级抽取在案)。
- CERN tracking `echo_retry` 标记在案:`cross_page[1].paragraph[1]`
  (`V o l u`)值 `echo_retry_exhausted`,另有 page 区多条(IBIC 2026、
  CERNCOURIER.COM 等);样式跨度输出
  `<style id='1'>欧洲核子研究组织</style><style id='3'>CERNCOURIER</style>`
  在 `page[3].paragraph[0..2]` 在案。
- **超出计划预期的落定**:两条幻觉文本**均不在** translate_tracking 任何
  output 里,只出现在 indent_policy.report(记录成品文本)与 **TranslationCache**。
  缓存直查(`~/.cache/babeldoc/cache.v1.db`,表 `_translationcache`):
  - id 2344:original_text 为 `term_pin.md` 提示词全文,单元源文 `ERNCOURIER`
    → translation 即 CERN 物流幻觉段(裹 ```json fence);
  - id 2273:同提示词,单元源文 `CourierT H E UNESCO…` → 即 Courier 封面幻觉句。
  即产生通道 = **术语梯级 4 钉裁重译**(B18 T4 新通道),且 N-B17-2 形态
  (畸形/幻觉回复入缓存)实锤两例。echo-retry 通道本身此两例未涉,
  但同属 T3 咽喉点辖权。
- 附带发现(记 N-B19 候选):`babeldoc/magazine/cache_setup.py` 的
  `use_project_cache` 声称"每个入口都调用"实为**零调用**,项目缓存路径
  `examples/cache/` 不存在;真实缓存一直在 `~/.cache/babeldoc/cache.v1.db`。
  T3 清缓存操作以真实路径为准。

## P2 上游长短比守卫在位、幻觉通道绕过 —— 证实

- 守卫在 [il_translator_llm_only.py:910](../../../babeldoc/format/pdf/document_il/midend/il_translator_llm_only.py#L910):
  token 比区间 `0.3 < out/in < 3`,越界 `set_placeholder_full_match()` 回退;
  同函数还有同文回退(:896)与编辑距离回退(:920)。
- 别处正常触发:B18 T5 tracking 中多条
  `Translation result is too long or too short. Input: N, Output: M`
  (CERN、bull、AramcoWorld 均有)。
- 绕过通道已由 P1 缓存证据落定为术语梯级 4(其回复不经 il_translator
  验收路径);逐案 file:line 溯源按计划留给 T3。

## P3 Courier-zh p4 极小字 —— 证实

输出 span 实测(`Courier-zh.no_watermark.en.mono.pdf` 物理 p4):
- **3.5pt** × 2 spans,首条 `There are countless cases that validate the value of traditi…`;
- **4.38pt** × 10 spans,首条 `defending their rights to protect such cultural heritage, wh…`。
另有 5.0pt(`Wide Angle`)与 5.95pt(刊眉)各 1 span,非正文段,不在 T4 断言集。

## P4 bull 首字装置盲区 —— 证实,p8 表现形态修正

- 源实测:p3 `核` 30pt [35.3, 124.8, 65.3, 154.8];p8 `塞` 30pt
  [170.1, 366.0, 200.1, 396.0]。均独立成段(与标题中同字区分)。
- 装置零捕获:bull `drop_cap.report` candidates=[]、`drop_cap_intent.report`
  intents=[]、`drop_cap_render` 无条目、`drop_cap_apply` decisions=[]。
- p3:输出中 `核` 30pt **原坐标原样遗留**(直通,tracking 无该单元);
  正文段进翻译时源文以 `技 术 在 能 源 …` 开头(缺 `核`),译出
  `Technology has improved…`,Nuclear 语义丢失(成品该段首证实)。
- **p8 修正**:`塞` 未原样遗留,而是**作为独立单元进了翻译**,tracking
  `page[5].paragraph[1]` IN `塞` OUT `Senegal`,渲染在原坐标 [171, 365],
  与正文段(IN `内加尔加强了…` OUT `Senegal has strengthened…`)起排区重叠
  ——用户所见 Senegal 重叠即此。两种表现(直通遗留 / 独立误译)同根:
  首字被拆为独立单元、逃过首字装置。T2b 的"归段"修法对两种表现同一处置。
- credit 重复:输出 p3 两条 `(Image/IAEA)` 11pt span,
  [21.62, 782.15, 91.23, 797.14] 与 [21.62, 795.62, 91.23, 810.6],
  纵向互叠 **1.52pt**(计划说"同页两条"系 p3,非 p8;p8 无重复)。

## P5 indent_policy 单一政策集 —— 实质证实,机制细节修正

- **修正**:mode 选择**已经**按目标语言键控——config 现有
  `indent_mode_by_target.entries = {zh: "all"}` + `fallback_mode: "source"`,
  最长前缀匹配在 [indent_policy.py:223](../../../babeldoc/magazine/indent_policy.py#L223)。
  故 en 目标(zh→en 六样本)现走 fallback `source`:政策不裁决
  (`mode_is_authoritative` False),每段照抄中文源几何的缩进旗——
  这正是 P5 所指"zh/源语义落在 en 目标上",实质成立。
- 单一的部分:数值政策键(`indent_em`、`article_opening_rank`、
  `excerpt_chars`、`functional_clearance_pt`)为全局单份,无按语言分离。
- 功能避让(B16 `capture_clearance`)与政策解耦在位:clearance 命中的段
  无条件恢复旗并走实测宽度([indent_policy.py:888](../../../babeldoc/magazine/indent_policy.py#L888)),
  与 mode 无关——T1 分离不扰。
- 对 T1 的影响:方向不变,实现落点更小——`indent_policy_by_target` 落为
  把既有 by-target 机制从"只键 mode"扩为"键整个政策集",zh 侧原值平移,
  en 侧声明 `style_indent: none` 语义(既有词表 `none` 模式);
  en 由"fallback 不裁决"变为"声明式裁决 none",这是行为改变,正是任务目的。

## 判定

无停机项。P4/P5 的修正均已写入上文并将反映在 T2/T1 的实现与门禁措辞中。
