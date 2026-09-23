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
