from typing import AsyncIterator
import json
import time
from ..llm.openai_compat import chat_stream
from ..obs import log_event
from .events import ChunkEvent, DoneEvent, ErrorEvent,ToolCallEvent
from .session import Session
from ..tools.calls import buffer_tool_calls,parse_tool_calls
from ..tools.file import register as register_file
from ..tools.registry import ToolRegistry

_registry = ToolRegistry()
register_file(_registry)  #模块级注册一次：tools=definitions随请求发出

MAX_STEPS = 6 #ReAct 轮数上限，防模型连续调工具失控

async def run_turn(
    session: Session, user_text: str, cfg=None
) -> AsyncIterator[ChunkEvent | DoneEvent | ErrorEvent | ToolCallEvent]:
    """追加用户消息 → 流式调 LLM → yield 事件 → 完整回复落回 session

    传输无关：不 print、不碰 WS——CLI 和 WebSocket 都是它的消费者
    """
    start_len = len(session.messages) #本轮起点：出错删到这里，历史回到上一轮的成对状态
    t0 = time.monotonic()
    err = None
    steps = 0
    n_tools = 0
    n_tools_ok = 0
    session.append("user", user_text)  # 1.用户消息写进历史

    full_reply = ""
    try:
        for step in range(MAX_STEPS):
            steps = step + 1
            full_reply = "" #每轮只累计本轮文本
            tool_calls_buf: dict[int, dict[str, str]] = {} #每轮清空工具调用缓存

            
        # 2.用整个 session 历史调 LLM（记忆）,tools随请求发出
            async for delta in chat_stream(session.messages, cfg=cfg,tools=_registry.definitions):
                if delta.content: # 正文文字,逐段送给界面显示
                    full_reply += delta.content
                    yield ChunkEvent(content=delta.content)
                if delta.tool_calls: # 模型要调工具,参数分片陆续到达,先累积进 tool_calls_buf
                    buffer_tool_calls(tool_calls_buf,delta.tool_calls)
            if not tool_calls_buf:
                #模型不再调工具 = 给出最终回答、本轮结束
                if full_reply:
                    session.append("assistant", full_reply)
                yield DoneEvent()
                return

            calls = parse_tool_calls(tool_calls_buf)
            #assistant的content+tool_calls必须写在同一条信息，否则模型下一轮看不到自己本轮说的话、上下文永久丢失
            #arguments 写回要转回 JSON 字符串(协议要求),parse 时已 loads 成 dict
            session.messages.append({
                "role":"assistant",
                "content":full_reply or None,
                "tool_calls":[{
                    "id":c["id"],
                    "type":"function",
                    "function":{
                        "name":c["name"],
                        "arguments":json.dumps(c["arguments"], ensure_ascii=False),
                    }
                }
                for c in calls
                ],
            })
            for c in calls:
                n_tools += 1
                try:
                    result = _registry.execute(c["name"], c["arguments"])
                    n_tools_ok += 1
                except Exception as e:
                     # 业务执行失败(文件不存在等)喂回给模型,让它自己改路径或向用户解释
                    result = f"工具执行失败: {e}"
                # tool 消息必须带 tool_call_id,漏了直接 API 400(plan 第二坑)
                session.messages.append({
                    "role":"tool",
                    "content":str(result),
                    "tool_call_id":c["id"],
                })
                yield ToolCallEvent(step=step+1,name=c["name"],args=c["arguments"],result=str(result))

        #for走完还没return = MAX_STEPS轮都在调工具
        err = "max_steps"
        yield ErrorEvent(message=f"执行步数超限：连续{MAX_STEPS}轮都在调工具")
    except Exception as e:
        del session.messages[start_len:] #删掉本轮全部消息（包含 user 消息和 tool 消息）
        full_reply = "" # 防止 finally 把本轮残留文本错写到上一轮
        err = str(e)
        yield ErrorEvent(message=str(e))
        return
    finally:
        # 回合埋点:一次输入到结束的耗时/步数/工具成败/错误
        log_event(
            "turn",
            session_id=session.session_id,
            seconds=round(time.monotonic() - t0, 2),
            steps=steps,
            tools=n_tools,
            tools_ok=n_tools_ok,
            error=err,
        )
        # 4b.消费者中途退出(WS 断开等)时,把已流出的文本补写回历史,不丢半截回复
        if full_reply and session.messages and session.messages[-1]["role"] == "user":
            session.append("assistant", full_reply)


   