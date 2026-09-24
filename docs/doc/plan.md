# mini-agent 开发方案

## 一、项目定位

桌面本地任务助手。打字下指令 → LLM 理解 → 自主规划步骤 → 调用工具执行(操作文件、跑命令、处理文档)。

分三个版本迭代,第一版只做对话,第二版加 ReAct 循环+文件+命令执行,第三版补文档处理打通三个验收场景。后期主线(Go LLM 网关 / ERP agent)另起版本规划,不在本方案展开。

## 二、版本路线总览

| 版本 | 主题 | 验收场景 |
|---|---|---|
| v1 | 对话基座 | 多轮对话,流式回复,session 连续 |
| v2 | ReAct + 文件 + 命令 | agent 自主多步完成任务:读文件→改文件→跑命令 |
| v3 | 文档处理 + 规划 + 前端 | 整理文件夹 / 统计CSV月度总额 / md转HTML |
| 后期 | Go 网关 / ERP | 单独规划 |

---

# 第一版:对话基座

## 1.1 目标与切片路线

最小可用对话助手:打字下指令 → DeepSeek 流式回复 → 保持上下文。文件/命令/ReAct/文档都暂不做。

**核心原则:先练"流式 + 记忆"两个基本功,会话列表和 UI 是壳,壳最后套。**

切片顺序:

| 切片 | 内容 | 验收 |
|---|---|---|
| v1.0 | CLI 流式 + 多轮记忆(**不碰 Web**) | 终端连续对话,追问"刚才我说了什么"能答上 |
| v1.1 | FastAPI + WebSocket,把 CLI 的逻辑搬上 Web | WS 连上,流式多轮对话 |
| v1.2 | 会话管理:列表 / 历史 / 新增(CRUD) | 多会话并存、可切换 |
| v1.3 | 前端 UI(仿 trae-work/codex) | 并入 v3,协议长全后再画 |

v1.3 不单独排期:v2 加 confirm + tool_call 协议,v3 加 plan 协议,等协议长全后和 v3 前端一起做,现在画 UI 必然返工。

**架构纪律(CLI 先行的目的):runner 与传输层无关。** runner 只产出事件流(`AsyncIterator[Event]`),CLI 和 WebSocket 都是它的 renderer:

- runner:追加用户消息 → 调 LLM → `yield` 事件(chunk / done / error;v2 扩 tool_call 事件,confirm / ask_user 走回调不走事件;v3 扩 plan)
- CLI renderer(v1.0):消费事件,打印终端
- WS renderer(v1.1):消费事件,序列化成 JSON 推送
- v2 的命令确认在两种 renderer 下分别是统一输入通道读 y/n(见 2.6)和 confirm 消息往返,runner 代码不动

## 1.2 技术栈

- **语言**:Python 3.12+
- **LLM**:OpenAI 兼容协议调 DeepSeek
- **CLI**(v1.0):标准库 asyncio;`rich` 可选(流式 Markdown 渲染,不上也行)
- **后端**(v1.1 引入):FastAPI / WebSocket。走 WS 不走 SSE——v2 确认流程要服务器主动推 + 客户端回,SSE 单向凑不了
- **前端**(v1.3,并入 v3 做):Web,仿 trae-work/codex 样式(独立生成,不在本方案展开)
- **依赖管理**:`uv`

## 1.3 目录结构

v1.0 先建(CLI,无 main.py、无 web/):

```
mini-agent/
├── app/
│   ├── __init__.py
│   ├── cli.py                # v1.0 入口:终端渲染循环
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── events.py         # 事件类型(chunk/done/error),runner 与 renderer 的契约
│   │   ├── session.py        # Session 内存管理
│   │   └── runner.py         # 核心:收消息 → 调 LLM → yield 事件(禁止 print / WS 调用)
│   ├── llm/
│   │   ├── __init__.py
│   │   └── openai_compat.py  # OpenAI 兼容流式调用(DeepSeek 走这个),直读 config;不设 base 抽象/factory(单 provider,避免过度设计)
│   ├── config/
│   │   ├── __init__.py
│   │   ├── loader.py         # 加载 models.yaml + env 覆写
│   │   └── schema.py         # pydantic 校验
│   └── store/
│       ├── __init__.py
│       └── session_store.py  # SessionStore:内存 dict+TTL(v2.4 换 SQLite)
├── configs/
│   └── models.yaml
├── docs/
│   ├── commit/               # 提交记录
│   └── doc/plan.md           # 本文档
└── pyproject.toml
```

v1.1 新增:

```
app/
├── main.py                # FastAPI 入口,lifespan,挂载路由
└── api/
    ├── __init__.py
    ├── routes_chat.py     # WS /api/chat/stream(v1.2 加建会话 / 列表端点)
    └── routes_health.py   # GET /api/health
```

v1.3 新增 `web/`(前端,并入 v3 做)。

v2.0 新增 `app/tools/`(registry 注册中心 + 各工具模块,每个工具一个文件、自带 register)和 `app/obs.py`(观测埋点,见 1.6)、`logs/metrics.jsonl`(指标日志,gitignore)。仓库根的 `test_*.py` 为联调临时脚本,验收后不纳入结构。

## 1.4 模块职责

- **config/**:读 `models.yaml`,pydantic 校验,env 覆写 key,`get_settings()` 单例
- **store/session_store.py**:`SessionStore` 内存 dict + TTL;v2.4 SQLite 替换实现,对外接口不变
- **llm/**:`openai_compat.chat_stream(messages, model, cfg) -> AsyncIterator[str]` 直读 config,不设抽象层/factory(单 provider)
- **agent/events.py**:事件数据类型(chunk / done / error),runner 与 renderer 之间的唯一契约;v2 扩 tool_call 事件(confirm / ask_user 走回调不走事件),v3 扩 plan
- **agent/session.py**:`Session` 数据结构(messages, session_id, created_at);存储逻辑在 `store/session_store.py`,单例放 `agent/store.py`(被 api 路由引用)
- **agent/runner.py**:**传输无关**。追加用户消息 → 调 LLM → 流式 yield 事件 → assistant 完整回复落回 session。代码里不允许出现 `print` / websocket 调用(v2 改为 ReAct 循环)
- **cli.py**(v1.0):stdin 读入 → 调 runner → 消费事件打印(`flush=True` 或 rich)
- **api/routes_chat.py**(v1.1):WS 收消息 → 调**同一个 runner** → 事件转 JSON 推回
- **obs.py**(v2.0):`log_event(type, **fields)` 写 `logs/metrics.jsonl` + 内存计数,`/api/metrics` 聚合(见 1.6)

## 1.5 关键数据结构

### `configs/models.yaml`

```yaml
default: deepseek-chat
models:
  - name: deepseek-chat
    provider: openai_compat
    base_url: https://api.deepseek.com/v1
    api_key: ${DEEPSEEK_API_KEY}
    model: deepseek-chat
  # 预留多模型,用户自加
```

### Message

```python
class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str
```

> v2 扩展:role 增加 `"tool"`,assistant 消息需携带 `tool_calls` 字段(见 2.7 第二坑)——v2.0 改 function calling 时一起扩 Message,否则 tool 结果没有合法的载体。

### 事件协议(runner → renderer)

v1 三种事件(v2 扩 tool_call 事件,confirm / ask_user 走回调不走事件;v3 扩 plan):

```python
class ChunkEvent(BaseModel):
    type: Literal["chunk"]
    content: str

class DoneEvent(BaseModel):
    type: Literal["done"]

class ErrorEvent(BaseModel):
    type: Literal["error"]
    message: str
```

CLI renderer 直接打印;WS renderer 包上 `session_id` 发 JSON。

### WebSocket 消息协议(v1.1)

前端 → 后端:
```json
{"type": "user_message", "session_id": "xxx", "content": "你好"}
```

后端 → 前端:
```json
{"type": "chunk", "session_id": "xxx", "content": "你"}
{"type": "chunk", "session_id": "xxx", "content": "好"}
{"type": "done", "session_id": "xxx"}
{"type": "error", "session_id": "xxx", "message": "..."}
```

## 1.6 可观测性（全程贯穿）

一个模块 `app/obs.py`,三个接入层,数据落 `logs/metrics.jsonl`(每行一条 JSON),内存计数器供 `/api/metrics` 聚合。runner 禁 print,但允许调 `obs.log_event()`——观测不违反传输无关纪律。

埋点分三层:

| 层 | 记什么 | 在哪埋 | 接入切片 |
|---|---|---|---|
| LLM 调用 | model、延迟、prompt/completion tokens | `openai_compat.chat_stream` 流结束时 | v2.0 |
| 回合(一次用户输入到 done) | session_id、耗时、步数、tool_call 次数/成败、错误 | `runner.run_turn` | v2.0 |
| 人机交互 | confirm 等待时长 + approved/rejected;ask_user 等待时长 + answered/declined/cancelled/timeout 分布 | confirm / ask_user 回调 | v2.1 / v2.2 |

- **token 计数**:OpenAI 协议流式默认不回 usage,要带 `stream_options={"include_usage": True}`,末尾 chunk 里取(DeepSeek 兼容)
- **聚合端点** `GET /api/metrics`:会话数、回合数、tool_call 数、错误数、LLM 累计 token、平均延迟(v2.4 接入)
- **v1 缺口(已在 v2.0 补上)**:chat_stream 的耗时/token 记录已接入 log_event(tools 参数 / delta yield / usage 拿取残局同步修完);遗留项是 `app/chat.py`(非流式 + 自带 print)已无任何引用,属死代码,待清理
- **调试收益**:ReAct 多步出问题时,jsonl 直接 grep 出每步耗时与成败;**简历表述**:"设计 LLM 应用全链路可观测性:结构化指标日志 + 聚合端点,量化 token 成本、回合延迟、工具调用成功率、人机交互等待时长"

## 1.7 任务清单

### v1.0:CLI 流式 + 多轮(本周,不碰 Web)

- [x] 1. 脚手架:`uv init` + 目录结构,`python -m app.cli` 能启动
- [x] 2. 配置:`models.yaml` + pydantic 校验 + env 覆写(schema.py Setting/ModelConfig + get_model 内 env 覆写;openai 钉 1.x,3.x 的 httpx2/httpcore2 流关闭有 bug)
- [ ] 3. LLM 客户端:抽象 + OpenAI 兼容实现(DeepSeek),流式 `AsyncIterator[Chunk]`(流式实现已有 chat_stream,抽象留到 v1.1 一起收)
- [x] 4. Session:Session / SessionStore 内存版,创建 / 读取 / 追加
- [x] 5. events + runner:收消息 → 调 LLM → yield chunk/done/error,完整回复落回 session
- [x] 6. CLI 渲染循环:stdin 读入 → runner → 打印事件(runner 里不写 print)
- [x] 7. 联调验收:终端多轮对话连续

### v1.1:FastAPI + WebSocket

- [x] 1. FastAPI 脚手架:hello world + lifespan + 挂载路由
- [x] 2. WebSocket 路由:收 user_message → 调同一个 runner → 事件转 JSON 推回
- [x] 3. 健康检查:`GET /api/health` 返回 LLM 配置可用性
- [x] 4. 验收:wscat 或简易测试页连 WS,流式多轮对话

### v1.2:会话管理(CRUD)

- [x] 1. SessionStore 加 list / get / create
- [x] 2. WS 支持指定 / 新建 session_id(必要时加 POST 建会话端点)
- [x] 3. 验收:多会话并存,历史可拉取、可切换

### v1.3:前端 UI(并入 v3)

- [ ] 1. 仿 trae-work/codex 对话 UI,连 WS 渲染流式 token
- [ ] 2. 与文件面板、命令确认弹窗、plan/tool_call 过程展示一并设计实现(见 3.2 ③)

## 1.8 验收

- **v1.0(核心验收,CLI 即可)**:终端启动 → 输入"你好" → 流式回复逐字出现 → 追问"刚才我说了什么" → 能答上
- **v1.1**:wscat / 测试页走 WS,同等多轮流式效果
- **v1.2**:能新建、切换、列出多个会话,历史消息不丢

---

# 第二版:ReAct + 文件 + 命令执行

## 2.1 目标

让 agent 能在对话里读写文件、跑命令(带确认),并且**跑在 ReAct 循环上**:LLM 决策 → 调 tool → 观察结果 → 再决策 → 直到完成,能自主多步干完一件事(读文件 → 改文件 → 跑验证)。

单步版和循环版代码量几乎一样(只差一个 while + max_steps),直接上循环,不留半成品。

切片路线:

| 切片 | 内容 | 验收 |
|---|---|---|
| v2.0 | 读文件最小闭环:工具注册 + read_file + function calling + ReAct 循环 + 观测埋点 | 对话"读一下 ./docs/doc/plan.md" → 循环跑通 |
| v2.1 | 补文件工具 + 命令确认:write/edit + run_command + confirm | 文件改写、命令确认可用 |
| v2.2 | 澄清提问:ask_user 工具 + 协议 + prompt | 提问澄清可用(三态+超时) |
| v2.3 | 多步串联联调 | 2.9 多步串联场景跑通（三场景需要 v3 工具,留到 v3.3） |
| v2.4 | 收尾:SQLite 落库 recent_files + `/api/metrics` 聚合端点 | 重启后最近访问可查;/api/metrics 有数据 |

## 2.2 新增能力

### ReAct 主循环
- `agent/runner.py` 改造:LLM 决策 → 调 tool → 观察结果 → 再决策 → 直到完成
- 终止条件:LLM 不再返回 tool_calls(给最终回复)或达到 `MAX_STEPS`(硬上限,防死循环,默认 6)
- 中间步骤(tool_call)实时推前端,可见执行过程

### 文件工具
- `read_file(path) -> content`
- `write_file(path, content)`
- `edit_file(path, old_str, new_str)` — 精确字符串替换
- `list_recent_files(limit=20)` — 查最近访问(v2.1 内存占位,v2.4 换 SQLite)

### 命令执行
- `run_command(cmd, cwd)` — 执行前走确认回调(WS 推前端 / CLI 走统一输入通道),确认后执行
- 超时控制(默认 30s)
- 工作目录无限制,每次确认兜底

### 澄清提问（ask_user）
- `ask_user(question, options=None)` — Agent 遇到需求歧义 / 多方案决策 / 缺少关键信息时，主动向用户提问
- **三态+超时响应**：`answered`（用户给出回答）/ `declined`（用户拒答，Agent 应用默认值继续）/ `cancelled`（用户取消整个任务）/ `timeout`（超时未响应，Agent 自行决策）
- **超时控制**：可配置（默认 5 分钟），超时后返回 `timeout` 状态，Agent 自行判断用默认值继续或中止
- **防止滥用**：系统 prompt 限制最多问 2-3 个问题，要求先充分检索上下文再提问，避免挤牙膏式追问
- 执行路径特殊：与普通工具不同，`ask_user` 不直接执行，由 runner 层拦截后挂起等外部输入

### 最近访问记录
- SQLite:`recent_files(id, path, op, accessed_at)`
- 每次 read/write/edit 自动写一条

## 2.3 目录新增

```
app/
├── agent/
│   └── runner.py              # 改造:单次调 LLM 改为 ReAct 循环
├── tools/
│   ├── __init__.py
│   ├── registry.py            # 工具注册中心(v3 文档工具也用这个)
│   ├── file.py                # read/write/edit/list_recent
│   ├── shell.py               # run_command(带确认流)
│   └── ask_user.py            # 澄清提问工具(runner 层拦截，不直接执行)
├── store/
│   └── db.py                  # SQLite 连接 + 表初始化
```

## 2.4 SQLite Schema

```sql
CREATE TABLE recent_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL,
    op TEXT NOT NULL,           -- read / write / edit
    accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_recent_files_accessed ON recent_files(accessed_at DESC);
```

## 2.5 命令确认协议(WebSocket 新增)

后端 → 前端:
```json
{"type": "confirm_request", "session_id": "xxx", "confirm_id": "cf_123", "cmd": "ls ~/Documents", "cwd": "/"}
```

前端 → 后端:
```json
{"type": "confirm_response", "session_id": "xxx", "confirm_id": "cf_123", "approve": true}
```

- `confirm_id`：本次确认的唯一标识，响应时带回，防止迟到/错乱的响应污染下一次确认（与 `ask_user` 的 `question_id` 作用一致）

确认后执行,结果走:
```json
{"type": "command_output", "session_id": "xxx", "stdout": "...", "stderr": "...", "exit_code": 0}
```

工具执行过程走:
```json
{"type": "tool_call", "session_id": "xxx", "step": 1, "name": "read_file", "args": {...}, "result": "..."}
```

> 前端 UI(文件面板 / 确认弹窗 / tool_call 展示)并入 v3,v2 验收用 wscat / 简易测试页完成。

### 确认回传机制(runner 保持传输无关)

runner 的事件流是**单向**的(yield 出去),但确认需要用户的答案**回传**给 runner。解法:runner 接收一个 **confirm 回调**,不碰传输层:

```python
async def run_turn(session, text, confirm=None, ask_user=None, tools=TOOLS):
    ...
    ok = await confirm(cmd, cwd) if confirm else False   # run_command 执行前
```

- CLI 传:走**统一输入通道**——`confirm = lambda cmd, cwd: cli_input.wait_line(prompt=f"执行 {cmd}? [y/N]")`,从全局单 queue 取下一行并解析 y/n,**不直接调 input()**(见 2.6 统一输入通道)。解析规则:只认 y/n(忽略大小写),**非 y/n 输入 → 忽略并重新等待**(比如队列里残留的"继续"不算回答,也不视为 declined——必须等明确 y/n)
- WS 传:推 `confirm_request`,挂起等 `confirm_response` 返回

runner 仍然不 print、不碰 WS ✅

## 2.6 澄清提问协议（ask_user，WebSocket 新增）

Agent 在 ReAct 循环中遇到需求歧义、多方案选择、缺少关键信息时，调用 `ask_user` 工具主动提问。与普通工具不同，`ask_user` 由 runner 层**特殊拦截**，挂起执行等待用户回复。

后端 → 前端：
```json
{
  "type": "ask_user",
  "session_id": "xxx",
  "question_id": "uq_123",
  "question": "登录功能用哪种方式实现？",
  "options": ["账号密码", "手机号+验证码", "微信OAuth"],
  "timeout_seconds": 300
}
```

- `question_id`：本次提问的唯一标识，响应时带回，防止串题
- `options`：可选，建议答案列表。前端展示为按钮，用户可点选或输入自由文本
- `timeout_seconds`：超时时间（默认 300s / 5 分钟），超时后 runner 自动恢复

前端 → 后端：
```json
{
  "type": "ask_user_response",
  "session_id": "xxx",
  "question_id": "uq_123",
  "status": "answered",
  "answer": "手机号+验证码"
}
```

**三态+超时 `status`**：

| status | 含义 | runner 行为 | Agent 收到的 tool_result |
|---|---|---|---|
| `answered` | 用户给出了回答 | 正常继续 | `answer` 字段内容 |
| `declined` | 用户拒绝回答这个问题 | 继续循环 | `"用户拒绝回答此问题，请基于合理假设继续"` |
| `cancelled` | 用户取消整个任务 | 终止 ReAct 循环，yield DoneEvent | —（循环直接结束） |

**超时处理**：
- 超时后 status 自动设为 `timeout`，runner 恢复执行
- Agent 收到：`"用户超时未响应（已等待 5 分钟），请基于合理假设继续，或中止任务等待用户回来"`
- Agent 自行判断：低风险的继续、高风险的中止并汇报

**Runner 拦截机制**：

`ask_user` 在注册形式上与普通工具一致（有 schema、能被 LLM 调用），但**执行路径不同**：

```
普通工具：  LLM 调 tool → registry.execute() → 立即返回结果 → 继续
ask_user：  LLM 调 tool → runner 检测到 ask_user → 拦截 → 调 ask_user_callback →
            挂起等回复 → 回复到达 → 作为 tool_result 喂回 → 继续
```

实现方式：runner 的 ReAct 循环中加一个 `if call.name == "ask_user"` 的分支，不走 `registry.execute()`，改走注入的 `ask_user_callback`。就一个 `if`，不引入额外抽象（当前只有 `ask_user` 一个"需要等用户"的工具，过度抽象是浪费）。

**回调签名**：

```python
# runner 接收的回调（由 CLI / WS 层注入）
async def ask_user_callback(
    question: str,
    options: list[str] | None = None,
    timeout: int = 300,
) -> AskUserResult:
    ...

# 返回值（三态+超时 + 可选 answer）
@dataclass
class AskUserResult:
    status: Literal["answered", "declined", "cancelled", "timeout"]
    answer: str | None = None
```

### 统一输入通道（CLI 全局唯一 stdin 读取者）

CLI 有三个输入源要读 stdin:主循环读对话消息、ask_user 读回答、confirm 读 y/n。**绝不能各开各的 `input()`**——谁抢到算谁的,主消息会被 ask 线程吃掉、confirm 永远读不到。收拢成一个:

- **全局只留一个常驻读线程**:循环 `input()` 读行后**不能直接 `queue.put()`**——`asyncio.Queue` 非线程安全(官方文档明确),外线程直接 put 有不唤醒/竞态风险(表现为偶发输入无响应,非 debug 不报错)。正确姿势:启动读线程前捕获 loop,读线程用 `loop.call_soon_threadsafe(queue.put_nowait, line)` 投递(跨线程投递 asyncio 队列的标准姿势)
- **主循环从 queue 分发**,按当前状态路由:
  - ask 等待态 → 当作问题的回答
  - confirm 等待态 → 当作 y/n
  - 否则 → 当作新的对话消息
- **语义写明**:ask 挂起期间,**任何输入都算回答**(要发新指令先取消 ask,Claude Code 同款处理)——不存在"挂起时输入别的内容"这个状态
- 超时:`wait_for(queue.get(), timeout)`,超时只放弃等待,读线程继续活着,不泄漏

- CLI renderer:实现超时,与 WS 行为一致(默认 300s),超时后返回 `timeout` 态,Agent 自行决策
- WS renderer：推 `ask_user` 消息，在连接上挂起等 `ask_user_response`，同时启动超时计时器（超时是 WS 场景的刚需——用户可能关网页走人）

## 2.7 ReAct 循环伪代码(流式版)

**必须统一流式**(`stream=True`):非流式会丢掉 v1 的打字机效果(体验倒退)。边收边判断:

```python
for step in range(MAX_STEPS):
    stream = llm.chat(messages, tools=registry.definitions, stream=True)
    content, tool_calls_buf = "", {}          # tool_calls 按 index 累积
    async for chunk in stream:
        delta = chunk.choices[0].delta
        if delta.content:
            content += delta.content
            yield ChunkEvent(content=delta.content)   # 有文本 → 逐字推给用户
        if delta.tool_calls:
            buffer(tool_calls_buf, delta.tool_calls)  # 有工具调用 → 累积,不给用户看
    # 流结束:分片 arguments 拼完整后才 json.loads(见下)
    if tool_calls_buf:
        messages.append(assistant(content=content or None, tool_calls=tool_calls_buf))  # content+tool_calls 同条消息:assistant 必须先落 messages 再挂 tool 结果;同轮文本(content)也必须带上,否则模型下一轮看不到自己上轮说的话,上下文永久丢失
        for call in parse(tool_calls_buf):            # 按 index 累积拼接再解析
            # ---- ask_user 特殊拦截：不走 registry.execute ----
            if call.name == "ask_user":
                result = await _handle_ask_user(call.args)  # 挂起等用户回复
                if result.status == "cancelled":
                    yield DoneEvent()                         # 用户取消 → 直接结束
                    return
                tool_result = _format_ask_user_result(result)  # answered/declined/timeout
            else:
                # 普通工具：正常执行（run_command 先走 confirm 回调）
                result = registry.execute(call)
                tool_result = str(result)
            yield ToolCallEvent(...)
            messages.append(tool_result)          # 简写!实现必须是 role=tool + tool_call_id 的完整消息,否则 API 400
    else:
        messages.append(assistant, content)           # 无 tool_calls → 本轮结束
        yield DoneEvent(); break
else:
    yield ErrorEvent(message="执行步数超限")
```

**⚠️ 流式 function calling 头号坑**:`tool_calls.arguments`(JSON 参数字符串)是**分片到达**的,必须**按 `index` 累积拼接**完整后再 `json.loads`,不能解析第一个分片。`id` / `name` 只在首片,`arguments` 每片追加。

**⚠️ 第二坑**:观察结果喂回时,伪代码里 `messages.append(tool_result)` 是简写——实际必须构造 `{"role": "tool", "tool_call_id": call.id, "content": ...}` 的完整消息,漏了 `tool_call_id` 会直接 API 400。

## 2.8 任务清单(先最小闭环,再铺开)

### v2.0:读文件最小闭环
- [x] 1. 工具注册中心:统一 schema(name, description, parameters),转 OpenAI function 定义(`tools/registry.py`,`definitions` + `execute`)
- [x] 2. read_file 一个工具够用(`tools/file.py`,自带 register)
- [x] 3. LLM function calling 接入:流式处理 tool_calls(按 index 累积拼接 → json.loads)(`tools/calls.py`,buffer 只累积 / parse 流结束后解析,职责分离;openai_compat 加 `tools` 参数)
- [x] 4. runner 改造 ReAct 循环:流式 + 多轮决策 + MAX_STEPS 终止 + tool_call 事件(`MAX_STEPS=6`;assistant(content+tool_calls) 与 role=tool 结果成对落历史;tool 执行异常喂回模型自纠)
- [x] 5. 观测埋点:`app/obs.py`(log_event → logs/metrics.jsonl + 内存计数) + chat_stream 记 LLM 延迟/token(顺带修 tools 参数 / delta yield / usage 拿取残局,见 1.6) + 回合耗时埋点(usage 在末尾空 choices 的 chunk 上,需先接住再 continue)
- [x] 6. ⭐ 验收闭环:对话"读一下 a.md" → 循环跑通(先证明循环没问题,再铺工具)(实测 metrics:steps=2 / tools=1 / tools_ok=1)

### v2.1:文件工具 + 命令确认
- [ ] 1. write_file / edit_file
- [ ] 2. 命令工具:run_command + confirm 回调 + 执行超时 30s（**确认等待永不超时**,只等用户明确点 y/n）
- [ ] 3. WebSocket 扩展:confirm_request/response + tool_call 协议 + confirm_id 防串题
- [ ] 4. list_recent_files:内存列表占位(SQLite 延后到 v2.4)
- [ ] 5. confirm 交互埋点:等待时长 + approved/rejected 结果记入 metrics(见 1.6)

### v2.2:澄清提问(ask_user)
- [ ] 1. ask_user 工具定义 + runner 拦截分支 + ask_user_callback 注入
- [ ] 2. WebSocket 扩展:ask_user / ask_user_response 消息 + 超时计时器 + question_id 防串题
- [ ] 3. CLI 统一输入通道:单常驻读线程 + 单 queue + 按状态分发(ask 回答 / confirm y/n / 新消息),主循环和 confirm 都改走它,不许再直接 input()
- [ ] 4. CLI renderer:ask_user 终端交互 + 超时（wait_for(queue.get(), 300),与 WS 同默认 300s）
- [ ] 5. 系统 prompt:引导 Agent 合理使用 ask_user（先查再问、最多 2-3 个、避免挤牙膏）
- [ ] 6. ask_user 交互埋点:等待时长 + answered/declined/cancelled/timeout 分布记入 metrics(见 1.6)

### v2.3:多步串联
- [ ] 1. 联调:2.9 多步串联验收(wscat / 测试页;三场景需要 v3 工具,留到 v3.3)

### v2.4:收尾
- [ ] 1. SQLite 初始化 + recent_files 落库(替换内存占位)
- [ ] 2. `GET /api/metrics`:聚合内存计数(会话数、回合数、tool_call 数、错误数、LLM 累计 token、平均延迟) + jsonl 落地检查

> 顺序原则(自己的原则):先跑通核心循环(v2.0)再扩展工具(v2.1)——否则一堆工具写完才发现循环有问题,返工。SQLite 延后(v2.4)减少早期复杂度。

## 2.9 验收

- 对话"读一下 ./docs/doc/plan.md"(或 Windows `C:\...\plan.md`) → agent 调 read_file → 内容流式显示
- 对话"把 plan.md 里 foo 改成 bar" → agent 调 edit_file → 文件已改
- 对话"跑一下 ls ~/Documents" → 确认(测试页) → 执行 → 输出显示
- **ask_user 正常路径**：对话"帮我做个登录功能" → Agent 发现歧义 → 调 ask_user 弹选项 → 用户选"手机号+验证码" → Agent 继续执行
- **ask_user declined（拒答）**：Agent 提问后用户点"跳过" → status=declined → Agent 基于默认值继续，不停滞
- **ask_user cancelled（取消任务）**：Agent 提问后用户点"取消任务" → 循环直接终止，回到等待状态
- **ask_user 超时**：Agent 提问后不操作 → 5 分钟超时 → Agent 收到 timeout 提示 → 自行判断继续或中止
- **多步串联(ReAct 核心验收)**:对话"读一下 a.md,把 foo 改成 bar,然后跑 python test.py 验证" → agent 连续决策:read_file → edit_file → 确认 → run_command → 报告结果
- **观测验收**:每轮对话后 `logs/metrics.jsonl` 有 llm / turn 记录(延迟、token、步数);工具调用与 confirm/ask_user 有对应埋点;`curl /api/metrics` 返回聚合数据

---

# 第三版:文档处理 + 规划 + 前端

## 3.1 目标

在 v2 的 ReAct 循环上补齐四块,覆盖三个验收场景:整理文件夹、统计CSV月度总额、md转HTML。

① 文档处理工具集 ← 大头
② 规划能力(planning prompt + plan 事件)
③ 前端可视化(plan + tool_call 过程展示,v1.3 的前端也在这里做)
④ 端到端验收(三场景)

切片路线:

| 切片 | 内容 | 验收 |
|---|---|---|
| v3.0 | 文档处理工具集:CSV / Excel / Word / md_to_html | 各工具单独可用 |
| v3.1 | 文件工具补充 + 规划能力:move_file / make_dir + plan prompt + plan 事件 | 整理文件夹可规划执行 |
| v3.2 | 前端可视化:对话 UI + plan/tool_call 展示 + 确认弹窗 + 文件面板 | 前端跑通所有协议 |
| v3.3 | 端到端验收:三场景串联 | 三场景端到端跑通 |

## 3.2 新增能力

### ① 文档处理工具集
- `read_csv(path) -> rows` / `summary_csv(path, group_by_col, agg_col, agg_func)` — 月度总额走这个
- `read_excel(path)` / `write_excel(path, data)`
- `read_docx(path)` / `write_docx(path, content)`
- md→HTML:走 `markdown` 库,直接在 file 工具里加 `md_to_html(path)` → 写回 `xxx.html`

### ①b 文件工具补充（整理文件夹场景用）
- `move_file(src, dst)` — 移动/重命名文件，支持批量（src 可传 glob 模式）
- `make_dir(path)` — 创建目录（含父目录，等价 `mkdir -p`）
- 都加在已有的 `tools/file.py` 里，不新建文件

### ② 规划能力
- 任务规划 prompt 模板(系统提示引导先列步骤再执行)
- plan 事件推给前端,展示执行计划

### ③ 前端可视化(v1.3 的前端在此完成)
- 仿 trae-work/codex 对话 UI,连 WS 渲染流式 token
- 展示 plan(执行计划)+ tool_call(中间步骤)过程
- 命令确认弹窗:展示 cmd + cwd,确认/拒绝按钮
- write/edit 改动 **diff 预览**(4.1 已定:改动可见而非每步确认,v2 不加确认靠这里兜)
- "我的文件"面板:列出最近访问文件,点击在线查看/编辑

## 3.3 目录新增

```
app/
├── tools/
│   └── docproc/
│       ├── __init__.py
│       ├── csv.py             # read_csv / summary_csv
│       ├── excel.py           # read_excel / write_excel
│       ├── word.py            # read_docx / write_docx
│       └── markdown.py        # md_to_html
├── agent/
│   └── prompts.py             # 规划系统提示模板
└── web/                       # 前端(原 v1.3,并入这里)
```

## 3.4 WebSocket 新增消息

```json
{"type": "plan", "session_id": "xxx", "steps": ["...", "..."]}
```

## 3.5 任务清单

### v3.0:文档处理工具集
- [ ] 1. CSV 工具:read + summary(按月聚合)
- [ ] 2. Excel 工具:read + write
- [ ] 3. Word 工具:read + write
- [ ] 4. md_to_html 工具:`markdown` 库渲染,写回原目录

### v3.1:文件工具补充 + 规划能力
- [ ] 1. 文件工具补充:move_file + make_dir（整理文件夹场景用，加在 tools/file.py）
- [ ] 2. 规划 prompt 模板 + plan 事件:引导 LLM 先列步骤再执行

### v3.2:前端可视化
- [ ] 1. 对话 UI:仿 trae-work/codex,连 WS 渲染流式 token(原 v1.3)
- [ ] 2. plan / tool_call 过程展示
- [ ] 3. 命令确认弹窗 + ask_user 问答 UI
- [ ] 4. "我的文件"面板:列出最近访问文件,点击在线查看/编辑
- [ ] 5. write/edit diff 预览(4.1 决策的兜底,v2 不加确认靠它)

### v3.3:端到端验收
- [ ] 1. 验收场景串联:三场景端到端跑通

## 3.6 验收

- **整理文件夹**:对话"把 ~/Downloads 里的图片归到一个子目录" → agent 列文件 → 规划 → 调 move → 报告结果
- **统计CSV月度总额**:对话"统计 sales.csv 每月总额" → agent 调 summary_csv → 表格展示
- **md转HTML**:对话"把 readme.md 转成 HTML" → agent 调 md_to_html → 生成 readme.html

---

# 四、跨版本约定

## 4.1 边界决策(已定)

| 点 | 方案 | 理由 |
|---|---|---|
| Python 依赖管理 | `uv` | astral 出,新项目事实标准 |
| LLM 接入 | OpenAI 兼容协议 | DeepSeek 原生兼容,后期接其他模型只改 yaml |
| Session 持久化 | v1 内存,v3+ 视情况加 | 桌面助手单进程,重启可丢 |
| 命令执行工作目录 | 任意目录 + 每次弹确认 | trae/codex/cursor 主流做法 |
| md→HTML 输出 | 写回原目录,`xxx.md` → `xxx.html` | pandoc、VSCode 导出主流 |
| 文档处理顺序 | CSV → Excel → Word | 验收场景只涉及 CSV+md,其他按需迭代 |
| write/edit 确认策略 | **v2 不加确认,v3 前端做 diff 预览**(已定) | 主流 Codex/Cursor 是"改动可见"而非每步确认;v2 保持简单 |
| 最近访问存储 | SQLite 单文件 | 比 JSON 好查询/并发 |

## 4.2 不做的(划线)

- Go LLM 网关 / API 网关 — 后期主线,单独规划
- ERP agent / ERP 业务加深 — 后期主线
- 多用户权限 — 桌面助手单用户
- 桌面 app 打包(Electron/Tauri) — 第一~三版纯 Web
- Session 持久化到磁盘 — 桌面助手重启可丢

## 4.3 后期主线预告(v4+)

- **Go LLM 网关**(对标 litellm 简化版):统一多 LLM 路由、key 管理、缓存、限流
- **Go API 网关**:统一 ERP/外部 API 调用、鉴权、协议转换
- **ERP agent**:业务流程自动化(订单/库存/财务等场景)
