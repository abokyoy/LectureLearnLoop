"""一次性：确认 practice_records 新列已生效（翻卡选项落库前置检查）"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import db_adapter

conn = db_adapter.get_connection()
try:
    rows = conn.execute(
        "select column_name, data_type from information_schema.columns "
        "where table_name='practice_records' order by ordinal_position"
    ).fetchall()
    with open("logs/u14_cols.txt", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(f"{r[0]}  {r[1]}\n")
    print("OK", [r[0] for r in rows])
finally:
    conn.close()
