# test_v12.py — v1.2 综合验收
import asyncio, json, urllib.request, websockets

WS_URL = "ws://127.0.0.1:8000/api/chat/stream"
API    = "http://127.0.0.1:8000/api"

async def ask(ws, text, sid=None):
    """发一条消息，返回 (session_id, 完整回复)"""
    payload = {"type": "user_message", "content": text}
    if sid:
        payload["session_id"] = sid
    await ws.send(json.dumps(payload))
    reply, new_sid = "", sid
    while True:
        m = json.loads(await ws.recv())
        new_sid = m.get("session_id") or new_sid
        if m["type"] == "chunk":
            reply += m["content"]
        elif m["type"] == "done":
            break
    return new_sid, reply

async def main():
    async with websockets.connect(WS_URL) as ws:
        # ① 建两个独立会话
        sid_a, _ = await ask(ws, "我最喜欢的数字是7")
        sid_b, _ = await ask(ws, "我最喜欢的颜色是蓝色")
        print(f"① 多会话并存: A={sid_a[:8]}  B={sid_b[:8]}  "
              f"[{'通过' if sid_a != sid_b else '失败'}]")

        # ② 切回 A 追问（验证记忆没串）
        _, reply = await ask(ws, "我刚才说的数字是几？", sid_a)
        print(f"② 切换+记忆: 回答={reply[:30]}  "
              f"[{'通过' if '7' in reply else '失败'}]")

    # ③ 历史拉取
    lst = json.loads(urllib.request.urlopen(f"{API}/sessions").read())
    n = len(lst["sessions"])
    print(f"③ REST 会话列表: {n} 个  [{'通过' if n >= 2 else '失败'}]")

    hist = json.loads(urllib.request.urlopen(f"{API}/sessions/{sid_a}").read())
    roles = [m["role"] for m in hist["messages"]]
    print(f"   历史角色序列: {roles}  "
          f"[{'通过' if 'assistant' in roles and 'user' in roles else '失败'}]")

asyncio.run(main())