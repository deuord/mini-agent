from pathlib import Path
import time
from app.tools.registry import ToolRegistry
from app.store.db import get_conn

def _record(op:str,path) -> None:
    # 只在工具执行成功时调用;不去重,同一文件多次访问就是多条
    # accessed_at 显式插 epoch 秒:不用 DEFAULT 那个 UTC 时间戳,显示转本地才不差 8 小时
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO recent_files (path, op, accessed_at) VALUES (?, ?, ?)",
            (str(path), op, time.time()),
        )
        conn.commit()
    finally:
        conn.close()   # 独立连接纪律:谁开谁关,漏了就是泄漏

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
    # ORDER BY accessed_at DESC 正好吃上 plan 2.4 建的索引
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT path, op, accessed_at FROM recent_files ORDER BY accessed_at DESC LIMIT ?",
            (max(1, limit),),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        return "暂无最近访问记录"
    lines = [
        f"{i+1}. [{r['op']}] {r['path']}  ({time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(r['accessed_at']))})"
        for i, r in enumerate(rows)
    ]
    return f"最近访问（{len(rows)} 条,最新在前）:\n" + "\n".join(lines)


def list_dir(path:str = ".")->str:
    # 只读列目录:结构化、不经过 shell,所以 runner 不拦截、无需用户确认
    # (run_command 跑 ls 仍每次确认;引导模型看目录用本工具,见 plan 2.2 / ADR-0004 边界1)
    p = Path(path)
    if not p.exists():
        return f"路径不存在:{path}"
    if not p.is_dir():
        return f"不是目录:{path}"
    entries = sorted(p.iterdir(), key=lambda x:(not x.is_dir(), x.name.lower()))  # 子目录排在前
    names = [(e.name + "/") if e.is_dir() else e.name for e in entries]
    head = f"{path}（共{len(names)}项,目录在前）"
    if len(names) > 200:  # node_modules 这类可能几千项,截断防爆上下文
        return head + ":\n" + "\n".join(names[:200]) + f"\n...(共{len(names)}项,只显示前200)"
    return head + ":\n" + "\n".join(names)

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
    registry.register(
        name="list_dir",
        description="列出一个目录下的文件和子目录(子目录名以 / 结尾、排在前面),只读、无需用户确认。查看目录结构时优先用本工具,不要用 run_command 执行 ls/dir/find——走 run_command 的命令每次都要用户确认",
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "目录路径,默认当前目录,支持相对路径和绝对路径",
                },
            },
        },
        handler=list_dir,
    )