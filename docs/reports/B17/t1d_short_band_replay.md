# B17 T1d:短残留带离线重放——先测量,后定标,测完不加

计划的 T1d 要给 residue 检测器加"短带"(错文种、字符数 ∈ [2, 12))。T0 复核证伪了它的前提:检测地板是**分方向**的(configs/detectors.json `residue_min_script_chars_into_en=1` / `into_zh=12`),into_en 方向短带早已存在——fd-zh 的 6 处短残留(含 1 字的`年`)全部在 issues.after 里,零漏报。计划所称的"12 字地板"真身在修复动作 `translate_orphan_text` 的准入条件(minimal_repair.py `orphan_min_source_chars`),不在检测。

唯一真实的检测缺口在 **into_zh** 方向(en→zh 运行的短拉丁残留)。按计划"默认值先测后定"条款,用 `tools/residue_census.py` 对 7 个最新缓存运行(5 个 en→zh + 2 个 zh→en 对照)做了离线重放,工件在 `examples/output/B17/T1d/census/`。

## 重放判据

census 人口 B(覆盖账单 untranslated)减去人口 A(检测器已见),取非旋转、residue_script=latin、script_chars ∈ [floor, 12) 者——即短带将**新增**的检出。

## 假阳性负担表(budget = 每样本 10)

| 样本(en→zh) | floor=2 | floor=4 | 预算 |
|---|---|---|---|
| AramcoWorld-en-v2 | 2 | 1 | OK |
| CERNCourier-en | **14** | **11** | **超** |
| Courier-en | 6 | 1 | OK |
| FD-en-v2 | **16** | 9 | floor=2 超 |
| Vogue-en | 4 | 0 | OK |
| 合计 | 42 | 22 | |

## 新增检出的构成(逐条目检)

- **制版残片 / 印刷 slug**:`Pub_CERN-26-J`、`CJulAug26_HI`、`STORY_v4.indd 24`、`dd 3`、`MONTH 202`、`DECEMBER 2`——模板遗留物,保留是正确行为;
- **品牌与页脚(furniture)**:`F&D` ×6、`JUNE 2026` ×7——running foot / 刊名,brand/folio 类,保留是设计;
- **断词碎片**:`Wh`、`th`、`us`(Vogue)——fragment 领域,不是 residue 的病;
- **真实漏译:0 条**。

## 结论

短带在 into_zh 方向的信噪比为零:42 条新检出中没有一条是真实漏译,两个样本超出预算。into_zh 的 12 字地板不是缺陷,是对杂志页 furniture 生态的正确校准。**不加短带,不动闭表,不动 config**——这是"先测量后定标"允许且要求的结论。T1d 在任务边界停下,交付本测量与 census 工件。

附:zh→en 方向的 B\A=64 条 below_threshold 全部是图表数字/纯拉丁 fallback_line(零汉字,无所谓"残留");T1a 的覆盖账单以 `no_source_script` 类显式命名了它们。

顺手修复:`tools/residue_census.py:550` 对 `source_box: null` 的覆盖行崩溃(census 首次遇到 box 为空的账单行),补了空值守卫。
