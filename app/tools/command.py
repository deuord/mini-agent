# app/tools/command.py — 命令执行工具:只管执行,执行前的确认在 runner 层存断点等用户回答(见 plan 2.5)
import shlex
import subprocess
from app.tools.registry import ToolRegistry

# 只读命令自动放行白名单(免确认)。定位是"减少打扰",不是安全边界:
# 只放行"单条简单只读命令",任何复合结构/元字符/拿不准的一律不批(见 ADR-0004 决策7)
_READONLY_CMDS = frozenset({
    "ls", "pwd", "cat", "head", "tail", "grep", "rg", "find", "wc", "stat", "file",
    "which", "whereis", "echo", "date", "whoami", "hostname", "tree", "du", "df",
    "ps", "uptime", "uname",
})
# git 只放只读子命令(push/commit/checkout/reset 等写操作不在内)
_READONLY_GIT_SUBCMDS = frozenset({"status", "log", "diff", "show", "blame", "ls-files"})
# find 带这些参数能执行命令或写盘,不能放行
_FIND_FORBIDDEN_OPTS = frozenset({
    "-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0", "-fls", "-fls0",
})
# 出现即拒的 shell 元字符:命令连接/管道/重定向/命令替换/子 shell/换行。
# 引号内出现也拒(如 echo "a;b")——保守误伤可接受,漏判不可接受
_FORBIDDEN_CHARS = frozenset(";|&<>`$()\n\r")


def is_auto_approved(cmd: str) -> bool:
    """判断命令是否属于可免确认的"单条简单只读命令";拿不准一律返回 False(要确认)

    不用 startswith 前缀匹配(`ls;rm` 会绕过),而是:先拒元字符 → shlex 严格分词 → 程序名精确匹配
    """
    if not cmd or any(ch in cmd for ch in _FORBIDDEN_CHARS):
        return False
    try:
        tokens = shlex.split(cmd)  # 引号未闭合会抛 ValueError → 拿不准,要确认
    except ValueError:
        return False
    if not tokens:
        return False
    prog = tokens[0]
    if prog == "git":
        return len(tokens) >= 2 and tokens[1] in _READONLY_GIT_SUBCMDS
    if prog not in _READONLY_CMDS:
        return False
    if prog == "find" and any(t in _FIND_FORBIDDEN_OPTS for t in tokens):
        return False
    return True


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
            timeout=30,  #执行超过30秒、超时直接终止(确认等待永不超时,与这个无关,见 plan 2.5)
        )
    except subprocess.TimeoutExpired:
        return f"命令超过30s被终止:{cmd}"
    except (FileNotFoundError,NotADirectoryError):
        return f"文件或目录不存在:{cwd}"
    out = (r.stdout or "").strip() + (r.stderr or "")
    if len(out) > 4000: #防止输入太长爆上下文
        out = out[:4000]+ f"\n...(输出共{len(out)}字符、已截断)"    
    return f"exit={r.returncode}\n{out}"    


def register(registry:ToolRegistry)->None:
    registry.register(
        name = "run_command",
        description = "在本机 shell 执行一条命令,返回退出码和输出。单条简单只读命令(如 ls、cat、grep、git status/log/diff)直接执行;其他命令(尤其写操作、复合命令、管道)会先向用户请求确认,用户可能拒绝;命令最长运行 30 秒",
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
   
