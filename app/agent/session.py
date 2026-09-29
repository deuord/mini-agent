import asyncio
import time
import uuid

class Session:
    #一个会话 = 一串消息
    def __init__(self,session_id:str|None=None):
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.messages:list[dict] = []
        # 回合断点:等确认/等回答时非空(见 plan 2.5);一个会话同时只有一个活跃回合,所以挂会话上就够
        self.pending:dict|None = None
        # 同一会话同时只跑一个回合:并发的第二个请求在此排队(不是报错),否则两个回合会交错写 messages、
        # 且后写的断点会覆盖前一个。锁同时保证下面 run_turn 里 start_len 回滚不会误删别人的消息
        self.lock = asyncio.Lock()
        self.create_time = time.time()
        self.update_time = time.time()


    def append(self,role:str,content:str):
        self.messages.append({"role":role,"content":content})
        self.update_time = time.time()

# SessionStore(存储/过期逻辑)在 app/store/session_store.py
