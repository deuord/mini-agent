import json
import time
from collections import Counter
from pathlib import Path


LOG_DIR = Path("logs")
METRICS_FILE = LOG_DIR / "metrics.json"
_counter = Counter()  #内存计数， /api/metrics聚合时用（v2.4接）


def log_event(type:str,**fields) ->dict:
    """记一条指标：写logs/metrics.json 一行，内存计数+1"""
    event = {"type":type,"ts":round(time.time(),3),**fields}
    _counter[type]+=1
    LOG_DIR.mkdir(exist_ok=True)
    with METRICS_FILE.open("a",encoding="utf-8") as f:
        f.write(json.dumps(event,ensure_ascii=False)+"\n")
    return event