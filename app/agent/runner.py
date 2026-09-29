from typing import AsyncIterator
import json
import time
from ..config.loader import load_models
from ..llm.openai_compat import chat_stream
from ..obs import log_event
from .events import ChunkEvent, ConfirmRequestEvent, DoneEvent, ErrorEvent, ToolCallEvent
from .session import Session
from ..tools.calls import buffer_tool_calls, parse_tool_calls
from ..tools.file import register as register_file
from ..tools.command import register as register_command
from ..tools.registry import ToolRegistry

_registry = ToolRegistry()
register_file(_registry)  #模块级注册一次：tools=definitions随请求发出
register_command(_registry)  # 命令工具:执行前由 runner 存断点等用户确认(见 plan 2.5)

Event = ChunkEvent | DoneEvent | ErrorEvent | ToolCallEvent | ConfirmRequestEvent

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

def _execute(c:dict) ->tuple[str,bool]:
    """跑一个普通工具,返回(结果文本,是否成功);业务失败喂回模型让它自纠(文件不存在等)"""
    try:
        return str(_registry.execute(c["name"],c["arguments"])),True
    except Exception as e:
        return f"工具执行失败: {e}",False

def _resolve_answer(session:Session,p:dict,answer:dict) ->tuple[str,bool]:
    """把对断点的回答翻译成 tool 结果;顺带记一次人机交互埋点(等待时长+通过与否)"""
    approved = answer.get("approve") is True
    log_event(
        "confirm",
        session_id=session.session_id,
        wait_seconds=round(time.time()-p["created_at"],1),
        approved=approved,
    )
    if not approved:
        return "用户拒绝执行该命令",True
    return _execute({"name":p["name"],"arguments":p["args"]})

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
    if session.pending:  #上个断点没答完,不许插新消息
        yield ErrorEvent(message="还有待处理的确认/提问,请先回答")
        return
    start_len = len(session.messages) #本段起点：出错删到这里，历史回到上一段的成对状态
    t0 = time.monotonic()
    stats = _new_stats()
    err = None
    session.append("user", user_text)  # 1.用户消息写进历史
    try:
        async for ev in _react(session, cfg, step_start=1, stats=stats):
            yield ev
    except Exception as e:
        del session.messages[start_len:] #删掉本段全部消息（含 user 消息），用户重发这条
        session.pending = None           #断点可能指向已删的消息，一并清掉，免得恢复时悬空
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
        result, ok = _resolve_answer(session, p, answer)
        stats["tools"] += 1
        if ok:
            stats["tools_ok"] += 1
        session.messages.append(_tool_msg(p["tool_call_id"], result))
        yield ToolCallEvent(step=p["step"], name=p["name"], args=p["args"], result=result)
        async for ev in _react(
            session, cfg, step_start=p["step"],
            calls=p["calls"], call_start=p["call_index"] + 1, stats=stats,
        ):
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
                        yield ChunkEvent(content=delta.content)
                    if delta.tool_calls: # 模型要调工具,参数分片陆续到达,先累积进 buf
                        buffer_tool_calls(buf,delta.tool_calls)
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
                if c["name"] == "run_command":
                    # 命令类工具必须过确认:存断点并结束本段,绝不挂起等回答(结果由 resume_turn 补)
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
                result, ok = _execute(c)
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
        # 本段被中途掐断(断流/异常/取消)时,给没配对的 call 补占位结果,否则下次请求直接 400(plan 第二坑)
        for cid in unpaired:
            session.messages.append(_tool_msg(cid, "（中断，未执行）"))
