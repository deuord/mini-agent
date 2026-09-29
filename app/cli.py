# app/cli.py — v1.0 入口(先跑通启动)
import asyncio
import json
from app.agent.runner import run_turn, resume_turn
from app.store.session_store import SessionStore


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

        await _render(session, run_turn(session, user_input))


async def _render(session, events):
    """消费一段事件流;遇确认请求就问一句、再起一段续跑(一问一答,不挂起连接)"""
    async for ev in events:
        if ev.type == "chunk":
            print(ev.content, end="", flush=True)
        elif ev.type == "tool_call":
            print(f"\n[调用工具 #{ev.step}] {ev.name} 参数={json.dumps(ev.args, ensure_ascii=False)}")
        elif ev.type == "confirm_request":
            print(f"\n执行命令? {ev.cmd} (cwd={ev.cwd})")
            answer = {
                "tool_call_id": ev.tool_call_id,
                "kind": "confirm",
                "approve": _ask_yn(),
            }
            await _render(session, resume_turn(session, answer))
        elif ev.type == "done":
            print("\n")
        elif ev.type == "error":
            print(f"错误：{ev.message}\n")


def _ask_yn() -> bool:
    while True:
        try:
            line = input("y/n: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print()
            return False
        if line in ("y", "n"):  # 只认 y/n 忽略大小写,其他输入重问(plan 解析规则)
            return line == "y"
        print("(只认 y/n,重新输入)", flush=True)


def main():
    asyncio.run(repl())


if __name__ == "__main__":
    main()
