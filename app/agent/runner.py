from typing import AsyncIterator

from ..llm.openai_compat import chat_stream
from .events import ChunkEvent, DoneEvent, ErrorEvent
from .session import Session


async def run_turn(
    session: Session, user_text: str, cfg=None
) -> AsyncIterator[ChunkEvent | DoneEvent | ErrorEvent]:
    """追加用户消息 → 流式调 LLM → yield 事件 → 完整回复落回 session

    传输无关：不 print、不碰 WS——CLI 和 WebSocket 都是它的消费者
    """
    session.append("user", user_text)  # 1.用户消息写进历史

    full_reply = ""
    try:
        # 2.用整个 session 历史调 LLM（记忆）
        async for delta in chat_stream(session.messages, cfg=cfg):
            full_reply += delta
            yield ChunkEvent(content=delta)  # 3.流式返回
    except Exception as e:
        # 4a.出错:撤掉刚才的 user 消息,保持历史"成对"
        session.messages.pop()
        yield ErrorEvent(message=str(e))
        return
    finally:
        # 4b.无论正常结束还是消费者提前退出,收到的回复都要落回历史
        if full_reply and session.messages[-1]["role"] == "user":
            session.append("assistant", full_reply)
    yield DoneEvent()

   