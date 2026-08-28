# Agent 执行计划 00：冻结双向多样张与人工真值

目标分支：`migration/minimal-v0.6.4`

执行角色：项目中持续复用的唯一执行 agent

## 1. 任务

准备后续 demo 唯一使用的双向样张矩阵和人工 expectations。Courier 只作为已知问题样张，不能承担泛化证明。

本阶段不修改翻译、检测或排版算法。

## 2. 前置输入

主控必须提供可读取的真实 PDF：

- Courier 英文源；
- 两份不同刊物的非 Courier 英文源；
- 两份不同刊物的中文源。

还需提供或人工补齐相关 `reviews/`、page labels 和 chain labels。缺少两份非 Courier 英文源或连续链人工判断时，返回 blocker 后停止。

## 3. 允许改动

- `minimal.zh-en.toml`
- `tests/fixtures/demo/sample_matrix.json`
- `tests/fixtures/demo/expectations/*.json`
- `tests/minimal/test_demo_sample_matrix.py`
- 必须随分支使用的 `reviews/*.decisions.json`
- 必须随分支使用的 `corpus/*.json`
- 若旧计划的失败执行已经生成，删除 `tools/tree_state_v1.py`、`tests/minimal/test_tree_state_v1.py`、`tests/fixtures/demo/schema_vectors.json`、`tests/minimal/test_demo_schema_vectors.py`、`tests/fixtures/demo/legacy_negative.json`、`tests/fixtures/demo/paid_gate_matrix.json` 和 `tests/fixtures/demo/rotation_queue.json`；同时删除只服务这些文件的未提交引用。

删除旧计划中的 `tools/tree_state_v1.py`、`tree-content-v1`、schema vectors、legacy negative spec、复杂 rotation/gate ledger。不得新增替代实现。

## 4. 样张矩阵

`sample_matrix.json` 至少有五个不同 source SHA-256：

| role | direction | requirement |
| --- | --- | --- |
| diagnosis | en→zh | Courier |
| transfer | en→zh | 非 Courier 英文刊物 |
| holdout | en→zh | 另一份非 Courier 英文刊物 |
| transfer | zh→en | 中文刊物 |
| holdout | zh→en | 另一份中文刊物 |

每项只保存：

```text
sample_id / publication_id / role
source_path / source_sha256
source_lang / target_lang / config_path
expectations_path
stage_pages
```

同一 PDF 或同一刊物的重复导出不能同时算 transfer 和 holdout。

## 5. 必须冻结的真值

每个方向分别包含：

- 至少一条同页跨栏 `body` chain；
- 至少一条相邻跨页 `body` chain；
- 至少一组相邻但不连续的 negative endpoints；
- 至少一个多栏页；
- TOC 的 `single_visual_line`、`block`、`prose_exempt`；
- 至少一个标题；
- 至少一个人工 `keep` drop-cap。

每份 expectations 使用简单、可人工检查的结构：

```text
sample_id / source_sha256 / direction
chains[]:
  id / role / ordered_members[]
  member: physical_page / source_text_sha256 / source_box / diagnostic_ref
  transitions[]: cross_column|cross_page
negative_chain_pairs[]
toc_records[]: anchor / kind / source_box
layout_regions[]: role / physical_page / source_box
titles[]: anchor / source_box / target_policy
dropcaps[]: anchor / keep|flatten
coverage_exemptions[]: anchor / reason
stage_pages
```

坐标保存普通 PDF point 数值和小容差即可；不开发 canonical quantization、half-even、跨解析器兼容或 schema migration。

## 6. 人工冻结方法

1. 在 source PDF 原分辨率页面查看候选段落。
2. 确认是否属于同一段落，并确定阅读顺序。
3. 从现有 IL/debug 信息取得文本 hash、物理页和 source box。
4. 再看一次完整上下文，防止把不同文章、caption 或署名连成 chain。
5. 写入 positive truth 和相邻 negative pair。

不得从当前 detector 输出直接生成 truth。

## 7. 双向配置

以 `minimal.en-zh.toml` 为模板新增 `minimal.zh-en.toml`，只修改方向：

```toml
[babeldoc]
lang-in = "zh"
lang-out = "en"
openai = true
openai-model = "gpt-4o-mini"
no-dual = true
qps = 1
pool-max-workers = 1
term-pool-max-workers = 1
watermark-output-mode = "no_watermark"
```

不加入 API key、样张路径、兼容开关或发布配置。

## 8. 唯一离线测试

`tests/minimal/test_demo_sample_matrix.py` 只检查：

- 五份样张角色、方向和文件可读取；
- source hash 不重复且匹配；
- 两个方向的跨栏/跨页 body truth、negative、TOC/layout/title/drop-cap 覆盖齐全；
- truth member 页码、box 和文本 hash 可在 source/IL 中唯一定位；
- holdout 与 transfer 不同刊物；
- `minimal.zh-en.toml` 能被现有配置加载器读取。

运行：

```text
uv run --no-sync pytest -q tests/minimal/test_demo_sample_matrix.py
```

不测试 symlink、文件 mode、Windows/Linux 差异、特殊路径、崩溃恢复、ledger 或旧格式兼容。

## 9. 返回主控

返回：实际样张路径和 hash、选择角色、truth chain 表、feature 覆盖表、生成文件、测试结果和缺失输入。主控人工查看全部 truth crop 后提交这些文件，再进入 Stage 01。
