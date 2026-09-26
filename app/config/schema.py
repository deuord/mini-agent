import os
import re
from pydantic import BaseModel,Field

class ModelConfig(BaseModel):
   name:str=Field(description="模型名称")
   provider: str = "openai_compat"
   base_url: str = Field(description="模型服务地址")
   api_key: str = Field(description="模型服务API密钥")
   model: str


class Setting(BaseModel):
  default:str
  models: list[ModelConfig] = Field(min_length=1)
  agent_max_steps: int = 6  # ReAct 轮数上限,v4.1 上下文工程完成后放开(改 models.yaml)
  

  def get_model(self,name:str|None=None)->ModelConfig:
    #按name取模型配置、default兜底、env覆写key
    name = name or self.default
    for model in self.models:
      if model.name == name:
       # deepseek-v4-flash -> DEEPSEEK_V4_FLASH_KEY(非字母数字统一换下划线)
       env_name = f"{re.sub(r'[^A-Za-z0-9]', '_', model.name).upper()}_KEY"
       env_key = os.environ.get(env_name)
       if env_key:
         model.api_key = env_key
       return model
    raise KeyError(f"模型 {name} 不存在")
 