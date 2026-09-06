# mini-agent 开发方案

## 一、项目定位

桌面本地任务助手。打字下指令 → LLM 理解 → 自主规划步骤 → 调用工具执行(操作文件、跑命令、处理文档)。

分三个版本迭代,第一版只做对话,第二版加文件+命令,第三版补 ReAct+文档处理打通三个验收场景。后期主线(Go LLM 网关 / ERP agent)另起版本规划,不在本方案展开。

## 二、版本路线总览

| 版本 | 主题 | 验收场景 |
|---|---|---|
| v1 | 对话基座 | 多轮对话,流式回复,session 连续 |
| v2 | 文件 + 命令 | 对话里让 agent 读写文件、跑命令 |
| v3 | ReAct + 文档处理 | 整理文件夹 / 统计CSV月度总额 / md转HTML |
| 后期 | Go 网关 / ERP | 单独规划 |

---

# 第一版:对话基座

## v1.1 目标与切片路线

最小可用对话助手:打字下指令 → DeepSeek 流式回复 → 保持上下文。文件/命令/ReAct/文档都暂不做。

**核心原则:先练"流式 + 记忆"两个基本功,会话列表和 UI 是壳,壳最后套。**

切片顺序:

| 切片 | 内容 | 验收 |
|---|---|---|
| v1.0 | CLI 流式 + 多轮记忆(**不碰 Web**) | 终端连续对话,追问"刚才我说了什么"能答上 |
| v1.1 | FastAPI + WebSocket,把 CLI 的逻辑搬上 Web | WS 连上,流式多轮对话 |
| v1.2 | 会话管理:列表 / 历史 / 新增(CRUD) | 多会话并存、可切换 |
| v1.3 | 前端 UI(仿 trae-work/codex) | 并入 v2,协议长全后再画 |

v1.3 不单独排期:v2 要加命令确认弹窗、v3 要加工具调用过程展示,现在画 UI 必然返工,等协议长全后和 v2 前端一起做。

**架构纪律(CLI 先行的目的):runner 与传输层无关。** runner 只产出事件流(`AsyncIterator[Event]`),CLI 和 WebSocket 都是它的 renderer:

- runner:追加用户消息 → 调 LLM → `yield` 事件(chunk / done / error;v2 扩 confirm,v3 扩 tool_call / plan)
- CLI renderer(v1.0):消费事件,打印终端
- WS renderer(v1.1):消费事件,序列化成 JSON 推送
- v2 的命令确认在两种 renderer 下分别是 `input("[y/N]")` 和 confirm 消息往返,runner 代码不动

## v1.2 技术栈

- **语言**:Python 3.12+
- **LLM**:OpenAI 兼容协议调 DeepSeek
- **CLI**(v1.0):标准库 asyncio;`rich` 可选(流式 Markdown 渲染,不上也行)
- **后端**(v1.1 引入):FastAPI / WebSocket。走 WS 不走 SSE——v2 确认流程要服务器主动推 + 客户端回,SSE 单向凑不了
- **前端**(v1.3,随 v2 做):Web,仿 trae-work/codex 样式(独立生成,不在本方案展开)
- **依赖管理**:`uv`

## v1.3 目录结构

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
│   │   ├── base.py           # LLMClient 抽象
│   │   ├── openai_compat.py  # OpenAI 兼容实现(DeepSeek 走这个)
│   │   └── factory.py        # 按 yaml 配置生成 client
│   ├── config/
│   │   ├── __init__.py
│   │   ├── loader.py         # 加载 models.yaml + env 覆写
│   │   └── schema.py         # pydantic 校验
│   └── store/
│       ├── __init__.py
│       └── session_store.py  # 内存 dict(v2 加 SQLite)
├── configs/
│   └── models.yaml
├── docs/plan.md
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

v1.3 新增 `web/`(前端,随 v2 一起做)。

## v1.4 模块职责

- **config/**:读 `models.yaml`,pydantic 校验,env 覆写 key,`get_settings()` 单例
- **llm/**:`LLMClient` 抽象(`chat(messages, model, stream) -> AsyncIterator[Chunk]`),OpenAI 兼容实现,factory 路由
- **agent/events.py**:事件数据类型(chunk / done / error),runner 与 renderer 之间的唯一契约;v2 扩 confirm,v3 扩 tool_call / plan
- **agent/session.py**:`Session`(messages, session_id, created_at),`SessionStore` 内存 dict + TTL
- **agent/runner.py**:**传输无关**。追加用户消息 → 调 LLM → 流式 yield 事件 → assistant 完整回复落回 session。代码里不允许出现 `print` / websocket 调用(v3 在此改 ReAct 循环)
- **cli.py**(v1.0):stdin 读入 → 调 runner → 消费事件打印(`flush=True` 或 rich)
- **api/routes_chat.py**(v1.1):WS 收消息 → 调**同一个 runner** → 事件转 JSON 推回

## v1.5 关键数据结构

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

### 事件协议(runner → renderer)

v1 三种事件(v2 扩 confirm,v3 扩 tool_call / plan):

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

## v1.6 任务清单

### v1.0:CLI 流式 + 多轮(本周,不碰 Web)

- [x] 1. 脚手架:`uv init` + 目录结构,`python -m app.cli` 能启动
- [x] 2. 配置:`models.yaml` + pydantic 校验 + env 覆写(schema.py Setting/ModelConfig + get_model 内 env 覆写;openai 钉 1.x,3.x 的 httpx2/httpcore2 流关闭有 bug)
- [ ] 3. LLM 客户端:抽象 + OpenAI 兼容实现(DeepSeek),流式 `AsyncIterator[Chunk]`(流式实现已有 chat_stream,抽象留到 v1.1 一起收)
- [x] 4. Session:Session / SessionStore 内存版,创建 / 读取 / 追加
- [x] 5. events + runner:收消息 → 调 LLM → yield chunk/done/error,完整回复落回 session
- [x] 6. CLI 渲染循环:stdin 读入 → runner → 打印事件(runner 里不写 print)
- [x] 7. 联调验收:终端多轮对话连续

### v1.1:FastAPI + WebSocket

- [ ] 1. FastAPI 脚手架:hello world + lifespan + 挂载路由
- [ ] 2. WebSocket 路由:收 user_message → 调同一个 runner → 事件转 JSON 推回
- [ ] 3. 健康检查:`GET /api/health` 返回 LLM 配置可用性
- [ ] 4. 验收:wscat 或简易测试页连 WS,流式多轮对话

### v1.2:会话管理(CRUD)

- [ ] 1. SessionStore 加 list / get / create
- [ ] 2. WS 支持指定 / 新建 session_id(必要时加 POST 建会话端点)
- [ ] 3. 验收:多会话并存,历史可拉取、可切换

### v1.3:前端 UI(并入 v2)

- [ ] 1. 仿 trae-work/codex 对话 UI,连 WS 渲染流式 token
- [ ] 2. 与 v2 文件面板、命令确认弹窗一并设计实现

## v1.7 验收

- **v1.0(核心验收,CLI 即可)**:终端启动 → 输入"你好" → 流式回复逐字出现 → 追问"刚才我说了什么" → 能答上
- **v1.1**:wscat / 测试页走 WS,同等多轮流式效果
- **v1.2**:能新建、切换、列出多个会话,历史消息不丢

---

# 第二版:文件 + 命令执行

## v2.1 目标

让 agent 能在对话里读写文件、跑命令(带确认)。ReAct 还不上,工具调用先靠 LLM 的 function calling 直连(单步调用,非循环)。

## v2.2 新增能力

### 文件工具
- `read_file(path) -> content`
- `write_file(path, content)`
- `edit_file(path, old_str, new_str)` — 精确字符串替换
- `list_recent_files(limit=20)` — SQLite 查询最近访问

### 命令执行
- `run_command(cmd, cwd)` — 执行前推前端确认请求,确认后执行
- 超时控制(默认 30s)
- 工作目录无限制,每次确认兜底

### 最近访问记录
- SQLite:`recent_files(id, path, op, accessed_at)`
- 每次 read/write/edit 自动写一条

## v2.3 目录新增

```
app/
├── tools/
│   ├── __init__.py
│   ├── registry.py            # 工具注册中心(v3 ReAct 也用这个)
│   ├── file.py                # read/write/edit/list_recent
│   └── shell.py               # run_command(带确认流)
├── store/
│   └── db.py                  # SQLite 连接 + 表初始化
```

## v2.4 SQLite Schema

```sql
CREATE TABLE recent_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL,
    op TEXT NOT NULL,           -- read / write / edit
    accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_recent_files_accessed ON recent_files(accessed_at DESC);
```

## v2.5 命令确认协议(WebSocket 新增)

后端 → 前端:
```json
{"type": "confirm_request", "session_id": "xxx", "cmd": "ls ~/Documents", "cwd": "/"}
```

前端 → 后端:
```json
{"type": "confirm_response", "session_id": "xxx", "approve": true}
```

确认后执行,结果走:
```json
{"type": "command_output", "session_id": "xxx", "stdout": "...", "stderr": "...", "exit_code": 0}
```

## v2.6 前端新增

- "我的文件"面板:列出最近访问文件,点击在线查看/编辑
- 命令确认弹窗:展示 cmd + cwd,确认/拒绝按钮

## v2.7 任务清单

- [ ] 1. SQLite 初始化:建表 + 连接池
- [ ] 2. 工具注册中心:统一 schema(name, description, parameters),转 OpenAI function 定义
- [ ] 3. 文件工具:read/write/edit/list_recent
- [ ] 4. 命令工具:run_command + 确认流 + 超时
- [ ] 5. WebSocket 扩展:confirm_request/response 协议
- [ ] 6. LLM function calling 接入:把 tools 注册给 DeepSeek,处理 tool_call
- [ ] 7. 前端:文件面板 + 命令确认弹窗
- [ ] 8. 联调验收:读文件 / 改文件 / 跑命令 三场景

## v2.8 验收

- 对话"读一下 /Users/xxx/a.md" → agent 调 read_file → 内容显示
- 对话"把 a.md 里 foo 改成 bar" → agent 调 edit_file → 文件已改
- 对话"跑一下 ls ~/Documents" → 弹确认 → 执行 → 输出显示

---

# 第三版:ReAct + 文档处理

## v3.1 目标

打通自主任务执行 + 文档处理,覆盖三个验收场景:整理文件夹、统计CSV月度总额、md转HTML。

## v3.2 新增能力

### ReAct 主循环
- `agent/runner.py` 改造:LLM 决策 → 调 tool → 观察结果 → 再决策 → 直到完成
- 任务规划 prompt 模板(系统提示引导先列步骤)
- 中间步骤实时推前端(可见思考过程)

### 文档处理工具
- `read_csv(path) -> rows` / `summary_csv(path, group_by_col, agg_col, agg_func)` — 月度总额走这个
- `read_excel(path)` / `write_excel(path, data)`
- `read_docx(path)` / `write_docx(path, content)`
- md→HTML:走 `markdown` 库,直接在 file 工具里加 `md_to_html(path)` → 写回 `xxx.html`

## v3.3 目录新增

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
│   ├── react.py               # ReAct 主循环
│   └── prompts.py             # 规划系统提示模板
```

## v3.4 ReAct 循环伪代码

```
loop:
    response = llm.chat(messages, tools=registered_tools)
    if response.tool_calls:
        for call in response.tool_calls:
            result = registry.execute(call.name, call.args)
            push_to_frontend({type: "tool_call", name, args, result})
            messages.append(tool_result)
    else:
        push_to_frontend({type: "chunk", content: response.content})
        if response.done: break
```

## v3.5 WebSocket 新增消息

```json
{"type": "tool_call", "session_id": "xxx", "name": "read_csv", "args": {...}, "result": "..."}
{"type": "plan", "session_id": "xxx", "steps": ["...", "..."]}
```

## v3.6 任务清单

- [ ] 1. ReAct 主循环:工具调度 + 多轮决策
- [ ] 2. 规划 prompt 模板:引导 LLM 先列步骤再执行
- [ ] 3. CSV 工具:read + summary(按月聚合)
- [ ] 4. Excel 工具:read + write
- [ ] 5. Word 工具:read + write
- [ ] 6. md_to_html 工具:`markdown` 库渲染,写回原目录
- [ ] 7. 前端:展示 plan + tool_call 中间步骤
- [ ] 8. 验收场景串联:三场景跑通

## v3.7 验收

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
