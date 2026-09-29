import time

from app.agent.session import Session

SESSION_TTL_SECONDS = 3600*6 #6小时没活动自动过期

class SessionStore:
    #会话仓库 dict+TTl （go里面就是map+过期检查）
    def __init__(self,ttl:int = SESSION_TTL_SECONDS):
        self.sessions:dict[str,Session] = {}
        self.ttl = ttl

    def create(self) -> Session:
        #创建一个新会话
        s = Session()
        self.sessions[s.session_id] = s
        return s

    def get(self,session_id:str) -> Session|None:
        s= self.sessions.get(session_id)
        if s is None:
            return None
        if time.time() - s.update_time > self.ttl:
            del self.sessions[session_id]
            return None
        return s

    def append(self,session_id:str,role:str,content:str) -> Session|None:
        s = self.get(session_id)
        if s is None:
            return None
        s.append(role,content)
        return s

    def list_sessions(self)->list[dict]:
        """列出所有活跃会话（摘要）;遍历时顺手回收已过期的"""
        out=[]
        for sid in list(self.sessions):   #先取 key 快照,避免遍历中改 dict
            s = self.get(sid)             #get 内部会删掉过期会话
            if s is None:
                continue
            last = (s.messages[-1].get("content") or "")[:30] if s.messages else ""
            out.append({
                "session_id":s.session_id,
                "messages":len(s.messages),
                "preview":last,
            })
        return out

    def history(self,session_id:str) -> dict|None:
        """取某会话的现场:完整历史 + 待回答的断点(断线重连后据此恢复弹框,见 plan 2.5)"""
        s = self.get(session_id)
        if s is None:
            return None
        return {"messages":s.messages,"pending":s.pending}
