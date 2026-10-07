# 一次性维护（2026-10-07）：回收"原件已不在磁盘"的僵尸 pdf_book 任务行及其子任务
# 用法：python tools/purge_zombie_book_tasks.py          # 干跑，只打印清单
#       python tools/purge_zombie_book_tasks.py --apply  # 实删
# 注意：干跑确认清单后再 --apply；原件临时离线（移动盘未挂载等）会被判僵尸，勿盲删。
import os
import sys

sys.path.insert(0, '.')
from database.db_adapter import get_connection  # noqa: E402

apply = "--apply" in sys.argv
conn = get_connection()
try:
    rows = conn.execute(
        "SELECT task_id, user_id, result_pdf FROM import_tasks WHERE kind='pdf_book'"
    ).fetchall()
    zombies = [r[0] for r in rows if not (r[2] and os.path.isfile(r[2]))]
    print("pdf_book rows=%d, zombies=%d -> %s" % (len(rows), len(zombies), zombies))
    if not zombies:
        sys.exit(0)
    if not apply:
        print("dry-run：未删除任何行，确认清单后加 --apply 执行")
        sys.exit(0)
    for tid in zombies:
        conn.execute("DELETE FROM import_tasks WHERE parent_task_id = ?", (tid,))
        conn.execute("DELETE FROM import_tasks WHERE task_id = ?", (tid,))
    conn.commit()
    print("purged=%d" % len(zombies))
finally:
    conn.close()
