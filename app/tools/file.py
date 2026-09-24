from pathlib import Path
from app.tools.registry import ToolRegistry

def read_file(path:Path)->str:
    return Path(path).read_text(encoding="utf-8")

def write_file(path:str,content:str)->str:
    p = Path(path)
    p.parent.mkdir(parents=True,exist_ok=True) # 父目录不存在自动建,模型没有 mkdir 工具,不建会卡住
    p.write_text(content,encoding="utf-8")
    return f"已写入文件{path},共{len(content)}个字符"

def edit_file(path:str,old_str:str,new_str:str)->str:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    n = text.count(old_str)
    if n == 0:
        raise ValueError(f"old_str在{path}里找不到、无法替换")
    if n > 1:
        raise ValueError(f"old_str在{path}里有多个匹配项,请多带几个字进行匹配")
    p.write_text(text.replace(old_str,new_str,1),encoding="utf-8")
    return f"已替换文件{path}里的目标文本（1处）"

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
    registry.register(
        name="write_file",
        description="创建或覆盖写入一个 UTF-8 文本文件,父目录不存在会自动创建",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "文件路径,支持相对路径和绝对路径",
                },
                "content": {
                    "type": "string",
                    "description": "文件的完整内容,会整体覆盖原文件",
                },
            },
            "required": ["path", "content"],
        },
        handler=write_file,
    )
    registry.register(
        name="edit_file",
        description="在文件里做一次精确字符串替换:old_str 必须在文件中唯一出现,整段换 new_str。局部小改动用它,大改用 write_file",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "文件路径,支持相对路径和绝对路径",
                },
                "old_str": {
                    "type": "string",
                    "description": "要被替换的原文,必须在文件里唯一出现",
                },
                "new_str": {
                    "type": "string",
                    "description": "替换成的新文本",
                },
            },
            "required": ["path", "old_str", "new_str"],
        },
        handler=edit_file,
    )