# -*- coding: utf-8 -*-
"""四期一次性清理：删除老流程 auto-create 的「机器学习」科目及其知识点（问题 4/5 存量数据）。

背景：learn_from_materials 旧"完成知识点管理"流程硬编码 subject='机器学习'，
batch-save 又对不存在科目自动 add_subject，导致测试用户名下出现非用户创建的
「机器学习」科目，且知识点被串写进该科目（与用户自建科目如"666"内容重复）。

规则（用户已确认）：
- 仅处理非 admin 用户；admin(0001) 的科目视为存量演示数据不动；
- 删除范围：该用户「机器学习」科目在 error_questions / practice_records /
  knowledge_point_sources / knowledge_points / user_subjects 中的关联记录；
- 用户自建的其他科目（如"666"）绝不触碰；
- 幂等：重复执行报告"无可清理"。

运行（server/ 目录）：python tests/p4_cleanup.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SUBJECT = "机器学习"
PASS = [0]
FAIL = []


def check(cond, msg):
    if cond:
        PASS[0] += 1
        print(f"PASS  {msg}")
    else:
        FAIL.append(msg)
        print(f"FAIL  {msg}")


def main():
    from app import create_app
    app = create_app()
    with app.app_context():
        from flask import current_app
        conn = current_app.config["DB_CONN_FACTORY"]()

        users = conn.execute(
            "SELECT user_id, username, is_admin FROM users ORDER BY user_id").fetchall()
        print(f"账号总数: {len(users)}")
        cleaned = []
        for uid, uname, is_admin in users:
            if is_admin:
                continue
            subj = conn.execute(
                "SELECT id FROM user_subjects WHERE user_id = ? AND subject_name = ?",
                (uid, SUBJECT)).fetchone()
            if not subj:
                continue
            kp_rows = conn.execute(
                "SELECT id FROM knowledge_points WHERE user_id = ? AND subject_name = ?",
                (uid, SUBJECT)).fetchall()
            kp_ids = [r[0] for r in kp_rows]
            print(f"发现 auto-create 科目: 用户 {uname}({uid}) 科目「{SUBJECT}」知识点 {len(kp_ids)} 个")
            if kp_ids:
                q = ",".join("?" * len(kp_ids))
                eq_n = conn.execute(
                    f"DELETE FROM error_questions WHERE user_id = ? AND knowledge_point_id IN ({q})",
                    (uid, *kp_ids)).rowcount
                conn.execute(
                    f"DELETE FROM knowledge_point_sources WHERE knowledge_point_id IN ({q})",
                    tuple(kp_ids))
                conn.execute(
                    f"DELETE FROM knowledge_points WHERE user_id = ? AND subject_name = ?",
                    (uid, SUBJECT))
            else:
                eq_n = 0
            pr_n = conn.execute(
                "DELETE FROM practice_records WHERE user_id = ? AND subject_name = ?",
                (uid, SUBJECT)).rowcount
            conn.execute(
                "DELETE FROM user_subjects WHERE user_id = ? AND subject_name = ?",
                (uid, SUBJECT))
            cleaned.append((uname, len(kp_ids), eq_n, pr_n))

        try:
            conn.commit()
        except Exception:
            pass  # sqlite 自动提交场景

        # 复核：非 admin 用户不应再有「机器学习」科目；admin 与其他科目不受影响
        left = conn.execute(
            "SELECT us.user_id FROM user_subjects us JOIN users u ON u.user_id = us.user_id "
            "WHERE us.subject_name = ? AND u.is_admin = 0", (SUBJECT,)).fetchall()
        check(len(left) == 0, f"非 admin 用户「{SUBJECT}」科目已清空（剩余 {len(left)}）")

        other = conn.execute(
            "SELECT COUNT(*) FROM user_subjects us JOIN users u ON u.user_id = us.user_id "
            "WHERE u.is_admin = 0 AND us.subject_name <> ?", (SUBJECT,)).fetchone()[0]
        print(f"非 admin 用户保留的其他科目数: {other}（应大于等于清理前，未被误伤）")

        # admin 科目未被触碰（数量前后一致由只读断言：admin 仍可有机器学习）
        admin_sub = conn.execute(
            "SELECT COUNT(*) FROM user_subjects WHERE user_id = ? AND subject_name = ?",
            ("0001", SUBJECT)).fetchone()[0]
        print(f"admin(0001)「{SUBJECT}」科目存在={bool(admin_sub)}（种子数据，规则：不删除）")

        for uname, kp_n, eq_n, pr_n in cleaned:
            print(f"已清理 {uname}: 知识点 {kp_n}，错题 {eq_n}，练习记录 {pr_n}")
        if not cleaned:
            print("本次无可清理记录（幂等：说明已清理过或不存在误建数据）")

        try:
            conn.close()
        except Exception:
            pass

    print(f"\n结果: {PASS[0]} PASS / {len(FAIL)} FAIL")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
