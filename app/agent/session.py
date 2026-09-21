import time
import uuid

SESSSION_TTL_SECONDS = 3600*6 #6小时没活动自动过期

class Session:
    #一个会话 = 一串消息
    def __init__(self,session_id:str|None=None):
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.messages:list[dict] = []
        self.create_time = time.time()
        self.update_time = time.time()


    def append(self,role:str,content:str):
        self.messages.append({"role":role,"content":content})
        self.update_time = time.time()

class SessionStore:
    #会话仓库 dict+TTl （go里面就是map+过期检查）
    def __init__(self,ttl:int = SESSSION_TTL_SECONDS):
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
        """列出所有活跃会话（摘要）"""
        now = time.time()
        out=[]
        for s in self.sessions.values():
            if now - s.update_time > self.ttl:
                continue
            last = s.messages[-1]["content"][:30] if s.messages else ""
            out.append({
                "session_id":s.session_id,
                "messages":len(s.messages),
                "preview":last,
            })
        return out

    def history(self,session_id:str) -> list[dict]|None:
        """取某会话的完整历史"""
        s = self.get(session_id)
        return s.messages if s else None
