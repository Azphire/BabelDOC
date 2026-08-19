# PLAN B9.5 — 碰撞检测与页框容纳:B9 线收官(2 会话)

前置:batch-b9.4。F1 缺陷 #4 + CERN 报头越顶(b9.2.2 定因:typesetting.py:1350 众数字号锚定,72pt 报头与 7pt 署名同段,锚小号致越顶;所需缩放穿地板)。实测确认:现无任何检测器覆盖文-文碰撞与出页(b9.4 e.3)。

## T9.5.0 授权维护

1. spec_check_b7_5.TRUTH_DIGESTS 增 FD-en-v2.decisions.json 钉(9ad183a 提交态 sha256);
2. 三处过期陈述更新:reviews/README.md:99、gap_register GAP-08(dropCapDecision 已有消费端,batch-b9.4)、UPSTREAM_DIFF.md:106(first_style_run 更名与"composition 不被重写"断言修正,替换行已起草);
3. run_all 输出编码健壮化(重定向下 UTF-8,子进程解码显式声明);
4. 评估协议补一句(docs/eval 合同,e0 复跑):「修复环决策按设计绕缓存,为流水线唯一不可重放环节;跨跑差异按归因地板处置(E2.1 与 b9.4 两次实测)。」

## 语义

两个新检测器(detectors/,configs 带 allowed_range,report 与 repair 分离):

1. **out_of_page**:段落渲染 box 超出页框(cropbox 内缩安全边距参数化);
2. **text_text_collision**:文段两两 box IoU ≥ 阈值,**且源几何无此重叠**(源版面盒对照——源本有的叠层是设计,不是缺陷;b9.2 幽灵层、CERN 拼版底栏均属源设计,必须被此对照豁免)。

两个新修复动作(repair_actions.json,ReAct 词表扩容,像素证据强制):

3. **contain_in_page**(适用 out_of_page × title 类):框内平移优先,不足则缩放,穿 `contain_min_scale` 地板则 escalate——CERN 报头病例的收账路径(众数锚定不动上游,越顶结果在 magazine 层矫正);
4. **resolve_collision**(适用 text_text_collision):v1 仅 report+escalate,不自动动(碰撞成因异质——CERN p3 叠符、Courier-zh p8 三层、Vogue 条目压 folio,盲目移动的风险大于收益;自动化等病例分类清楚再议)。

## 任务

T9.5.1(会话一):T0 四项 → 前提复核(a. 页框/cropbox 在 IL 的取法;b. 源几何盒的可得性——对照用源版面盒来自哪个 checkpoint 层;c. contain_in_page 的平移/缩放通道与 b8.4 写回工具的复用面)→ 两检测器 + contain 动作实现 → 合成用例门禁(出页/贴边安全距/源设计叠层豁免/诱发碰撞检出/contain 平移-缩放-escalate 三态/词表校验)→ 默认关零差异 → run_all 全绿 → tag batch-b9.5.1。

T9.5.2(会话二):三臂验收——CERN p1 报头**先重测再行动**(b9.2 标题路径已变,F1 测量作废):现状光栅 + contain 前后光栅 + 页框几何断言;全语料碰撞普查表(诱发 vs 源设计分列——Courier-zh p8 三层、CERN p3 叠符、Vogue folio 压条逐一归类);修复落地清单(contain 施加处逐一像素证据);escalate 清单;非触碰段零外溢(归因地板);冻结夹具;tag batch-b9.5。

## 负向

上游零改动(众数锚定不修,越顶在 magazine 层矫正——修上游锚定属排版算法变更,记未来工作);真值/裁决只读;修复动作像素证据强制(b8.4 规矩);门禁无 API key。

## 明确不做

resolve_collision 的自动动作;众数锚定上游修复;zh 线;F2(下一步)。
