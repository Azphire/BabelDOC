# PLAN B9.4 — 下沉字裁决消费:flatten 落地与候选缺口(1–2 会话)

前置:batch-b9.3。B7 的 dropCapDecision 字段自写入起无消费端(三处注明);用户三条 flatten 裁决(Courier-en p4#3/p5#5/p7#8)待生效;F1 缺陷 #6(FD p8 "W hen")的候选缺口待查。

## T9.4.0 授权维护

docs/eval/gap_register.md 登记两条(按 e0 规则编号、e0 门禁复跑):
- 页级机制经文档级通道外溢(b9.3 实测:共享 auto-glossary 词条组成 7/18/26 变化 + 跨页配对;归因地板下零未解释项);
- 裁决词条跨源行边界失配(14 对中 1 对,行切分与 glossary 匹配的组合空隙)。

## 语义

开关 `magazine_drop_cap_apply`(默认 False)。开启时消费 IL 的 dropCapDecision:

- **flatten**:译前 pass(裁决注入之后、翻译之前)——将放大首字符并入段落文本流(翻译看到完整首词),其样式降为段落正文样式(巨型字形消失,按正文渲染);composition 重建沿 b9.3 的 copy 语义(未具名字段自动携带)。
- **keep**:显式保持现状(与无裁决行为逐字节一致,断言之)。
- **无裁决**:机器默认按 configs(`drop_cap.json` 增 `default_decision_by_target`,zh 档默认 flatten——中文无下沉字惯例,en 档 keep;仅对已标记候选生效,带 vocabulary 校验)。

## 任务

T9.4.1:前提复核(a. 放大首字符在裁决注入时点的 composition 形态——独立 run?其字符与首词其余字符的归属;b. FD p8 W 未成候选的确切原因——rank?字号比?article_map 归属?用 F1 冻结 checkpoint 取证;c. flatten 后首词进入翻译的路径完整性——min_text_length、glossary 匹配面的变化)→ 实现消费 pass + configs → 合成用例门禁(flatten 并流/keep 恒等/无裁决默认分档/候选外零动/守恒)→ 默认关零差异 → run_all 全绿 → tag batch-b9.4.1(若一会话可完则直接 batch-b9.4)。

T9.4.2(验收,可并入会话一若时间允许):三臂协议,Courier-en——三处 flatten 光栅前后(巨型拉丁字母消失、首词入正文流且已译);FD p8 候选缺口结论(可标则标并出 review 底稿供用户裁决,不可标则定界记录);Vogue p3 残片("T"/"Wh e")在候选/行切分共存下的现状观察;非裁决段零外溢(灵魂断言,注意 b9.3 已证的文档级通道——glossary 组成若因 flatten 并词变化,按归因地板如实呈报而非硬求逐字节);冻结夹具;tag batch-b9.4。

## 负向

上游零改动;真值/裁决只读(FD 新候选的裁决属用户,本批只出底稿);代码零页型名;门禁无 API key。

## 明确不做

Typesetting 首行几何美化(flatten 后首行按正文规则,不追首字下沉的视觉复刻);en 目标语的 flatten 默认(保持 keep);B9.5 内容。
