# Codex Plan C20A：Repair manager 强制 structured tool call

计划版本：2026-08-26 rev.3  
两天编排：WT2首项，transport 4–5h；C19合入后adapter 1–2h  
推荐执行模型：`gpt-5.6-sol`，reasoning `xhigh`  
网络/API：fake OpenAI-compatible client与fake executor；禁止真实请求。  
目标提交序列：

1. `feat(translator): add forced structured tool transport`
2. `feat(repair): require forced structured tool calls`（C19合入后）

## 0. 任务

把repair manager从“普通LLM文本中解析JSON”切换为provider层真正的forced structured tool call。生产路径只能消费恰好一个、名称正确、schema严格、state-bound的call；纯JSON文本、markdown、错误工具、多call、unknown/extra/超限参数全部fail closed。普通翻译接口和缓存保持兼容。

本批只实现OpenAI-compatible structured transport；`ExecutorTranslator`若尚无安全tool protocol，必须显式`supports_tool_calls=false`并留下residual，不能退回文本JSON。HITL binding由C20B、final/subset compliance由C20C处理。

本文件上下文自足，并给出与C19并行开发时使用的冻结接口。命令由Codex在Linux/WSL Bash独立worktree执行。

## 1. 权威、基线与接口冻结

- 审计基线：`57a12552da7a13523ad5a2e27b45473f24183208`。
- 英文TeX SHA-256：`a3e7a6237085d3879ab98f53265d3fac7450d18ee8610f6eb62230c6ba67fd08`。
- TeX 607–608：manager通过structured tool calls从六项closed actions选一项；decision只有action、target objects、bounded params，并由deterministic executor复验。

与C19并行时按以下冻结接口编码；第一commit不得修改`react/decide.py`生产路径。C19合入后，第二commit只做adapter/rename并切换production，不改变语义：

```text
Action enum:
  reprocess_omitted_text
  reallocate_continuity_chain
  retypeset_article_region
  contain_overflowing_heading
  resolve_text_collision
  no_action

Decision:
  action
  issue_ids[]
  target {physical_page_number, article_id, element_refs[]}
  parameters {}
  state_sha256
```

无自由文本reason、coordinate、replacement text、prompt、URL或code。C19的deterministic decoder/preflight拥有最终裁决权。

## 2. 启动与当前证据

```bash
git status --short --branch
git rev-parse HEAD
mkdir -p .tmp/c20a
export UV_CACHE_DIR="$PWD/.tmp/c20a-uv-cache"
```

审计基线中：

- `BaseTranslator.llm_translate()`只返回字符串；
- `OpenAITranslator`可请求JSON mode，但没有forced tool-call接口；
- `ExecutorTranslator`只转发普通/JSON-mode文本；
- `react/decide.py`要求`reason`并从文本JSON解析；
- current request/decision logs可能保留`prompt_text`和raw reply。

先跑当前基础gate：

```bash
timeout 90s uv run python spec_checks/spec_check_repair_transaction.py
timeout 90s uv run python spec_checks/spec_check_cli_credentials.py
```

若C19已经合入，还要跑`spec_check_repair_methodology_contract.py`；若并行未合入，使用本计划fixture中的冻结typed Decision adapter，不复制C19 comparator/handler。

## 3. 独立transport capability

在`BaseTranslator`增加可选接口，不修改普通翻译contract：

```python
@dataclass(frozen=True)
class ToolCallResult:
    tool_name: str
    arguments: Mapping[str, object]
    provider_call_id: str | None
    finish_reason: str | None

class BaseTranslator:
    def supports_tool_calls(self) -> bool: ...
    def llm_tool_call(
        self, *, messages, tool_name, parameters_schema,
        state_sha256, cache_context, request_limits
    ) -> ToolCallResult: ...
```

要求：

- base默认false，入口抛typed `ToolCallsUnsupported`；
- `llm_translate()`签名、返回值、普通cache bytes和调用点不变；
- result只暴露typed args和非敏感metadata；content不作参数；
- provider call ID不进入semantic/cache digest；
- transport-level limits包含timeout、max attempts、argument bytes/depth；
- no-network translator永远false。

## 4. OpenAI-compatible forced call

请求必须包含语义等价字段：

```text
tools=[{type:function,function:{name:"select_repair_action",parameters:<schema>,strict:true}}]
tool_choice={type:function,function:{name:"select_repair_action"}}
```

provider/SDK兼容性：

- capability按endpoint+model显式声明/探测；不支持strict tools则fail closed；
- 不要假设所有OpenAI-compatible endpoint支持`oneOf`；provider schema使用strict-compatible单对象+action enum，action-specific组合约束由deterministic decoder执行；
- fake tests使用SDK真实response object shape或最小协议adapter，不只用自造dict；
- refusal、length/incomplete、zero calls、multiple calls、wrong type/name均拒绝；
- arguments必须是JSON object，拒绝duplicate key、NaN/Infinity、超限深度/数组/字符串/bytes；
- 即使content含JSON，也只读取tool_calls；无tool call即拒绝。

Retry语义：读取bounded config `max_tool_call_attempts`和每attempt timeout；有效范围建议1–3。Schema/logic拒绝不重试；只有明确transient transport状态可在上限内重试。C22只允许一次paid CLI job，不代表job内只有一个HTTP request；report记录attempt/call/cache counts。

## 5. Repair tool schema

工具名固定`select_repair_action`。Provider-level schema顶层和所有对象`additionalProperties:false`，所有字段required；用空值表示no target，不省字段：

```json
{
  "action": "<six-value enum>",
  "issue_ids": [],
  "target": {
    "physical_page_number": null,
    "article_id": null,
    "element_refs": []
  },
  "parameters": {
    "max_source_chars": null,
    "fit_profile": null,
    "spacing_profile": null,
    "minimum_scale_profile": null,
    "wrap_policy": null,
    "collision_axis": null
  },
  "state_sha256": "64 lowercase hex"
}
```

上述是strict-provider兼容的wire superset schema：`parameters`六个properties全部required、类型分别为`integer|string enum|null`，对象`additionalProperties:false`；某action不用的slot必须为null，不能省略。允许的非null组合由versioned action→parameter-slot矩阵冻结：`reprocess_omitted_text`只可用`max_source_chars`；chain/article reflow只可用声明的fit/spacing/wrap tokens；heading只可用minimum-scale/wrap tokens；collision只可用collision-axis token；`no_action`全部null。具体enum/range来自C19同一canonical config，provider schema生成器与decoder共用它，禁止两份字段表。字段有长度/count/range上限。Provider schema不允许reason、box、source/target replacement、arbitrary nested metadata。

Wire与domain明确分层：provider decoder先验证六键齐全、forbidden slots均null、required slots非null且合法；随后剥离所有null slots，才构造C19 canonical `Decision.parameters`。因此wire no_action有六个null slots，而domain no_action的parameters恰为`{}`。C19 executor永远看不到wire null placeholders。

Deterministic per-action decoder再检查：

- action为六项enum；
- `no_action` wire必须`issue_ids=[]`、target为`null/null/[]`、六个parameter slots全null；canonicalize后domain parameters为`{}`；
- 其他action的issue IDs非空且来自当前state；
- target physical page/article/elements存在、同owner、非unsupported；
- non-null parameter slot set/enum/numeric bounds与action matrix完全一致；null slots在进入C19前剥离；
- state hash与当前RepairKnowledgeState一致；
- issue kind与action mapping、roles/assets/limits由C19 preflight复验。

任一失败时handler零调用、state零mutation；记录typed拒绝reason，不让模型自由文本reason进入控制逻辑。

## 6. Cache与敏感数据

tool-call cache key至少包含：

```text
transport protocol/version
provider endpoint identity（去query/credential）
model + output-affecting params
canonical messages digest
forced tool name
canonical schema digest
RepairKnowledgeState digest
request limits/retry policy
```

cache value保存canonical arguments、finish reason、attempt metadata，不保存credential。Cache hit后仍重新跑schema、state和C19 preflight。

所有生产logging sinks、sidecar、request log、cache-error log和report不得保存全文`prompt_text`、完整provider request/response、原文/译文payload或raw model reply。当前普通translator在cache set异常时记录完整`text`/`translation`的路径必须改为只记录stable request digest、字符数、engine/model和typed exception class；provider error/retry/refusal同理。默认只保存：prompt template/version digest、state/schema digests、bounded issue/ref IDs、typed args、call/cache/attempt counts。若开发者需要raw payload，必须进入明确opt-in、敏感、默认关闭、gitignored路径；C22 artifact不得包含。

删除`react/decide.py`生产文本JSON fallback和`reason`依赖。兼容reader可读取历史record用于审计，但不能执行。

### 6.1 Exact run-intent/effective config

本批同时收口外部tool call所需的机器可读preflight。扩展现有`effective_config_report()`，保持credential redaction，并新增稳定字段：input basenames+SHA（无绝对路径）、lang-in/out、selected physical pages/output mode、translator/term/repair model identity、QPS与worker pools、request/tool timeouts、repair iteration/action/call limits、`max_tool_call_attempts`、cache policy、working/output path类别，以及`credential_configured: bool`。启用OpenAI但credential缺失时，普通`--validate-config`仍可服务离线模式；C22的`tools/validate_bounded_run_intent.py --require-external-credentials`必须返回`BLOCKED_PENDING_CREDENTIAL`，不打印值/长度/前后缀。

Validator只消费上述同源report与v4 binding摘要，拒绝missing/unknown/out-of-bound字段，并输出canonical run-intent digest。它不能另解析一份TOML或手写第二套default。C22给`--print-effective-config`的argv必须与paid command除print/validate mode外完全相同（包括`--files`、pages、reviews、work/output、debug）。

## 7. ExecutorTranslator处理

两天范围内不发明半套executor协议：

- `ExecutorTranslator.supports_tool_calls()`明确false；
- repair manager遇到它时输出`STRUCTURED_TOOL_CALLS_UNSUPPORTED`、保留issues/residual、停止；
- 普通executor translation不受影响；
- 如果仓库已有完整versioned executor tool protocol，可实现并测试；否则不得用`llm_translate(request_json_mode=True)`模拟支持。

后续独立批次可增加executor `operation=tool_call` capability negotiation，但不阻塞OpenAI路径和两天ABB job。

## 8. 测试

新增两个fast gates并声明`GATE_SET="fast"`。本分支直接逐项运行并把准确文件名交给WT0；只有WT0 integration owner修改统一`run_all.py` registry/meta-test，合入后验证存在、唯一、依赖顺序正确。

### 8.1 `spec_check_tool_call_transport.py`

使用fake OpenAI SDK client：

1.恰好一个forced call成功；
2.content-only JSON拒绝；
3.markdown JSON拒绝；
4.zero/two calls拒绝；
5.wrong type/name拒绝；
6.malformed/duplicate-key/NaN/oversized/deep args拒绝；
6a.六个action逐一通过真实provider strict-schema validator并canonicalize到预期C19 parameters；wire no_action全null→domain`{}`；unused slot非null、required slot缺失/null、action-specific组合错误均在handler前拒绝；
7.refusal/truncation拒绝；
8.transient retry不超过config，logic error零retry；
9.unsupported endpoint/model fail closed；
10.Executor不调用ordinary translate fallback；
11.schema/model/state/params任一改变cache miss；
12.cache hit仍schema/preflight；
13.普通`llm_translate`和existing cache fixture bytes不变；
14.用logger capture覆盖普通translation cache-set error、provider error/retry/refusal和repair schema error；所有log/report均无原文、译文、prompt、raw reply或secret，只含digest/count/typed metadata。
15.exact paid-like argv的effective report包含本节全部字段；漏`--files`、bounds缺失、enabled OpenAI无credential、超界attempt/QPS分别fail closed；report和run-intent无secret/绝对路径。

### 8.2 `spec_check_repair_tool_schema.py`

六action合法decode正例；覆盖unknown/extra/reason/box/free text、stale state、wrong issue kind、cross owner、unsupported page、unknown ref、out-of-range、no_action非空。每个负例证明handler未调用。

与C19集成后，构造一个valid tool call进入single-action transaction，再用content-only JSON证明residual+stop而非fallback。

## 9. 必跑命令

```bash
timeout 90s uv run python spec_checks/spec_check_tool_call_transport.py
timeout 90s uv run python spec_checks/spec_check_repair_tool_schema.py
timeout 90s uv run python spec_checks/spec_check_repair_transaction.py
timeout 90s uv run python spec_checks/spec_check_cli_credentials.py
timeout 90s uv run python spec_checks/spec_check_gate_registration.py
timeout 600s uv run python spec_checks/run_all.py --set fast
```

集成branch必须再跑：

```bash
timeout 90s uv run python spec_checks/spec_check_repair_methodology_contract.py
timeout 90s uv run python spec_checks/spec_check_repair_action_handlers.py
timeout 90s uv run python spec_checks/spec_check_tool_call_transport.py
timeout 90s uv run python spec_checks/spec_check_repair_tool_schema.py
```

这些文件中只有前两个由C19创建；本计划明确创建后两个。所有必跑入口均由C19或本计划实际交付。

## 10. 文件面、提交与交接

预期：

```text
babeldoc/main.py
babeldoc/translator/translator.py
babeldoc/translator/cache.py（仅tool namespace，普通格式不改）
babeldoc/tools/executor/translator.py
babeldoc/magazine/react/decide.py
babeldoc/magazine/react/cache_key.py
babeldoc/magazine/react/config.py
configs/repair_actions.json 或 tool-call config
tools/validate_bounded_run_intent.py
spec_checks/spec_check_tool_call_transport.py
spec_checks/spec_check_repair_tool_schema.py
由WT0 integration owner统一更新的`spec_checks/run_all.py`，不得在本并行分支暂存
```

分两次精确stage，不用`git add -A`：

- Commit 1只含`BaseTranslator`/OpenAI transport、tool cache namespace、Executor unsupported capability、日志redaction和transport gate；不碰C19 state/comparator/handlers/production decide。
- C19 commits进入WT0后，integration owner先精确cherry-pick Commit 1。WT2工作树保持clean并执行`git switch -c c20a-adapter <含C19和Commit1的integration-commit>`，不reset/rebase旧branch；Commit 2修改`react/decide.py`/config adapter，把生产路径切到forced call并跑C19+C20A gates。

```bash
git status --short
git diff --check
git add -- <逐项确认的上述实际pathspec>
git diff --cached --check
git diff --cached --stat
git commit -m "<对应的固定commit主题>"
```

交接：两个commit、capability matrix、schema/cache versions、retry limits、C19 adapter说明、所有正负测试exit code、确认无真实API/无raw prompt artifact。Integration owner只在C19后合入第二commit并跑第9节集成gates。

## 11. 完成与停止条件

完成：

- OpenAI production repair只消费forced named tool call；
- 纯文本JSON、多call、错误schema和stale state全部fail closed；
- 普通翻译/API cache不破坏；
- Executor unsupported时明确residual，不fallback；
- cache/report不存全文prompt/raw reply/secret；
- retry/timeout有界可审计；
- 新gates声明为fast、分支内直接运行全绿，且WT0合入后完成canonical注册验证；
- 与C19 single-action transaction集成通过；
- 未发真实请求。

时间盒分两段判断：transport phase active time≤5h；此时只要求新tool transport自身绝无文本JSON fallback，旧production decide尚未切换是预期状态。Adapter phase在C19合入后active time≤2h，累计active time≤7h；只有这一步完成时才要求production repair路径完全移除文本JSON fallback。

停止：目标provider SDK/endpoint无structured calls、必须改普通翻译cache才能继续、C19冻结接口发生语义冲突、strict superset+nullable schema仍无法通过真实provider validator、日志不可避免泄露全文/secret、任何测试联网、transport phase超过5h仍无forced-call transport，或adapter phase超过2h仍有production文本JSON fallback。报告blocker，不用JSON mode冒充tool calling。
