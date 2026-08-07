# PLAN B2.5 — 门禁提速:产物缓存 + 分层执行 + 计时取证(1 会话)

前置:B2.4 已提交(batch-b2.4)。目标:run_all 全量一轮回到 15 分钟量级;为"越跑越慢"取证。本批次不改任何断言的命题,只改断言获取证据的方式与执行编排。

## 背景数据(不符即报告,不阻塞)

run_all 耗时:B2.3 时 2804.8s → B2.4 时 14241.7s,工作量未变,膨胀原因未知。单项:b2 831→4726s,b2_1 578→3672s。

## 任务

### T2.5a 逐断言计时(先行,取证用)

各 spec_check 的断言执行统一经计时包装,run_all 汇总输出每门禁 top-5 慢断言及其耗时。本任务完成后先单独跑一轮 run_all(旧路径,未接缓存),用计时数据回答:5 倍膨胀来自哪些断言?是流水线重跑次数变多,还是单次流水线变慢(环境因素)?结论写入交付报告后再继续 T2.5b。

### T2.5b 共享产物缓存

新增 `spec_checks/artifacts.py`:

- 缓存键 = (样张 sha256, 运行模式, 工作区指纹)。工作区指纹 = SHA-256(git rev-parse HEAD ‖ git diff 二进制 ‖ configs/ 全部文件内容)——代码或配置任何改动自动失效,不存在"吃到旧产物"的通道。
- 运行模式枚举自现有门禁的实际需求(现场盘点,预计为:only_parse 干跑、skip_translation 全 stage 含 checkpoint、分类开启版三种)。
- `get_artifacts(sample, mode)`:命中返回缓存目录,未命中构建后缓存。缓存根 `examples/output/gate_cache/`(.gitignore 覆盖),run_all 启动时打印命中/构建统计,并提供 `--clear-cache`。
- 各门禁的流水线调用改经此接口。**断言命题不变**:门禁仍对产物做同样的检查,只是产物由共享构建提供。
- render_diff 加前置捷径:两 PDF 字节级 sha256 相等直接判同(退出 0),不再栅格化;不等才走既有栅格对比。

### T2.5c 分层执行

断言分两档:`static`(grep/schema/git/JSON 校验类,不依赖流水线产物)与 `pipeline`。`run_all --fast` 只执行 static 档(pipeline 档打印 SKIPPED: fast tier);默认全量。约定(CLAUDE.md §5 追加,原文照录):「迭代开发期用 run_all --fast 快速回归;批次提交打 tag 前必须全量 run_all 全绿(断言 6 的 EXPECTED-RED 状态除外,直至调参批次达标)。」

### T2.5d 标签页号越界修复

`validate_page_labels` 增加:页号必须落在该样张 manifest pages 范围内(1..pages),越界报错而非静默 miss。对现有 page_labels.json 复跑校验确认通过。

## 门禁 `spec_checks/spec_check_b2_5.py`

正向:1) 缓存命中路径与直跑路径对同一样张产出的 checkpoint 集在规范形式下相等(抽一份样张验证);2) 工作区指纹敏感性:人为改 configs 任一文件一字节,缓存键改变(构建后还原);3) render_diff 哈希捷径:同文件退出 0 且未生成栅格产物;4) run_all --fast 在干净工作区 5 分钟内完成且 static 档全绿;5) 全量 run_all 全绿(仅 06c EXPECTED-RED),总耗时与逐门禁计时入交付报告;6) 越界页号被校验拒绝(负向探针)。

负向:7) SPEC_NO_NESTED 与无缓存回退均保留:删除 gate_cache 后任一门禁单文件独立运行仍全绿(自建产物);8) 断言文本/命题零改动核对:各 spec_check 的断言描述串集合与 batch-b2.4 相比,仅允许新增(计时/分层封装不得改写既有断言语义);9) 改动 ⊆ {spec_checks/*, tools/render_diff.py, babeldoc/magazine/corpus.py(T2.5d), CLAUDE.md};上游零改动;注释无中文。

## 明确不做

不删任何断言;不降 DPI 等对比精度参数;不动词表/特征/流水线;不填标签。
