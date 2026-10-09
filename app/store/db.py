# app/store/db.py — SQLite 连接 + 表初始化(单文件 data/mini-agent.db,见 plan 2.4)
import sqlite3
from pathlib import Path

# db.py 在 app/store/ 下,上溯三级(app/store -> app -> 项目根)才是 data/
DB_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DB_FILE = DB_DIR / "mini-agent.db"

# 全部 IF NOT EXISTS,进程启动时调一次即幂等
_SCHEMA = """
CREATE TABLE IF NOT EXISTS recent_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL,
    op TEXT NOT NULL,           -- read / write / edit
    accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_recent_files_accessed ON recent_files(accessed_at DESC);
"""


def get_conn() -> sqlite3.Connection:
    """开一个连接(用完即关)。每次操作独立连接:sqlite3 连接不跨线程安全,
    而工具都丢 asyncio.to_thread 执行,独立连接最省心(见 plan 2.4)"""
    DB_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row   # 行支持按列名取值,后续 SELECT 用着方便
    return conn


def init_db() -> None:
    """建表(幂等),进程启动时调一次。v2.4 任务1 暂未接调用方"""
    conn = get_conn()
    try:
        conn.executescript(_SCHEMA)
    finally:
        conn.close()
