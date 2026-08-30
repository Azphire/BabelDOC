# B15 冷跑新样本问题清单(只记录,留待下批裁决)

来源:`examples/output/B15/T4/{Vogue-en,ITU-zh}/work/…/issues.after.json`、
`furniture.report.json`、成品抽验渲染。按红线,以下问题一律未修。

## Vogue-en(en→zh,3 页,residue 2 条)

| 页 | 摘录 | 归因 |
|---|---|---|
| p1 | `FENDI BOUTIQUES  888291 0163FENDI.COM` | 广告品牌行,应保留类 |
| p3 | `FPARSOHDIUOCNE ED DBITY OBRO: OJUML IPAR OSAD…` | **M1** 旋转署名行交织搅碎 |

- **M1 旋转双行署名交织**(Vogue p3 右缘):两行旋转的制作署名
  (`FASHION EDITOR: …` / `PRODUCED BY: …`)在段落形成期被按几何序交织为
  一段乱串,再整段计为 residue。与 CERN slug 交织同源(重合/近邻字符
  排序),但两行**文本不同**,不落入 B15 孪生段判据;且
  `magazine_rotated_lane` 固定为 off,旋转单元无专用通道。
- fragment_cluster ×2(p3 目录条目拆段)、instruction_compliance ×1
  (`VO GU E→VOGUE` 词条采纳记录)。

## ITU-zh(zh→en,8 页,residue 7 条)

| 页 | 摘录 | 归因 |
|---|---|---|
| p2–p8 | `国际电联新闻杂志06/2019` ×7 | **M2** 旋转书脊家具保源 |

- **M2 旋转书脊刊名家具未译**:每页右缘竖排刊名+期号。家具 pass 正确
  分组(6 页组,文本呈倒序 `06/2019 志杂闻新联电际国`)且全员一致保源
  ——"一个声音"达成,但方向为 zh→en 时该家具仍是中文。既有 HITL 词条
  `国际电联新闻杂志→ITU News Magazine` 因倒序文本 `absent_from_source`
  未命中(hitl_apply skipped 记录在案)。修复需旋转单元的读序还原,
  归 rotated_lane 议题。
- instruction_compliance ×3(词条采纳记录:国际电联→ITU、马里奥•马尼维奇
  →Mario Maniewicz ×2)。
- text_figure_overlap ×2(p1 封面题图带、p3 期号块)、
  text_text_collision ×1(p2 引号)。

## 共通观察

- 两份冷跑 HITL 均由既有 decisions 文件自动应用(Vogue 6 词条、
  ITU 9 词条 + 8 页 page_kinds 覆盖),执行侧代批复核:既有裁定维持,
  无新增裁决需求;ITU 一条词条 skipped(见 M2)。
- fix0829 旧缓存部分命中,冷跑实际耗时 Vogue 58s / ITU 98s,远低于
  冷估(3–8 / 5–12 分钟);API 花费相应低于 $0.2 预算上限。
- ITU zh→en 缩进模式为 `source`(fallback):带外页 `after:True` 5 处均为
  `mode_decides_nothing` 保源缩进,非闸门违例(闸门只约束本 pass 的决定)。
