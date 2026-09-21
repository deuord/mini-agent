from fastapi import APIRouter,HTTPException
from app.agent.store import store

router = APIRouter()

@router.get("/api/sessions")
async def list_sessions():
    return {"sessions":store.list_sessions()}

@router.get("/api/sessions/{session_id}")
async def get_history(session_id:str):
    msgs = store.history(session_id)
    if msgs is None:
        raise HTTPException(status_code=404,detail="会话不存在或者已过期")
    return{"session_id":session_id,"messages":msgs}