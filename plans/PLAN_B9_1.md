# PLAN B9.1 — 语言方向按样张声明 + 人名翻译默认策略(1 会话)

前置:batch-e2.3 / tag final-f1;用户已在 corpus/registry.user.json 六条各补 source_lang / target_lang(en×5→zh;Courier-zh 为 zh→en)。B9 排版修正线第一批,解锁 F1 缺陷 #2(Courier-zh 全篇未译)与 #1(人名默认保留拉丁)。

## 任务

### T9.1a 方向字段落地

- manifest 重建:source_lang/target_lang 作为语义字段逐字复制(registry→manifest);corpus_check 校验:两字段齐全、枚举 ∈ {en, zh}、互不相同。
- CLAUDE.md §2 registry 语义字段清单追加两字段(原文照录):「source_lang/target_lang 为样张翻译方向声明,仅用户可写;一切运行驱动按样张读取方向,禁止全局方向配置覆盖。」
- 驱动改造:examples/output/final/scripts/run_final.py(及 artifacts.py 中带翻译的构建模式、tools 中任何硬编码 lang 的驱动,现场盘点)改为逐样张从 manifest 读方向;发现读不到即报错,不回退默认值。

### T9.1b 人名翻译默认策略(声明式)

- `configs/translation_style.json`:`person_names: "transliterate" | "keep_source"`(默认 transliterate),`style_note_by_target`(按目标语声明一句注入文案,zh 档:人名音译为中文、首现可括注原文;en 档:中文人名按拼音)。带 allowed_range/vocabulary 校验。
- 注入:复用既有上下文通道(TitleContextSnapshot 槽/hint block),**全部翻译批次**携带该指令——含 unassigned 页与孤儿修复路径(brief 缺席的页正是 F1 里人名保留重灾区);brief 的 names 建议与 HITL 裁决词条优先级高于默认策略(裁决 > brief > 默认,三级在注入文案中显式排序)。
- 零字面量:注入文案全部来自 configs,代码不含任何语言/人名字符串。

### T9.1c 冒烟(真实 API)

- Courier-zh 以修正方向(zh→en)全栈重跑:首次真实调用约 80 段,记录成本;快览:是否成英文、链检测在 zh 页型误判下的既知掩码如实记录(不修,zh 校准另案);
- Courier-en 重跑(缓存大量命中,人名策略是新 prompt 成分会引起可控 miss):TOC 页人名逐个对照 F1(Sisco Auala / Anna Ruohonen / Jim Al-Khalili / Chimamanda Ngozi Adichie 等应转为音译);已裁决四人名不受默认策略扰动(裁决优先断言);
- 产物入 examples/output/b9_1/,对照表入交付报告。

## 门禁 spec_check_b9_1

正向:manifest 两字段与 registry 逐字相等;corpus_check 负向探针(缺字段/非法值/同值被拒);驱动逐样张方向断言(桩:六样张方向表);注入断言(桩记录:每批次 prompt 含 style 指令、裁决词条在场时优先序正确);默认 keep_source 时行为与 final-f1 逐位一致(策略可关断言)。
负向:上游零改动(注入走既有通道);代码零人名/语言字面量;真值/registry 机器只读;run_all 全绿。

## 明确不做

标题排版(B9.2)、行结构(B9.3)、下沉字消费(B9.4)、碰撞(B9.5);zh 页型校准;F2 定稿(全线收官后)。
