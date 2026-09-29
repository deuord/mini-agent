from fastapi import APIRouter,HTTPException
from app.agent.store import store

router = APIRouter()

@router.get("/api/sessions")
async def list_sessions():
    return {"sessions":store.list_sessions()}

@router.get("/api/sessions/{session_id}")
async def get_history(session_id:str):
    snap = store.history(session_id)
    if snap is None:
        raise HTTPException(status_code=404,detail="会话不存在或者已过期")
    # pending:有待确认/待回答的断点就带出来,前端重连后据此重新弹框(见 plan 2.5)
    return{"session_id":session_id,**snap}