# -*- coding: utf-8 -*-
"""存量裸 LaTeX 定界迁移（2026-10-13 用户裁定方案 A，一次性工具）。

范围：error_questions.explanation / error_questions.correct_answer /
      practice_records.question_content（同题干全部流水行一并同步，与「题干=聚合键」
      既有编辑口径一致；改后同题干仍指向同一新文本，聚合不破坏）。
      favorite_questions.question_content（2026-10-15 评审 Minor-3 补口：收藏态
      is_favorite 按题干文本比对，历史裸行会让已收藏题在新归一写入下漏判）。
口径：完全复用 services.error_analyze._wrap_bare_latex（单一实现，不另写一套规则）。
安全：默认 dry-run 只报告将改哪些行；--apply 时先把每行原值备份到
      logs/bare_latex_backup_<时间戳>.jsonl，再逐行 UPDATE。不碰 practice_records.user_answer
      （用户原始作答按「如实」规则保留原文）。

用法：python tools/migrate_bare_latex.py           # 预览
      python tools/migrate_bare_latex.py --apply   # 实际执行
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from database.db_adapter import get_connection  # noqa: E402
from services.error_analyze import _wrap_bare_latex  # noqa: E402


def _plan_rows(cur):
    """→ [(表, id, 列, 旧值, 新值)]；同题干流水按“旧文本→新文本”整组展开。"""
    changes = []

    cur.execute("SELECT id, explanation, correct_answer FROM error_questions")
    for rid, exp, ans in cur.fetchall():
        for col, old in (("explanation", exp), ("correct_answer", ans)):
            new = _wrap_bare_latex(old or "")
            if old and new != old:
                changes.append(("error_questions", rid, col, old, new))

    cur.execute("SELECT id, question_content FROM practice_records")
    pr_rows = cur.fetchall()
    # 题干聚合键：同一原文的全部流水行必须同步为同一新文本
    by_text = {}
    for rid, qc in pr_rows:
        new = _wrap_bare_latex(qc or "")
        if qc and new != qc:
            by_text.setdefault(qc, []).append(rid)
    for old_text, ids in by_text.items():
        new_text = _wrap_bare_latex(old_text)
        for rid in ids:
            changes.append(("practice_records", rid, "question_content", old_text, new_text))

    # 评审 Minor-3：收藏表题干同口径纳入（收藏态/重练匹配按题干文本比对）
    cur.execute("SELECT id, question_content FROM favorite_questions")
    fav_by_text = {}
    for rid, qc in cur.fetchall():
        new = _wrap_bare_latex(qc or "")
        if qc and new != qc:
            fav_by_text.setdefault(qc, []).append(rid)
    for old_text, ids in fav_by_text.items():
        new_text = _wrap_bare_latex(old_text)
        for rid in ids:
            changes.append(("favorite_questions", rid, "question_content", old_text, new_text))
    return changes


def main():
    apply = "--apply" in sys.argv
    with get_connection() as conn:
        cur = conn.cursor()
        changes = _plan_rows(cur)
        print(f"{'APPLY' if apply else 'DRY-RUN'}: 将变更 {len(changes)} 个字段值")
        for table, rid, col, old, new in changes:
            print(f"- {table}#{rid}.{col}  ({len(old)}→{len(new)} 字符)")
        if not changes:
            print("库中无裸 LaTeX 内容，无需迁移。")
            return 0
        if not apply:
            print("预览模式未做任何修改；确认后加 --apply 执行。")
            return 0

        backup = (Path(__file__).resolve().parents[1] / "logs" /
                  f"bare_latex_backup_{time.strftime('%Y%m%d_%H%M%S')}.jsonl")
        with backup.open("w", encoding="utf-8") as bf:
            for table, rid, col, old, new in changes:
                bf.write(json.dumps({"table": table, "id": rid, "col": col, "old": old},
                                    ensure_ascii=False) + "\n")
        print(f"原值已备份：{backup}")

        n = 0
        for table, rid, col, old, new in changes:
            # 评审 Minor-6：f-string 拼列名虽无实际注入面（表/列均来自本脚本固定清单），
            # 仍用白名单断言锁死，防后续改动引入风险
            assert table in ("error_questions", "practice_records", "favorite_questions"), table
            assert col in ("explanation", "correct_answer", "question_content"), col
            cur.execute(f"UPDATE {table} SET {col} = ? WHERE id = ?", (new, rid))
            n += 1
        conn.commit()
        print(f"迁移完成：{n} 个字段值已更新。")
        # 复核：不应再有可包裹的裸 LaTeX 行
        left = sum(1 for table, rid, col, old, new in changes
                   if _wrap_bare_latex(new) != new)
        print(f"复核：二次包裹检查残留 {left} 条（应为 0）")
        return 0


if __name__ == "__main__":
    sys.exit(main())
