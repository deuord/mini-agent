import asyncio
import json
import websockets


async def main():
    async with websockets.connect("ws://127.0.0.1:8000/api/chat/stream") as ws:
        sid = None

        # 第一条
        print(">>> 我最喜欢的数字是7")
        await ws.send(json.dumps({"type": "user_message", "content": "我最喜欢的数字是7"}))
        while True:
            msg = json.loads(await ws.recv())
            if msg["type"] == "session":
                sid = msg["session_id"]
                print(f'[会话 {sid}]')
            elif msg["type"] == "chunk":
                print(msg["content"], end="", flush=True)
            elif msg["type"] == "done":
                print("\n[done]")
                break
            elif msg["type"] == "error":
                print(f'\n[error] {msg["message"]}')
                break

        # 第二条（带 session_id 追问，测多轮记忆）
        print("\n>>> 我刚才说的数字是几？")
        await ws.send(json.dumps({"type": "user_message", "content": "我刚才说的数字是几？", "session_id": sid}))
        while True:
            msg = json.loads(await ws.recv())
            if msg["type"] == "chunk":
                print(msg["content"], end="", flush=True)
            elif msg["type"] == "done":
                print("\n[done]")
                break
            elif msg["type"] == "error":
                print(f'\n[error] {msg["message"]}')
                break


asyncio.run(main())
