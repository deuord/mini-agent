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

        answer = await _render(session, run_turn(session, user_input))
        while answer is not None:
            answer = await _render(session, resume_turn(session, answer))


async def _render(session, events):
    """消费一段事件流;遇确认请求就问一句、存答案后退出(让生成器关闭释放锁,再由 repl 调 resume_turn)

    不能在 _render 里递归调 resume_turn:run_turn 持着 session.lock 在 yield 上挂起,
    resume_turn 也要拿同一把锁 → 死锁。必须先 aclose 掉 run_turn(释放锁),再单独调 resume_turn。
    """
    pending = None
    try:
        async for ev in events:
            if ev.type == "chunk":
                print(ev.content, end="", flush=True)
            elif ev.type == "tool_call":
                print(f"\n[调用工具 #{ev.step}] {ev.name} 参数={json.dumps(ev.args, ensure_ascii=False)}")
            elif ev.type == "confirm_request":
                print(f"\n执行命令? {ev.cmd} (cwd={ev.cwd})")
                pending = {
                    "tool_call_id": ev.tool_call_id,
                    "kind": "confirm",
                    "approve": _ask_yn(),
                }
                break  # 退出循环 → finally 里 aclose 生成器(释放锁)→ repl 里再调 resume_turn
            elif ev.type == "done":
                print("\n")
            elif ev.type == "error":
                print(f"错误：{ev.message}\n")
    finally:
        await events.aclose()
    return pending


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
