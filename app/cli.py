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
        async for ev in run_turn(session, user_input, confirm=_confirm):
            if ev.type == "chunk":
                print(ev.content, end="", flush=True)
            elif ev.type == "tool_call":
                print(f"\n[调用工具 #{ev.step}] {ev.name} 参数={json.dumps(ev.args, ensure_ascii=False)}")
            elif ev.type == "done":
                print("\n")
            elif ev.type == "error":
                print(f"错误：{ev.message}\n")



    def main():
        async def _confirm(cmd: str, cwd: str) -> bool:
        # v2.1 过渡版:直接 input。v2.2 任务3 建统一输入通道后,把这里换成 wait_line,别的不动
                while True:
                    line = input(f"执行命令? {cmd} (cwd={cwd}) [y/n]: ").strip().lower()
                    if line in ("y", "n"):  # 只认 y/n 忽略大小写,其他输入重问(plan 解析规则)
                        return line == "y"
                    print("(只认 y/n,重新输入)", flush=True)
                asyncio.run(repl())


if __name__ == "__main__":
    main()
