# -*- coding: utf-8 -*-
"""一次性修复错题 #1253 的公式定界符（2026-10-15 用户裁定 A）。

背景：该题解析是中英混合叙述行，_wrap_bare_latex 保守判定（宁漏不错包）刻意
不处理这类行，存量迁移与落库兜底都覆盖不到——需按语义手工分段加 $ 定界。
范围：error_questions#1253（正确答案/解析）+ 同题干全部流水行题干（聚合键整组
同步，与 migrate_bare_latex.py 同口径）+ error_questions 冗余题干列。
安全：先备份原值到 logs/bare_latex_backup_<ts>.jsonl 再 UPDATE；执行后回读打印。

用法：python tools/fix_error_1253_delims.py           # 预览（dry-run）
      python tools/fix_error_1253_delims.py --apply   # 实际执行
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

EID = 1253

# 语义与原值一一对应，仅为数学片段补 $ 行内定界（KaTeX 可解析形态）
OLD_Q = "已知关于 x 的一元二次方程 x^2+(n-4)x-4n=0。若 n 为整数，且方程的一个根小于 4，则 n 的取值范围是 ______。"
NEW_Q = "已知关于 x 的一元二次方程 $x^2+(n-4)x-4n=0$。若 $n$ 为整数，且方程的一个根小于 4，则 $n$ 的取值范围是 ______。"
OLD_A = "n≥-3|n>=-3"
NEW_A = "$n\\geq-3$|$n>=-3$"
# 裸原文（首次入库形态，留档供校验与回滚参考）
RAW_EX = ("Δ=(n-4)^2-4(-4n)=n^2+8n+16=(n+4)^2≥0。方程可化为 (x-4)(x+n)=0，"
          "根为 4 和 -n。因为 4 不小于 4，所以需 -n<4，即 n>-4。又 n 为整数，因此 n≥-3。")
# 首修态（含 $4$，已被货币防误判丢弃，需二修）
OLD_EX = ("$\\Delta=(n-4)^2-4(-4n)=n^2+8n+16=(n+4)^2 \\geq 0$。"
          "方程可化为 $(x-4)(x+n)=0$，根为 $4$ 和 $-n$。"
          "因为 $4$ 不小于 $4$，所以需 $-n<4$，即 $n>-4$。"
          "又 $n$ 为整数，因此 $n \\geq -3$。")
# 二修（2026-10-15 渲染同款正则实测）：$4$ 这类纯数字体被 md_render 货币防误判规则
# （$ 紧跟数字不当公式）丢弃，会露出生文本——纯数字用裸文本，不进公式定界
NEW_EX = ("$\\Delta=(n-4)^2-4(-4n)=n^2+8n+16=(n+4)^2 \\geq 0$。"
          "方程可化为 $(x-4)(x+n)=0$，根为 4 和 $-n$。"
          "因为 4 不小于 4，所以需 $-n<4$，即 $n>-4$。"
          "又 $n$ 为整数，因此 $n \\geq -3$。")


def main():
    apply = "--apply" in sys.argv
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT pr.id, pr.question_content, eq.correct_answer, eq.explanation, eq.question_content "
                    "FROM error_questions eq JOIN practice_records pr ON eq.practice_record_id = pr.id "
                    "WHERE eq.id = ?", (EID,))
        row = cur.fetchone()
        if not row:
            print(f"未找到错题 #{EID}，退出")
            return 1
        prid, pr_q, eq_a, eq_ex, eq_q = row
        print("流水#" + str(prid) + " 题干 repr: " + repr(pr_q))
        print("错题 答案 repr: " + repr(eq_a))
        print("错题 解析 repr: " + repr(eq_ex))
        # 幂等校验：各字段现值必须 ∈ {裸原文, 首修态}（二修可能重跑/断点续跑），否则中止
        if (pr_q not in (OLD_Q, NEW_Q) or eq_a not in (OLD_A, NEW_A)
                or (eq_ex or "") not in (RAW_EX, OLD_EX)):
            print("!! 库内现值与预期形态均不符，可能已被另行编辑——中止，不覆盖")
            return 1

        # 同题干整组范围（聚合键纪律，含已修态）：pr 全部行 + eq 冗余题干列
        cur.execute("SELECT COUNT(*) FROM practice_records WHERE question_content IN (?, ?)",
                    (OLD_Q, NEW_Q))
        n_pr = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM error_questions WHERE question_content IN (?, ?)",
                    (OLD_Q, NEW_Q))
        n_eq = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM favorite_questions WHERE question_content IN (?, ?)",
                    (OLD_Q, NEW_Q))
        n_fav = cur.fetchone()[0]
        print("同题干范围: practice_records " + str(n_pr) + " 行, error_questions 冗余列 "
              + str(n_eq) + " 行, favorite_questions " + str(n_fav) + " 行")
        if not apply:
            print("DRY-RUN 未做修改；确认后加 --apply 执行。")
            return 0

        backup = (Path(__file__).resolve().parents[1] / "logs" /
                  f"bare_latex_backup_{time.strftime('%Y%m%d_%H%M%S')}.jsonl")
        with backup.open("w", encoding="utf-8") as bf:
            bf.write(json.dumps({"table": "error_questions", "id": EID, "col": "correct_answer",
                                 "old": eq_a}, ensure_ascii=False) + "\n")
            bf.write(json.dumps({"table": "error_questions", "id": EID, "col": "explanation",
                                 "old": eq_ex}, ensure_ascii=False) + "\n")
            bf.write(json.dumps({"table": "practice_records(同题干整组)", "old": pr_q,
                                 "count": n_pr}, ensure_ascii=False) + "\n")
        print("原值已备份: " + str(backup))

        cur.execute("UPDATE error_questions SET correct_answer = ?, explanation = ? WHERE id = ?",
                    (NEW_A, NEW_EX, EID))
        cur.execute("UPDATE practice_records SET question_content = ? WHERE question_content IN (?, ?)",
                    (NEW_Q, OLD_Q, NEW_Q))
        cur.execute("UPDATE error_questions SET question_content = ? WHERE question_content IN (?, ?)",
                    (NEW_Q, OLD_Q, NEW_Q))
        cur.execute("UPDATE favorite_questions SET question_content = ? WHERE question_content IN (?, ?)",
                    (NEW_Q, OLD_Q, NEW_Q))
        # 评审 Minor-2：回读校验前置到 commit 之前（同一事务内 SELECT 可读到自己未提交的写，
        # 断言不过则不 commit，with 退出时 rollback），使校验真正成为守卫而非事后报告
        cur.execute("SELECT pr.question_content, eq.correct_answer, eq.explanation "
                    "FROM error_questions eq JOIN practice_records pr ON eq.practice_record_id = pr.id "
                    "WHERE eq.id = ?", (EID,))
        q2, a2, ex2 = cur.fetchone()
        assert q2 == NEW_Q and a2 == NEW_A and ex2 == NEW_EX, "回读不一致，回滚不提交！"
        conn.commit()
        print("APPLIED: 事务内回读校验通过并提交，三字段均已带 $ 定界。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
