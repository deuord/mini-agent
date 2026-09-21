from fastapi import APIRouter,WebSocket,WebSocketDisconnect
from app.agent.runner import run_turn
from app.agent.store import store

router = APIRouter()

@router.websocket("/api/chat/stream")
async def chat_stream(ws:WebSocket):
    await ws.accept()
    try:
        while True:
            data = await ws.receive_json()  #收前端消息
            print(f"[WS]收到：{data}")
            if data.get("type") != "user_message":
                continue
            session_id = data.get("session_id")
            content = data.get("content","")

            session = store.get(session_id) if session_id else None
            if session is None:
                session = store.create()
                await ws.send_json({"type":"session","session_id":session.session_id})

                #调同一个runner，事件转json推回
            async for ev in run_turn(session,content):
                print(f"[WS] 事件: {ev.type}")     # ← 看事件有没有产生
                await ws.send_json({
                    "type":ev.type,
                    "session_id":session.session_id,
                    "content":getattr(ev,"content",""),
                    "message":getattr(ev,"message",""),
                })
    except WebSocketDisconnect:
        pass
    except Exception as e:                          # ← 加上这个！别吞异常
        print(f"[WS] 异常: {type(e).__name__}: {e}")
        raise