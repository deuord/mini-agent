# ADR-0003 客户端中断后保留已生成的部分，不回滚

日期：2026-09-29
状态：已接受（修正 plan 2.5 原「本段回滚」设计）

## 决策：断流 / 取消时不回滚，把已生成的部分落盘

**背景**：SSE 版下客户端随时可能中断（用户点停止、关页面、切标签、网络断）。原 plan 2.5 写的是「断在流式输出 / 工具执行中 → 本段回滚，用户重发这条消息」，靠 `run_turn` 的 `except` 里 `del session.messages[start_len:]` 实现。

实测发现两件事：

1. **那个回滚从来没生效过**：客户端断流 = generator 被外部关闭，抛出的是 `GeneratorExit`（继承 `BaseException`），**绕过 `except Exception`**，所以 `del` 根本没执行。断流后的历史里只剩一条没人回复的 user 消息，半截回复被丢弃。
2. **回滚本身就不是对的方向**（见下）。

**决策**：不回滚。

- **断在流式输出中**：user 消息保留，那半截已生成、已显示给用户的正文落盘成一条 `assistant`（尾部加「（回复已中断）」标记）
- **断在工具执行中**：已执行完的 tool 结果保留；还没拿到结果的那条 call 补一条占位 `tool` 结果（`"（中断，未执行）"`），保证 `assistant(tool_calls)` 有配对，否则下次请求直接 400

**理由（业界一致，不是我们自己拍的）**：

- 第一原则：**用户屏幕上已经看到的内容，必须和历史一致**。回滚会让「他说过的话、他看过的回答」凭空消失，读起来就是 bug
- Frontend Patterns（Stop Generation 模式）：*keep the tokens that already arrived*——中止时把消息标记为 `stopped`，保留半截内容
- Prasad Subrahmanya（streaming chat from scratch）：*Persist the partial. A cancelled turn still happened... If you throw it away, the reader hits stop and watches their conversation lose a turn, which reads as a bug.*
- techfordev：*Persist the partial assistant snapshot... Without this step, the assistant message disappears from the conversation when the stream closes.*
- LangChain 中断处理：累积的 partial 要 persist，不要静默丢弃

**代价**：

- 半截回复永久留在上下文里，下一轮 LLM 会看到。用户中断后改问别的，模型可能受它干扰。可接受——真实对话本来就有「说一半被打断」，而且我们加了「（回复已中断）」标记，模型能判断这不是完整回答
- 若中断发生在工具已执行之后，历史里会保留「工具已执行」的记录。这是对的（文件确实改了）；反过来，回滚会让重发后的模型重复执行同一个写操作——**回滚的代价比保留更大**

## 附带修正

- plan 2.5 原「断在其他位置 → 本段回滚」一条，替换为「断在流式输出中」「断在工具执行中」两条（均不回滚）
- `run_turn` 的 `except` 分支不再删消息，只记录错误；`_react` 的 `finally` 里补写半截正文
