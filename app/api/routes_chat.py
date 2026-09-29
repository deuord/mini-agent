# app/api/routes_chat.py — HTTP + SSE:发消息/续答都是普通 POST,流用 text/event-stream 推回去
# 确认/提问不走长连接:runner 遇断点结束本段,前端再发一次 POST /api/chat/resume 续跑(见 plan 2.5)
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.agent.runner import run_turn, resume_turn
from app.agent.store import store

router = APIRouter()

# 关掉中间层缓冲,否则流会被攒着一起吐(Nginx / 部分网关)
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


class ChatRequest(BaseModel):
    session_id: str | None = None
    content: str


class ResumeRequest(BaseModel):
    session_id: str
    tool_call_id: str   # 关联键:对应哪个断点(见 plan 2.5)
    kind: str           # confirm
    approve: bool = False


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _payload(ev, session_id: str) -> dict:
    """事件 → SSE 的 data 字段(字段随 event 类型而定,见 plan 1.5)"""
    out = {"type": ev.type, "session_id": session_id}
    if ev.type == "chunk":
        out["content"] = ev.content
    elif ev.type == "tool_call":
        out["step"] = ev.step
        out["name"] = ev.name
        out["args"] = ev.args
        out["result"] = ev.result
    elif ev.type == "confirm_request":
        out["step"] = ev.step
        out["tool_call_id"] = ev.tool_call_id
        out["cmd"] = ev.cmd
        out["cwd"] = ev.cwd
    elif ev.type == "error":
        out["message"] = ev.message
    return out


def _stream(session, events) -> StreamingResponse:
    async def gen():
        async for ev in events:
            yield _sse(_payload(ev, session.session_id))

    return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/api/chat")
async def chat(req: ChatRequest):
    """发一条用户消息;带 session_id 就续用该会话,取不到就新建(先推一条 session 事件)"""
    session = store.get(req.session_id) if req.session_id else None
    is_new = session is None
    if is_new:
        session = store.create()

    async def gen():
        if is_new:
            yield _sse({"type": "session", "session_id": session.session_id})
        async for ev in run_turn(session, req.content):
            yield _sse(_payload(ev, session.session_id))

    return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/api/chat/resume")
async def chat_resume(req: ResumeRequest):
    """提交对断点的回答(确认/后续 v2.2 的提问),同一条流继续推"""
    session = store.get(req.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在或者已过期")
    answer = {
        "tool_call_id": req.tool_call_id,
        "kind": req.kind,
        "approve": req.approve,
    }
    return _stream(session, resume_turn(session, answer))
