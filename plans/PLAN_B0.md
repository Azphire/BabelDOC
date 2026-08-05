# PLAN B0 — 基建:checkpoint、回归样张、渲染对比(1–2 会话)

前置阅读:CLAUDE.md 全文。本批次不改变任何翻译/排版行为,只添加观测与验证基础设施。

## 目标

1. 建立扩展目录骨架与两份登记表。
2. 在既有 debug JSON 落盘之外,增加 **XML checkpoint**(可往返格式),并提供从任意 checkpoint 重新载入 IL 的工具函数。
3. 建立回归样张登记(样张位于 `examples/input/`,产物统一进 `examples/output/`)。
4. 提供 `tools/render_diff.py`:对两份 PDF 逐页栅格化对比,输出量化报告。
5. LLM 翻译缓存项目本地化:DB 重定向到 `examples/cache/cache.v1.db`,禁用行数淘汰,相同翻译内容直接命中缓存。
6. 门禁 `spec_checks/spec_check_b0.py` 全绿。

## 需复核的代码事实(与 CLAUDE.md §2 一致;不符即停止)

- `high_level._do_translate_single` 在 `translation_config.debug` 为真时,于各 stage 后调用 `xml_converter.write_json(docs, translation_config.get_working_file_path(...))`。
- `XMLConverter`(`document_il/xml_converter.py`)有 `write_xml/read_xml/from_xml/to_xml/to_json/write_json/deepcopy`;**没有** JSON 读取方法。
- `TranslationConfig.only_parse_generate_pdf` 为真时跳过全部翻译相关 stage(`get_translation_stage` 中移除),可无 API key 干跑。
- `pymupdf` 已是核心依赖,可用于栅格化。
- 缓存:`translator/cache.py` 中 `db = SqliteDatabase(None)`(peewee 延迟初始化),`init_db()` 在模块底部导入时执行,路径硬编码为 `const.CACHE_FOLDER / "cache.v1.db"`(`~/.cache/babeldoc/`);`_cleanup()` 按 `MAX_CACHE_ROWS = 50_000` 删除旧行;`BaseTranslator.translate/llm_translate` 均经 `TranslationCache.get/set`,受实例与调用两级 `ignore_cache` 控制。

## 任务

### T0.1 目录骨架与登记表

创建 `babeldoc/magazine/__init__.py`、`prompts/.gitkeep`、`configs/.gitkeep`、`tools/`、`corpus/`、`spec_checks/`、`UPSTREAM_DIFF.md`(空表头:file | symbol | purpose | batch)、`WAIVERS.md`(空表头:id | scope | reason | expiry-condition | batch)。

### T0.2 XML checkpoint

新建 `babeldoc/magazine/checkpoint.py`:

- `dump_checkpoint(docs, translation_config, stage_name: str) -> Path`:调用 `XMLConverter.write_xml` 写 `working_dir/checkpoint.<NN>_<stage_name>.xml`(NN 为 stage 在流水线中的两位序号,保证文件名字典序 = 执行序);同时写同名 `.json`(复用 `write_json`)供人工检查。返回 XML 路径。
- `load_checkpoint(path) -> Document`:`XMLConverter.read_xml` 封装,附带基本完整性检查(total_pages 与实际 page 数一致)。
- 挂接:在 `_do_translate_single` 的每个既有 debug `write_json` 点旁,当新配置开关 `magazine_checkpoint`(默认 False)为真时调用 `dump_checkpoint`。`TranslationConfig` 增加该布尔字段(构造参数,默认 False)。这是本批次唯一的上游改动点(`high_level.py` + `translation_config.py`),逐条登记 `UPSTREAM_DIFF.md`。
- 覆盖的 stage 至少包括:create_il、layout_parser、paragraph_finder、styles_and_formulas、il_translated、typesetting 之后(若既有 debug 点缺 typesetting 后落盘,则补一个 checkpoint 调用,不改 debug JSON 行为)。

### T0.3 回归样张登记

样张 PDF 已由用户置于 `examples/input/`(本仓库快照中可能不含,以本地实际为准;若目录为空则停止并报告)。新建 `corpus/manifest.json`:每条记录 `{file, sha256, pages, notes}`,`file` 为相对 `examples/input/` 的路径。新建 `tools/corpus_check.py`:校验 manifest 与实际文件一致(存在、哈希、页数),并对 `examples/input/` 中未登记的 PDF 给出警告。创建 `examples/output/.gitkeep`;`.gitignore` 加入 `examples/output/*` 与 `examples/cache/*`(产物与缓存不入库,`.gitkeep` 除外)。

### T0.4 渲染对比工具

`tools/render_diff.py`,CLI:`python tools/render_diff.py A.pdf B.pdf --out report_dir/`。

- 逐页以固定 DPI(默认 150,参数化)栅格化两份 PDF(pymupdf)。
- 每页计算:像素差异占比(阈值化后非零像素 / 总像素)、bbox 级差异区域数;页数不等时记为结构性差异。
- 输出 `report.json`(逐页指标 + 汇总)与差异热区叠加 PNG(仅差异页)。
- 退出码:全同为 0,存在差异为 1,结构性差异(页数不等/无法打开)为 2。后续所有批次的"行为未变"断言都建立在这个工具上。

### T0.5 基线固化

用 `only_parse_generate_pdf=True` + `magazine_checkpoint=True` 对 manifest 中每份样张干跑一次,产出 PDF 存入 `examples/output/baseline/<name>.b0.pdf`,checkpoint 目录存入 `examples/output/baseline/<name>.checkpoints/`。manifest 增补 baseline 条目(含哈希)。后续所有批次的实际翻译测试产物一律写入 `examples/output/<batch>/`,不得散落他处。

### T0.6 缓存项目本地化

- 上游改动(登记 UPSTREAM_DIFF.md):`translator/cache.py` 的 `init_db` 增加可选参数 `db_path: Path | None = None`(None 时保持原行为)与 `enable_cleanup: bool = True`;`TranslationCache.set` 中的 `_cleanup()` 调用受该开关控制。**先验证** peewee 对 `SqliteDatabase(None)` 二次 `db.init()` 的行为(需先 `db.close()`);若二次 init 不可靠,改为在首次导入前完成重定向并在交付报告中说明。
- 扩展侧:`babeldoc/magazine/cache_setup.py` 提供 `use_project_cache(root: Path)`——将 DB 重定向到 `examples/cache/cache.v1.db` 并禁用淘汰;在本项目所有入口(tools 脚本、后续批次的 stage)统一调用。
- 语义确认:同一 `(engine, params, 原文)` 第二次调用返回缓存值且不发起网络请求(用计数桩验证,见门禁 10)。

## 门禁 `spec_checks/spec_check_b0.py`

正向断言:

1. `checkpoint.py` 存在且 `dump_checkpoint`/`load_checkpoint` 可导入。
2. 对样张干跑后,working_dir 中 checkpoint XML 文件数 ≥ 5,且文件名序号严格递增。
3. 任取一个 checkpoint:`load_checkpoint` 成功,`docs.total_pages == len(docs.page)`,且 `to_xml(load(x)) == to_xml(load(load→write(x)))`(写读写等幂)。
4. `render_diff.py` 对同一 PDF 自比对退出码为 0;对基线 PDF 与其任意单页删除版本比对退出码为 2。
5. `corpus_check.py` 通过。
10. 缓存:调用 `use_project_cache` 后,用桩翻译引擎(继承 `BaseTranslator`,`do_translate` 内计数)对同一文本调用两次 `translate`——第二次计数不增加且返回值相同;`examples/cache/cache.v1.db` 文件存在;写入 50,001 条测试记录后行数不减少(淘汰已禁用);`~/.cache/babeldoc/cache.v1.db` 的 mtime 在测试期间未变化(未误写全局库)。

负向断言:

6. `magazine_checkpoint=False`(默认)时,working_dir 不出现任何 `checkpoint.*` 文件(默认路径零行为变化)。
7. 干跑产出 PDF 与 T0.5 基线经 `render_diff` 比对退出码为 0(checkpoint 挂接未改变渲染)。
8. `git diff` 中被修改的上游文件集合 ⊆ {`high_level.py`, `translation_config.py`, `translator/cache.py`},且均已登记 `UPSTREAM_DIFF.md`;`init_db()` 无参调用行为与上游一致(默认路径、淘汰开启)。
9. 全部新增/修改代码中注释无中文字符(简单正则扫描 `#`/docstring 行)。

## 明确不做

- 不加 JSON 读取路径(B1 评估是否需要)。
- 不动 schema、不动任何 midend stage、不引入任何 LLM 调用。
- 不做增量/断点续跑入口(只做"载入 checkpoint 得到 Document 对象"的能力,消费方在后续批次)。
