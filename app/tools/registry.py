from typing import Any
from collections.abc import Callable


class ToolRegistry:
    def __init__(self)->None:
        self._definitions:list[dict[str,Any]]=[]
        self.handlers:dict[str,Callable[...,Any]]={}

    def register(
            self,
            name:str,
            description:str,
            parameters:dict[str,Any],
            handler:Callable[...,Any],
        )->None:
            if name in self.handlers:
                raise ValueError(f"Tool {name} already already registered")
            self._definitions.append({
               "type":"function",
               "function":{
                "name":name,
                "description":description,
                "parameters":parameters,
               },
            })
            self.handlers[name]=handler

    @property
    def definitions(self)->list[dict[str,Any]]:
        return self._definitions

    def execute(self,name:str,arguments:dict[str,Any])->Any:
        if name not in self.handlers:
            raise ValueError(f"Tool {name} not registered")
        return self.handlers[name](**arguments)
