from collections import deque
from pathlib import Path
import time
from app.tools.registry import ToolRegistry

_recent: deque[dict] = deque(maxlen=200)  #最近访问记录(方案 A 内存占位,重启即空;v2.4 换 SQLite,见 plan 2.2)

def _record(op:str,path:str)->None:
    # 只在工具执行成功时调用;不去重,同一文件多次访问就是多条
    _recent.append({"path":str(path),"op":op,"at":time.time()})

def read_file(path:Path)->str:
    text = Path(path).read_text(encoding="utf-8")
    _record("read",path)
    return text

def write_file(path:str,content:str)->str:
    p = Path(path)
    p.parent.mkdir(parents=True,exist_ok=True) # 父目录不存在自动建,模型没有 mkdir 工具,不建会卡住
    p.write_text(content,encoding="utf-8")
    _record("write",path)
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
    _record("edit",path)
    return f"已替换文件{path}里的目标文本（1处）"

def list_recent_files(limit:int = 20)->str:
    if not _recent:
        return "暂无最近访问记录"
    items = list(_recent)[::-1][:max(1,limit)]  #deque 尾部最新,倒序取前 limit 条
    lines = [
        f"{i+1}. [{r['op']}] {r['path']}  ({time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(r['at']))})"
        for i,r in enumerate(items)
    ]
    return f"最近访问（{len(items)} 条,最新在前）:\n" + "\n".join(lines)

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
    registry.register(
        name="list_recent_files",
        description="列出最近被读取/写入/编辑过的文件(按访问时间倒序,最新在前),用于回顾动过哪些文件",
        parameters={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "返回条数,默认 20",
                },
            },
        },
        handler=list_recent_files,
    )