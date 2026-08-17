# PLAN B9.2R — 恢复批次:证据降级、prune 保护、门禁只读化、sweep 锁

本批次清偿 e0/e1/e2 的 known-red 与其关联欠账。零翻译调用、零 API、零上游改动。
交接来源:`plans/PLAN_B9_2.md` §"会话一事故"与 §"交接给恢复批次"。

## 0. 前提复核(开工现场核实,与 PLAN_B9_2 前提一致)

- e0 `check_02_no_dead_link` 红:1 条死链
  `examples/output/b8_4/smoke/raster/b8_4.p6_15.page6.png`。
- e1 `check_06` 红:`KeyError('mid_break_rate')`——`tools/eval_report.py` 在 checkpoint
  缺失时优雅降级并把缺项写进 `absent`,门禁却直接取键。
- e1 `check_11b` 红,**且现场复现了破坏性写入**:该断言以被跟踪的
  `docs/eval/results_e1/lopo_v2.json` 作 `tools/lopo.py` 的输出路径,输入不在时
  工具照样写出退化报告(`folds=0`、`samples=0`),覆盖冻结件后断言才报"不一致"。
  本会话首次运行 e1 即触发,已 `git checkout` 复原。
- e2 `check_12` 红:`FileNotFoundError`,缺
  `examples/output/b8_4/smoke/AramcoWorld-en-v2/work/AramcoWorld-en-v2/checkpoint.08_chain_builder.xml`。
- 台账逐行扫描(按引用路径与"目录 + 文件名"两种形式)确认受 prune 波及的行:
  **A-26**(四份出处产物全失)、**E-02**(页级栅格哈希不可现场复算)、
  **E-06** / **E-13**(引文存活于被跟踪的 `evidence.json`,页级对照层已失)。
  **C-06** 的两处缺失来自 b7.5.1 语料换血,非本次淘汰,不动。
- `configs/output_retention.json` 的 `keep_recent_batches` 盘上已是 2。
- `examples/output/gate_cache/` 内有一个孤儿 `.partial`(270 MB),其锁的 pid 已不存在,
  但 `staging_stale_after_seconds = 86400` 使它被当作活的构建。
- 工作区带上一会话未提交的 `examples/output/final/` 三份**被跟踪**文件的删除
  (旁边有手工打的 `final.zip`)。按 §5.11 定归属:内容在 git 里,本会话 `git checkout` 复原,
  不进本次 commit 的 diff。

## 1. 2b 降级(用户裁定的路径,不重算)

- 台账新增第五档状态 `artifact pruned, sha recorded`,含义:引文与哈希存活于**被跟踪的**
  台账与批次报告,可照文本引用;承载它的未跟踪产物已淘汰,**产物级复验已失**,且一律不重算。
- A-26 / E-02 / E-06 / E-13 状态改为该档,逐行在状态单元格写明"不重跑"的理由
  (role block 已改变 prompt 空间)与仍可引的部分;引文内容一字未改。
- 五条被淘汰路径进台账顶部"已失效产物登记"(e0 `check_03` 断言其确实不在树内)。
- 顶部关于页级栅格"在树内"的散文改为与事实一致。
- 缺口登记新增 `GAP-19`:成因、已排除的恢复路径(gate_cache 变体不可互换,实测)、
  不重跑的理由、根因修复三条、以及"不补的措辞"合同。
- e2 `check_05a` 由"任何行不得为 open"改为"E2 自己关的行必须可引 + 任何 open 行必须在
  缺口登记里有答复"。降级是合法状态,**无人写下理由**才是缺陷。

## 2. 冻结证据只读化(本批灵魂)

- 新增 `spec_checks/frozen.py`:声明冻结前缀(`docs/eval/`),提供
  `snapshot` / `changed`(机械层)与 `absent` / `skip`(协作层)。
- `spec_checks/run_all.py` 逐门禁前后取哈希;写了冻结件的门禁当场转红并被点名。
- e1 `check_11b`:重算写入临时目录再逐字节比对;输入缺失报 SKIPPED 并列出缺失路径;
  另断言跑完后盘上冻结件字节未变。
- e1 `check_06`、e2 `check_12`:输入缺失报 SKIPPED 并指明路径。
- 工具层纵深:`tools/lopo.py` 在 `missing` 非空时**不写**目标文件(默认输出路径就是被跟踪路径);
  `tools/splice_judge.py` 新增 `required_checkpoints()`,让调用者先问再跑。
- 盘点结论:全部 27 个历史门禁中,唯一"会写被跟踪文件"的路径是 e1 `check_11b`
  (e2 `check_03c` / `check_12` 本就写临时目录)。静态断言 `02d` 把这个形状本身钉死。

## 3. prune 保护与归档

- `configs/output_retention.json` 新增 `protected_paths`(并入 e0 登记的分级入库清单与
  全部"路径 + sha256"条目)、`archive_patterns`、`archive_max_file_kb`。
- `tools/prune_outputs.py`:`registered_paths` / `is_registered` 参与 `prunable` 的排除;
  新增 `archivable` 与 `archive_evicted`,把被淘汰批次的小体积文本打进
  `docs/reports/archive/<batch>.zip`(入库),大件仍删除;归档是增量的,无新成员不重写。
- `keep_recent_batches` 落实为 2;`spec_check_b8_4` 的 `check_04c` 随迁
  (fabricated tree 加 sidecar、断言归档选取、断言登记路径不可被选中),
  `check_04e` 改为按"谁调用 run_gate"定位驱动函数而非按函数名。
- CLAUDE.md 第 4.13 条写下该约定,门禁按 sha256 钉住并逐锚点校验。

## 4. 并发锁

- `spec_checks/artifacts.py` 新增 `SWEEP_LOCK`(`gate_cache/sweep.lock`)与
  `acquire_sweep_lock` / `release_sweep_lock` / `sweep_lock_holder`;
  第二个并发 sweep 在清统计、trim、写完成标记之前就被拒,并点名持有者 pid 与已运行时长。
- 新增 `pid_is_running`(Windows 走 `OpenProcess` + `GetExitCodeProcess`,POSIX 走 `kill(pid, 0)`),
  接入 `_lock_is_live`:pid 已消失的 staging 立刻算孤儿,不再被 24 小时窗口保住。
- 现存孤儿 `.partial` 已清理(1 个目录、269 MB)。

## 5. 门禁与交付

- 新增 `spec_checks/spec_check_b9_2r.py`(20 条断言,含 8 条负向),注册进 `run_all.py` 末位;
  e0 `check_07b` 声明该 gate 为"排在 E0 之后"的例外并写明理由。
- 全量 `run_all` 无条件全绿,known-red 清零。
- 单 commit,tag `batch-b9.2r`。

## 实测(本会话现场记录,不改计划)

### 归档首包

11 个 zip、**40 个成员**、合计 124 199 bytes,全部入库:
`b2_2`(6)、`b2_3`(6)、`b2_5`(1)、`b4`(1)、`b5`(4)、`b6`(12)、`b6_2`(1)、
`b7_2`(1)、`b7_3`(2)、`b7_5`(2)、`b8`(4)。内容全是被淘汰批次里**未跟踪**的
`*.log` 与 `*.json` 小文本(各批的 `run_all.*.log`、`smoke.*.log`、`gate.log`、
`spec_check_*.log` 等)——旧策略下它们留在盘上、不进 git,一次 clone 即失。

**首包分两次形成,第二次是机制的真实体检**:开工时手动 `--apply` 收下 23 个成员;
随后一次全量 sweep 在收尾 prune 里删掉 **658 文件 / 11.80 GB**,而在删之前又归档了
**17 个新成员**(`b2_2` 6、`b2_3` 6、`b5` 2、`b6` 1、`b6_2` 1、`b8` 1)。
这 17 个正是旧策略下会静默消失的那一类。**第二次全量 sweep 归档零新增**:同名文件已是成员,
故归档收敛、不产生 git churn。

### 全量 sweep

- 第一遍(指纹变更后冷缓存):**27/28**,唯一红是本批门禁的 `check_03c`——它按"活树"
  断言归档幂等,而 sweep 的各门禁正往被淘汰批次目录里写文件、收尾 prune 在最后才跑,
  故该断言在 sweep 中途必然报"还有待归档"。**这是真发现而非测试瑕疵**:幂等只在树不变时成立,
  断言改到 fabricated tree + 可丢弃目标目录上做。b2 一个门禁耗 3828 s 重建整代缓存。
- 第二遍(修好后,warm cache):**28/28,1820.9 s,196 hit / 0 built(100% 命中)**,
  全程无一条 `FROZEN EVIDENCE WRITTEN` —— 这就是"27 个历史门禁没有一个写被跟踪证据"的实证,
  比静态盘点强。
- prune 之后复跑 e0/e1/e2 仍 13/13、33/33、19/19:本次淘汰没有毁掉任何引文。

### 会话中发现并修掉的两个真缺陷(计划外,同属本批范围)

1. **锁不是原子的**:第一版 `acquire_sweep_lock` 先查 holder 再写文件,两个同一瞬间启动的
   sweep 都读到"无锁"而双双放行——本会话实测撞上了(两个 run_all + 两个 b0 同时在跑,
   旧代缓存被其中一个 trim 掉)。改为 `O_CREAT|O_EXCL` 先抢占,失败者再判 holder;
   实测同时双启一个 REFUSED 一个 proceeded。门禁 `04a` 加了这条竞态的断言。
2. **孤儿 staging 被时间窗保住**:`staging_stale_after_seconds = 86400` 是唯一判据,
   pid 早已消失的 `.partial` 仍算"活构建",270 MB 白占一天。新增 `pid_is_running`
   (Windows `OpenProcess` + `GetExitCodeProcess` 判 zombie,POSIX `kill(pid,0)`)接入
   `_lock_is_live`,现存孤儿当场回收 269 MB。

## 遗留(不属本批)

- 显示标题越出页顶(`typesetting.py:1350` 的 `avg_height` 取众数),交 B9.5。
- TOC 页行结构保持,交 B9.3。
- 归档只覆盖小体积文本;未跟踪的大件(PDF、checkpoint、栅格)仍随淘汰消失,
  这是设计而非缺口——引用纪律由台账文本承担。
- `spec_checks/frozen.py` 的冻结前缀目前只有 `docs/eval/`(本批声明的范围)。
  本次 sweep 的实证是"全程无任何被跟踪文件被门禁改写",据此把前缀扩到
  `examples/output/` 下被跟踪的证据(b8_4 的 `evidence.json` 等)是自然的下一步;
  扩容只增加检测、不改任何门禁行为,但按本项目规矩须再跑一次全量才能入库,故留给下一批。
