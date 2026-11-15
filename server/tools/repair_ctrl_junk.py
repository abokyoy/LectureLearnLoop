# -*- coding: utf-8 -*-
"""存量 md 字体解码垃圾 token 剔除（2026-11-04 九下数学页脚乱码，一次性工具）。

范围：vault 全部 .md（含各书分段）；口径与 postprocess_pdf_text_layer 的
_CTRL_CH_RE token 剔除完全一致（单一规则，直接复用正则）。
安全：默认 dry-run 只报告；--apply 先备份原文到 logs/ctrl_junk_backup_<ts>/，
再逐文件写盘 + upsert_note_content 同步入库（MF-5 同存同改口径）。

用法：python tools/repair_ctrl_junk.py           # 预览
      python tools/repair_ctrl_junk.py --apply   # 实际执行
"""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from services import import_service as imp  # noqa: E402

VAULT = SERVER / "data" / "vault"


def clean_md(text: str) -> str:
    """逐行剔除含控制字符的空格分隔 token；整行皆垃圾则删行并收敛空行。

    零控制字符文件原样返回（评审自发现：空行收敛不得波及正常笔记格式）。
    """
    if not imp._CTRL_CH_RE.search(text):
        return text
    out_lines = []
    for ln in text.split("\n"):
        if not imp._CTRL_CH_RE.search(ln):
            out_lines.append(ln)
            continue
        kept = " ".join(t for t in ln.split(" ") if t and not imp._CTRL_CH_RE.search(t))
        if kept.strip():
            out_lines.append(kept.rstrip())
        # 整行皆垃圾 → 丢弃该行文字，保留其换行结构后统一收敛
        else:
            if out_lines and out_lines[-1] != "":
                out_lines.append("")
    joined = "\n".join(out_lines)
    while "\n\n\n" in joined:
        joined = joined.replace("\n\n\n", "\n\n")
    return joined


def main():
    apply = "--apply" in sys.argv
    targets = []
    for md in VAULT.rglob("*.md"):
        try:
            old = md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        new = clean_md(old)
        if new != old:
            targets.append((md, old, new))
    print(f"{'APPLY' if apply else 'DRY-RUN'}: 将修复 {len(targets)} 个 md 文件")
    for md, old, new in targets:
        print(f"- {md.relative_to(VAULT)}  (控制字符 {sum(1 for c in old if imp._CTRL_CH_RE.search(c))} 个 → 0)")
    if not targets:
        print("无含控制字符垃圾的 md，无需修复。")
        return 0
    if not apply:
        print("预览模式未做任何修改；确认后加 --apply 执行。")
        return 0

    backup_dir = SERVER / "logs" / f"ctrl_junk_backup_{time.strftime('%Y%m%d_%H%M%S')}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    n_file = n_db = 0
    for md, old, new in targets:
        # 评审 W：备份保留相对路径，防跨用户同名文件互盖致不可回滚
        rel = md.relative_to(VAULT)
        dst = backup_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(md, dst)
        md.write_text(new, encoding="utf-8")
        n_file += 1
        # vault/<user_id>/... → 同步入库
        parts = md.relative_to(VAULT).parts
        if len(parts) > 1:
            if imp.sync_note_content(parts[0], md, new):
                n_db += 1
            else:
                print(f"! 入库失败：{md}")
    print(f"完成：{n_file} 个文件已写盘，{n_db} 个已同步入库；原文备份 {backup_dir}")
    # 复核：不应再残留控制字符
    left = sum(1 for md, _o, n in targets if imp._CTRL_CH_RE.search(n))
    print(f"复核：残留含控制字符文件 {left} 个（应为 0）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
