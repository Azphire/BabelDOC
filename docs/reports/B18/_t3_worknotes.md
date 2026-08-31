# T3 工作笔记(实现前勘察,随做随更)

## 现状机制(读码结论,2026-08-31)

- 跨页 title 链只允 `STRATEGY_PROPORTIONAL`([chain_translation.py:1659](../../../babeldoc/magazine/chain_translation.py#L1659)):切点按**源份额**估计,再 `_snap_title_split_to_lexical_boundary` 吸附到词界;`_build_allocation` 用 min readable scale(title 用 `title_min_scale`)在各成员框逐段实测,任一段不进 → 该级作废 → allocation None → `chain_target_overflow` 释放。
- 同页 column 标题链在 title_typeset 侧本就有"联排"形态:union box + 拼接 target(_prove_title_chains 736-772)。跨页对每成员各自 `_render_owner`,**scale 各搜各的,无同 scale 约束**。
- Courier doUo7 实数:member 框 [60.6,677.9,445.0,724.2](宽 384.4)与 [59.2,678.1,252.0,724.0](宽 192.8),源 30pt,各高 ~46pt(单行框);joint 调用发生过(cache 在手),溢出于分配段。

## T3 改动点

1. `chain_translation._allocate_target`:cascade 全败且 `pair_class=="title"`、双成员 → `_attempt_joint_fit`:
   - 切点 = 词界中最接近**框宽份额**者(非源份额);
   - 公共 scale 二分 [title_min_scale, 1.0]:每候选 scale 用按 scale 缩放的 style 实测两段各入各框(逐字节消费完 = fit);
   - 成功 → `_build_allocation(strategy="joint_fit")`,走既有 joint_success 通道(守恒验证沿用);
   - 失败 → 现行释放不动。
2. `title_typeset`:链成员组渲染后加同 scale 约束——公共 scale = min(成员各自 fitted scale),以该 scale 定排重渲;报告新增结果类 `joint_fit`(公共 scale、各成员行数、基线取法)。基线取法 executor 落定:**框内垂直居中**(源标题墨迹充满框,居中≈源;取法写入报告)。
3. 溢出路径的 outcome 增记失败测量细节(哪个成员、哪段、消费到哪),为归因与回归服务。
4. 夹具:双成员跨栏标题联排(词界切点、两框同 scale)正向;极端超长降到 min_scale 仍溢出 → 释放兜底(B17 release 回归夹具仍绿)反向。

## 待运行时落定

- Courier 溢出的确切失败点(哪一段、哪级测量)——warm 重跑 + 新 outcome 细节读出。
- 该链走的是 `_allocate_target` 还是 `_legacy_allocation`(fragment_boxes 空提示可能无 slots → legacy;legacy 不测量,None 只可能来自 proportional/snap 失败 → 若是 legacy,溢出其实是**切点吸附失败**而非几何溢出,joint_fit 的挂点要同时覆盖 legacy 路径)。

## 执行结果(2026-08-31)

- 探针落定:Courier 链走 **slots** 路径;min scale 容量 [53, 11],proportional 切点给成员二 17 字(仅进 12)→ 溢出。宽度份额切点(~35/53)同样不可行——**可行域由容量决定**,份额只在可行域内择优。实现按此收敛:可行词界切点 = [len-cap2, cap1],择最近框宽份额者;公共 scale 二分取最大可行。
- 实样:chain Rm2XR joint_success,切点 "…Changing | Times" 词界;title 报告双成员 joint_fit,公共 scale 0.4(20pt),p2 两行 + p3 "Times" 连续呈现;released_title_chains 空;issues.after 6(B17 9),unowned 0,裸断 0。
- 溢出探针(allocation_probe)永久入报告:路径、容量、逐策略失败点。
