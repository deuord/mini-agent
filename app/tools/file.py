from pathlib import Path
from app.tools.registry import ToolRegistry

def read_file(path:Path)->str:
    return Path(path).read_text(encoding="utf-8")

def register(registry:ToolRegistry)->None:
    registry.register(
        name="read_file",
        description="读取一个文本文件，返回文件完整内容",
        parameters={
            "type":"object",
            "properties":{
                "path":{
                    "type":"string",
                    "description":"文件路径,支持相对路径和绝对路径",
                }
            },
            "required":["path"],
        },
        handler=read_file,
    )