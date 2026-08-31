# B18 T0 前提复核(2026-08-31,HEAD ca78529)

结论:**P1–P5 全部成立**,无不符项,放行 T1。

## P1 ✅ ABB 拉丁词裸断(两处形态均实测)

输出 `examples/output/B17/T3R/ABB-zh/ABB-zh.no_watermark.en.mono.pdf` rawdict:

- **p6**(100pt 源 `创新` → `innovation`):50pt 两 span,`i` bbox [33.9, **119.5**, 48.8, 187.6] 与 `nnovation` bbox [33.9, **184.5**, 289.0, 252.6] —— 与计划给的 y 坐标逐位一致,首字母后断行。
- **p5**(30pt 同族,计划留待实查,现落定):19.5pt,**逐字符断行** —— `i`/`n`/`n`/`o`/`v`… 每字符一行,x 恒 56.9(框宽仅 ~12.6pt),竖排式堆叠。同页另有 7.8pt `N`/`o`/`t`/`e`(`Note`)同形态逐字符堆叠。p5 比 p6 更极端:不是断成两截,是碎成单字符。

## P2 ✅ fd p3#4 `编者的话` 孪生豁免 + residue 双报

- `short_unit.report.json` refused_units:`{page:3, paragraph:"p3#4", reason:"bilingual_companion", chars:4, shape:"label_shaped", debug_id:"Bg4eS"}`。
- `issues.before.json` 与 `issues.after.json` **均**含 detector `untranslated_residue`、debug_id `Bg4eS`、`layout_label:"abandon"`、residue_ratio 1.0、script han —— 检测在报、无人认领、跨迭代未消。
- 源页 companion 实存:p3 有 `FROM THE `(22pt, bbox [346.7, 12.9, 454.3, 38.5])与 `EDITOR`(22pt, [454.3, 12.5, 529.1, 38.5]),墨色 #231f20(近黑,非背景色)。**注意**:y 起点 12.5pt,距页顶极近,T2 的"版内/遮盖"判据须以 IL trim/render 实查落定,此处只钉存在性与墨色。

## P3 ✅ Courier-zh 跨栏标题链释放致延展丢失

- `chain_translation.report.json` outcomes:chain `doUo7`(canonical `chain-bb2591…`),members `p2#3`(page_index 1, title)+ `p3#1`(page_index 2, title),`fallback_reason: "chain_target_overflow"`,joint_call_count 1。
- 输出 p3 实测:30pt `indigenous `(y 115.8–156.6)/ `knowledge`(y 154.8–195.6)孤立两行 —— 释放后成员各排,跨栏连续标题不复存在。

## P4 ✅ 术语链止于检测,无落实

- `hitl_apply.report.json` → `applied.terms.dropped_from_auto`:**35 对** auto_target↔human_target 变体(例:`Roman Duval`→`Romain Duval`、`Rud Demuy`→`Ruud de Mooij`、`Martin Cihák`→`Martin Čihák`),闭集在手。
- `glossary_freeze`:189 条注入,sha256 在报(软注入在位)。
- [minimal_repair.py:58](../../../babeldoc/magazine/minimal_repair.py#L58) `"instruction_compliance": ()`(无可用动作)+ [minimal_repair.py:73](../../../babeldoc/magazine/minimal_repair.py#L73) `"instruction_compliance": NO_OP` —— 检出后无落实,与计划所述一致。

## P5 ✅ 十二样本与缓存在位

- `examples/input/` 十二样本齐:ABB-zh, AramcoWorld-en-v2, CERNCourier-en, Courier-en, Courier-zh, FD-en-v2, HuaweiTech-zh, ITU-zh, Vogue-en, WIPO-zh, bull-zh, fd-zh。
- 翻译缓存 `~/.cache/babeldoc/cache.v1.db` 19.5MB,mtime 2026-08-31(B17 T3 批次后)。B17 报告记 12/12 全经管线。温重跑翻译花费近零成立(B17 实测同款)。

## T0 顺带观察(不改计划,供执行参考)

- P1 p5 形态提示断行粒度是**字符级**,与 T1 "拉丁断行只许空白/连字符" 的排查方向吻合;且窄框(12.6pt)场景走廊扩宽是唯一活路,缩字到 min_scale 也进不了一行。
- P2 companion 距页顶 12.5pt,"版内"判据可能直接命中 —— T2 实查时先看 trim/media box 与渲染可见性,别假设它可见。
