from app.tools.registry import ToolRegistry

def ask_user(question:str,options:list[str]|None=None) -> str:
    """占位实现:正常情况下 runner 会拦截,不会走到这里 留一个能跑的实现,方便单独测试工具本身(不经过 runner 时直接调)"""
    return f"（需要用户回答）{question}"

def register(registry:ToolRegistry) -> None:
    registry.register(
        name="ask_user",
        description=(
            "向用户提问以澄清需求。用在:①需求有歧义 ②要在多个方案里选 ③缺少关键信息 "
            "④同一工具连续失败2次后不知如何处理。提问前先尽力自己查(读文件/看上下文),"
            "不要问已经能从上下文推断出来的问题;一轮对话最多问3-4个问题,避免连续追问"
        ),
        parameters={
            "type":"object",
            "properties":{
                "question":{
                    "type":"string",
                    "description":"要问用户的问题,说清为什么需要这个信息,让用户能直接回答",
                },
                "options":{
                    "type":"array",
                    "items":{"type":"string"},
                    "description":"可选的候选答案列表(如[\"账号密码\",\"手机号+验证码\"]),用户可直接点选;不确定时不要传",
                },
            },
            "required":["question"],
        },
        handler=ask_user,
    )