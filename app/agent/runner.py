from typing import AsyncIterator
from contextlib import aclosing
import asyncio
import json
import time
from ..config.loader import load_models
from ..llm.openai_compat import chat_stream
from ..obs import log_event
from .events import ChunkEvent, ConfirmRequestEvent, DoneEvent, ErrorEvent, ToolCallEvent, AskUserEvent
from .session import Session
from ..tools.calls import buffer_tool_calls, parse_tool_calls
from ..tools.file import register as register_file
from ..tools.command import register as register_command, is_auto_approved
from ..tools.registry import ToolRegistry
from ..tools.ask_user import register as register_ask_user

_registry = ToolRegistry()
register_file(_registry)  #模块级注册一次：tools=definitions随请求发出
register_command(_registry)  # 命令工具:执行前由 runner 存断点等用户确认(见 plan 2.5)
register_ask_user(_registry)  # 澄清提问工具:向用户提问以澄清需求(见 plan 2.6)

Event = ChunkEvent | DoneEvent | ErrorEvent | ToolCallEvent | ConfirmRequestEvent | AskUserEvent

ASK_USER_TIMEOUT_SECONDS = 300   # 澄清提问默认超时(仅 Web/SSE 路径生效,CLI 不超时)

def _tool_msg(tool_call_id:str,content) ->dict:
    # tool 结果必须带 tool_call_id,漏了直接 API 400(plan 第二坑)
    return {"role":"tool","content":str(content),"tool_call_id":tool_call_id}

def _assistant_msg(content:str,calls:list[dict]) ->dict:
    #assistant的content+tool_calls必须写在同一条信息，否则模型下一轮看不到自己本轮说的话、上下文永久丢失
    # arguments 写回要转回 JSON 字符串(协议要求),parse 时已 loads 成 dict
    return {
        "role":"assistant",
        "content":content or None,
        "tool_calls":[{
            "id":c["id"],
            "type":"function",
            "function":{
                "name":c["name"],
                "arguments":json.dumps(c["arguments"],ensure_ascii=False),
            },
        }
        for c in calls],
    }

async def _execute(c:dict) ->tuple[str,bool]:
    """跑一个普通工具,返回(结果文本,是否成功);业务失败喂回模型让它自纠(文件不存在等)

    丢线程池执行:工具都是同步阻塞的(run_command 的 subprocess.run 能跑几十秒),
    直接在协程里调会把事件循环卡住,期间所有请求(含 /api/health)全部停摆
    """
    try:
        return str(await asyncio.to_thread(_registry.execute,c["name"],c["arguments"])),True
    except Exception as e:
        return f"工具执行失败: {e}",False

async def _resolve_answer(session:Session,p:dict,answer:dict) ->tuple[str,bool]:
    """把对断点的回答翻译成 tool 结果;顺带记一次人机交互埋点(等待时长+通过与否)"""
    kind = p["kind"]
    waited = round(time.time()-p["created_at"],1)

    if kind == "confirm":
        approved = answer.get("approve") is True
        log_event(
            "confirm",
            session_id=session.session_id,
            wait_seconds=waited,
            approved=approved,
        )
        if not approved:
            return "用户拒绝执行该命令", True
        return await _execute({"name": p["name"], "arguments": p["args"]})

    # kind == "ask_user":四态(answered / declined / cancelled / timeout)
    # 显式 status 一律信任:CLI 永远显式 answered(阻塞再久也不超时,ADR-0004 决策2);
    # Web 端过期后由前端发 timeout(ADR 决策4 自动续跑)。仅在 status 缺失时后端惰性兜底判过期
    status = answer.get("status")
    if status is None:
        expires = p.get("expires_at")
        status = "timeout" if (expires is not None and time.time() > expires) else "answered"
    log_event("ask_user", session_id=session.session_id, wait_seconds=waited, status=status)

    if status == "answered":
        return str(answer.get("answer", "")), True
    if status == "declined":
        return "用户拒绝回答此问题，请基于合理假设继续", True
    if status == "cancelled":
        return "用户取消了整个任务", True
    # timeout
    return f"用户超时未响应（已等待{ASK_USER_TIMEOUT_SECONDS//60}分钟），请基于合理假设继续，或中止任务等待用户回来", True


def _log_turn(session:Session,t0:float,stats:dict,err:str|None) ->None:
    # 回合埋点:一次输入到结束的耗时/步数/工具成败/错误(断点恢复会分多段,每段各记一条)
    log_event(
        "turn",
        session_id=session.session_id,
        seconds=round(time.monotonic()-t0,2),
        steps=stats["steps"],
        tools=stats["tools"],
        tools_ok=stats["tools_ok"],
        error=err,
    )

def _new_stats(steps:int = 0) ->dict:
    return {"steps":steps,"tools":0,"tools_ok":0}

async def run_turn(
    session: Session, user_text: str, cfg=None
) -> AsyncIterator[Event]:
    """第一段:追加用户消息 → 跑 ReAct → yield 事件;遇"需要用户输入"就存断点结束本段

    传输无关：不 print、不碰任何传输层——CLI 和 HTTP/SSE 都是它的消费者
    """
    async with session.lock:  #同一会话串行:并发的第二个请求在此排队(锁持到本段流结束),见 plan 2.5
        if session.pending:  #上个断点没答完,不许插新消息
            yield ErrorEvent(message="还有待处理的确认/提问,请先回答")
            return
        t0 = time.monotonic()
        stats = _new_stats()
        err = None
        session.append("user", user_text)  # 1.用户消息写进历史
        try:
            # 必须用 aclosing 显式关掉 _react:async for 在 break/异常/外部关闭时不会自动关子生成器,
            # 那样它的 finally(保半截正文 + 补 tool 占位)就不会执行,只剩 GC 兜底=不确定
            async with aclosing(_react(session, cfg, step_start=1, stats=stats)) as gen:
                async for ev in gen:
                    yield ev
        except Exception as e:
            # 不回滚:用户消息和已经发生的部分都留在历史里(与断流路径一致,见 plan 2.5)。
            # 重发还是追问由用户决定,替他删消息反而会让历史"少一轮"
            err = str(e)
            yield ErrorEvent(message=str(e))
        finally:
            _log_turn(session, t0, stats, err)

async def resume_turn(
    session: Session, answer: dict, cfg=None
) -> AsyncIterator[Event]:
    """后续段:从 session.pending 续跑

    answer 必须带 tool_call_id 和 kind(关联键),迟到/重发/串题由它挡住
    """
    async with session.lock:  #与 run_turn 同一把锁:续跑期间不许别的请求插队(见 plan 2.5)
        p = session.pending
        if not p:
            yield ErrorEvent(message="没有待回答的断点")
            return
        if answer.get("tool_call_id") != p["tool_call_id"] or answer.get("kind") != p["kind"]:
            yield ErrorEvent(message="断点不匹配（可能已回答或已过期）")
            return
        session.pending = None
        t0 = time.monotonic()
        stats = _new_stats(steps=p["step"])
        err = None
        try:
            # 先补上断点那个 call 的结果，历史才成对；结果可能是命令输出或"用户拒绝"
            result, ok = await _resolve_answer(session, p, answer)
            stats["tools"] += 1
            if ok:
                stats["tools_ok"] += 1
            session.messages.append(_tool_msg(p["tool_call_id"], result))
            yield ToolCallEvent(step=p["step"], name=p["name"], args=p["args"], result=result)
            if answer.get("status") == "cancelled":
                # 用户取消整个任务:tool 结果已补(历史合法),直接收尾(见 plan 2.6)
                yield DoneEvent()
                return
            async with aclosing(_react(
                session, cfg, step_start=p["step"],
                calls=p["calls"], call_start=p["call_index"] + 1, stats=stats,
            )) as gen:
                async for ev in gen:
                    yield ev
        except Exception as e:
            # 不回滚:断点结果已落历史,回滚会留下悬空 tool_call(下次 400),错误让用户重发新消息
            err = str(e)
            yield ErrorEvent(message=str(e))
        finally:
            _log_turn(session, t0, stats, err)

async def _react(
    session:Session, cfg, step_start:int,
    calls:list[dict]|None = None, call_start:int = 0, stats:dict|None = None,
) ->AsyncIterator[Event]:
    """ReAct 主干(一段执行);calls/call_start 是断点恢复时复用本步 tool_calls 用"""
    stats = stats if stats is not None else _new_stats(step_start)
    max_steps = load_models().agent_max_steps  # 从配置读,默认 6;v4.1 放开时改这里默认值,或 models.yaml 加 agent 段
    unpaired = [c["id"] for c in calls[call_start:]] if calls else [] #本步还没落结果的 call
    half = "" #本轮已生成但还没进历史的正文;本段被掐断时由 finally 补写(见 plan 2.5)
    try:
        for step in range(step_start, max_steps + 1):
            stats["steps"] = step
            if calls is None: #正常轮:先让模型决策
                content = ""
                buf: dict[int, dict[str, str]] = {} #每轮清空工具调用缓存
                # 2.用整个 session 历史调 LLM（记忆）,tools随请求发出
                async for delta in chat_stream(session.messages, cfg=cfg,tools=_registry.definitions):
                    if delta.content: # 正文文字,逐段送给界面显示
                        content += delta.content
                        half = content #边生成边记:这会儿被掐断,已经显示出去的字不能丢
                        yield ChunkEvent(content=delta.content)
                    if delta.tool_calls: # 模型要调工具,参数分片陆续到达,先累积进 buf
                        buffer_tool_calls(buf,delta.tool_calls)
                half = "" #流式阶段收尾:content 下面要么落成 assistant 文本、要么随 tool_calls 一起落盘
                if not buf:
                    #模型不再调工具 = 给出最终回答、本段结束
                    if content:
                        session.append("assistant", content)
                    yield DoneEvent()
                    return
                calls = parse_tool_calls(buf)
                session.messages.append(_assistant_msg(content, calls))
                unpaired = [c["id"] for c in calls]
                call_start = 0
            for i in range(call_start, len(calls)): #执行本步的 tool_calls
                c = calls[i]
                if c["name"] == "ask_user":
                    # 澄清提问:与 confirm 同一套断点管道,只是 kind 不同、带超时
                    session.pending = {
                        "kind":"ask_user",
                        "step":step,
                        "call_index":i,
                        "calls":calls,
                        "tool_call_id":c["id"],
                        "name":c["name"],
                        "args":c["arguments"],
                        "created_at":time.time(),
                        "expires_at":time.time() + ASK_USER_TIMEOUT_SECONDS,  # 惰性判定,不用定时器
                    }
                    unpaired = []
                    yield AskUserEvent(
                        step=step,
                        tool_call_id=c["id"],
                        question=c["arguments"].get("question",""),
                        options=c["arguments"].get("options") or [],
                        timeout_seconds=ASK_USER_TIMEOUT_SECONDS,
                    )
                    return
                if c["name"] == "run_command" and not is_auto_approved(c["arguments"].get("cmd", "")):
                    # 非白名单只读命令必须过确认:存断点并结束本段,绝不挂起等回答(结果由 resume_turn 补)
                    # 白名单(ls/git status 等单条只读命令)直接落到下面 _execute 免确认,见 ADR-0004 决策7
                    session.pending = {
                        "kind":"confirm",
                        "step":step,          #第几轮(1-based)
                        "call_index":i,       #待处理的 call 在本步 calls 里的下标
                        "calls":calls,        #本步全部 tool_calls(恢复时直接复用,不从历史反解析)
                        "tool_call_id":c["id"],
                        "name":c["name"],
                        "args":c["arguments"],
                        "created_at":time.time(),
                        "expires_at":None,    #仅 ask_user 有值;confirm 永不超时
                    }
                    unpaired = []  #断点接管了,不当成"中断丢结果"补占位
                    yield ConfirmRequestEvent(
                        step=step,
                        tool_call_id=c["id"],
                        cmd=c["arguments"].get("cmd",""),
                        cwd=c["arguments"].get("cwd","."),
                    )
                    return
                result, ok = await _execute(c)
                stats["tools"] += 1
                if ok:
                    stats["tools_ok"] += 1
                session.messages.append(_tool_msg(c["id"], result))
                unpaired.remove(c["id"])
                yield ToolCallEvent(step=step,name=c["name"],args=c["arguments"],result=result)
            calls = None    #本步跑完 → 下一轮重新决策
            call_start = 0
            unpaired = []
        else:
            #for走完还没return = MAX_STEPS轮都在调工具
            yield ErrorEvent(message=f"执行步数超限：连续{max_steps}轮都在调工具")
    finally:
        # 本段被中途掐断(断流/取消)时先保住已生成的正文:用户屏幕上已经看到的内容必须和历史一致,
        # 丢了就等于"对话凭空少一轮",业界一致做法是 persist partial(见 plan 2.5 / ADR-0003)
        if half:
            session.append("assistant", half + "\n\n（回复已中断）")
        # 再给没配对的 call 补占位结果,否则下次请求直接 400(plan 第二坑)
        for cid in unpaired:
            session.messages.append(_tool_msg(cid, "（中断，未执行）"))
