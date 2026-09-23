# app/cli.py — v1.0 入口(先跑通启动)
import asyncio
from app.agent.runner import run_turn
from app.store.session_store import SessionStore
import json


async def repl():
    store = SessionStore()
    session = store.create()
    print("mini-agent v1.0 — 输入 exit 退出\n")

    while True:
        try:
            user_input = input("用户：").strip()
        except (KeyboardInterrupt, EOFError):
            break
        if user_input == "exit":
            print("退出")
            break

        if not user_input:
            continue

        print("助手：", end="", flush=True)
        async for ev in run_turn(session, user_input):
            if ev.type == "chunk":
                print(ev.content, end="", flush=True)
            elif ev.type == "tool_call":
                print(f"\n[调用工具 #{ev.step}] {ev.name} 参数={json.dumps(ev.args, ensure_ascii=False)}")
            elif ev.type == "done":
                print("\n")
            elif ev.type == "error":
                print(f"错误：{ev.message}\n")



def main():
    asyncio.run(repl())


if __name__ == "__main__":
    main()
