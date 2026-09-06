import yaml
from pathlib import Path
from .schema import Setting

# loader.py 在 app/config/ 下,上溯三级(app/config -> app -> 项目根)才是 configs/
CONFIG_FILE = Path(__file__).resolve().parent.parent.parent / "configs" / "models.yaml"

# 取模型用 cfg.get_model(name),见 schema.py
def load_models():
    with CONFIG_FILE.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
        return Setting(**raw)