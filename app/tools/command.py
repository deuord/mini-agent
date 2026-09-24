# app/tools/command.py — 命令执行工具:只管执行,执行前的确认在 runner 层走 confirm 回调
import subprocess
from app.tools.registry import ToolRegistry

def run_command(cmd:str,cwd:str = ".")->str:
    try:
        r = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,  #执行超过90秒、超时直接终止
        )
    except subprocess.TimeoutExpired:
        return f"命令超过90s被终止:{cmd}"
    except (FileNotFoundError,NotADirectoryError):
        return f"文件或目录不存在:{cwd}"
    out = (r.stdout or "").strip() + (r.stderr or "")
    if len(out) > 4000: #防止输入太长爆上下文
        out = out[:4000]+ f"\n...(输出共{len(out)}字符、已截断)"    
    return f"exit={r.returncode}\n{out}"    


def register(registry:ToolRegistry)->None:
    registry.register(
        name = "run_command",
        description = "在本机 shell 执行一条命令,返回退出码和输出。执行前会先向用户请求确认,用户可能拒绝;命令最长运行 90 秒",
        parameters={
            "type":"object",
            "properties":{
                "cmd":{
                    "type":"string",
                    "description":"要执行的 shell 命令,例如 ls -la",
                },
                "cwd":{
                    "type":"string",
                    "description":"工作目录,不传则用当前目录",
                }
            },
            "required":["cmd"],
        },
        handler=run_command,
    )
   
