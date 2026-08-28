# 聊天路由:接收用户消息,调 LLM,维护多轮上下文

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from llm.factory import get_llm_client
from store.session_store import get_session_store

chat_router = APIRouter(prefix="/chat", tags=["聊天"])


class SendRequest(BaseModel):
    """POST /chat/send 请求体"""

    session_id: str | None = None  # 首次对话可不传,服务端自动创建
    message: str


@chat_router.post("/send")
async def send_chat_message(req: SendRequest):
    store = get_session_store()
    session = store.get(req.session_id) if req.session_id else None
    if session is None:
        session = store.create()

    session.append("user", req.message)
    try:
        reply = await get_llm_client().chat(session.messages)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM 调用失败: {e}")
    session.append("assistant", reply)

    return {"session_id": session.session_id, "reply": reply}
