from dataclasses import dataclass,field

@dataclass
class ChunkEvent:
    type:str = "chunk"
    content:str = ""

@dataclass
class DoneEvent:
    type:str = "done"


@dataclass
class ErrorEvent:
    type:str = "error"
    message:str = ""

@dataclass
class ToolCallEvent:
    type:str = "tool_call"
    step:int = 0
    name:str = ""
    args:dict = field(default_factory=dict)
    result:str = ""

@dataclass
class ConfirmRequestEvent:
    # 命令确认请求:yield 出这个事件后本段立即结束,等调用方发 resume(见 plan 2.5)
    type:str = "confirm_request"
    step:int = 0
    tool_call_id:str = ""    # 关联键就是它,不再另造 confirm_id
    cmd:str = ""
    cwd:str = ""
