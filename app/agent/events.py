from dataclasses import dataclass

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
