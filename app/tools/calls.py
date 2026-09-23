import json
from typing import Any

def buffer_tool_calls(buf:dict[int,dict[str,str]],deltas:list[Any]) ->None:
    # 分片按 index 归位：id/name 只在首片出现，arguments 每片追加
    for delta in deltas:
        slot = buf.setdefault(delta.index,{"id":"","name":"","arguments":""})
        if delta.id:
            slot["id"] = delta.id
        if delta.function and delta.function.name:
            slot["name"] = delta.function.name
        if delta.function and delta.function.arguments:
            slot["arguments"] += delta.function.arguments

def parse_tool_calls(buf:dict[int,dict[str,str]]) ->list[dict[str,Any]]:
    # 拼接完整后才json.loads --提前解析半截json会直接报错
    calls = []
    for index in sorted(buf):
        slot = buf[index]
        if not slot["id"] or not slot["name"]:
            raise ValueError(f"tool_call #{index}缺ID或name（首片丢失")
        calls.append(
            {
                "id":slot["id"],
                "name":slot["name"],
                "arguments":json.loads(slot["arguments"] or "{}"),
            }
        )
    return calls