"""一次性清理 Vault 孤儿附件图片（2026-10-06，用户裁定执行）。

背景：附件同存同删修复（import_service.delete_md_with_attachment_cleanup）
只作用于之后的删除动作；此前已删除 MD 留下的孤儿图片需要全库追溯回收。

口径与运行时删除逻辑完全一致（复用同一套匹配函数）：
- 每个 `<dir>/附件/` 目录独立判定：引用源 = 该目录整棵子树内的笔记文件
  （*.md / *.markdown / *.txt），相对路径 `附件/x` 只对同子树笔记有意义
- 仅回收图片扩展名（_ALLOWED_IMG_EXT）；非图片文件（原件 PDF 等）一律保留
- 子树内任一笔记读取失败 → 该附件目录整体跳过（宁可泄漏不可误删）
- 空附件目录在清理后顺带移除

用法：
    python tools/cleanup_orphan_attachments.py            # 干跑，仅报告
    python tools/cleanup_orphan_attachments.py --apply    # 实际删除
"""
import os
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))

from services import import_service as imp  # noqa: E402


def find_orphans_in_att_dir(att_dir: Path) -> tuple[list[Path], int]:
    """返回 (该附件目录内的孤儿图片文件, 子树笔记数)；不可判定返回 ([], n)。"""
    root = att_dir.parent
    notes = []
    for dirpath, _dirs, fnames in os.walk(root):
        for fn in fnames:
            p = Path(dirpath) / fn
            if p.suffix.lower() in imp.NOTE_SCAN_EXTS and p.is_file():
                notes.append(p)
    disk_forms = imp._att_disk_forms(att_dir)
    if not disk_forms:
        return [], len(notes)
    keep: set[str] = set()
    for p in notes:
        try:
            keep |= imp._names_referenced(
                p.read_text(encoding="utf-8", errors="replace"), disk_forms)
        except OSError:
            return [], len(notes)  # 读取失败：整目录跳过
    orphans = [att_dir / n for n in sorted(set(disk_forms) - keep)
               if Path(n).suffix.lower() in imp._ALLOWED_IMG_EXT]
    return orphans, len(notes)


def main(apply: bool, vault_root: Path) -> int:
    mode = "APPLY" if apply else "DRY-RUN"
    total_files = total_bytes = att_dirs = notes_seen = skipped = 0
    print(f"[{mode}] 扫描 {vault_root} ...")
    for user_dir in sorted(p for p in vault_root.iterdir() if p.is_dir()):
        for dirpath, dirs, _f in os.walk(user_dir):
            if "附件" not in dirs:
                continue
            att_dir = Path(dirpath) / "附件"
            if not (att_dir.is_dir() and att_dir.resolve(strict=False)
                    .is_relative_to(Path(dirpath).resolve(strict=False))):
                continue
            att_dirs += 1
            orphans, n_notes = find_orphans_in_att_dir(att_dir)
            notes_seen += n_notes
            if not orphans and n_notes == 0 and any(att_dir.iterdir()):
                skipped += 1
                continue  # 无笔记却仍有文件：非图片场景，不动
            for f in orphans:
                try:
                    size = f.stat().st_size
                    print(f"  - {f.relative_to(vault_root)}  ({size/1024:.1f} KB)")
                    total_files += 1
                    total_bytes += size
                    if apply:
                        f.unlink(missing_ok=True)
                except OSError as e:
                    print(f"  ! 无法处理 {f}: {e}")
            if apply and orphans and att_dir.is_dir() and not any(att_dir.iterdir()):
                try:
                    att_dir.rmdir()
                except OSError:
                    pass
    print(f"[{mode}] 完成：附件目录 {att_dirs} 个 / 笔记 {notes_seen} 篇；"
          f"{'删除' if apply else '待删除'}孤儿图片 {total_files} 个，"
          f"共 {total_bytes/1024/1024:.1f} MB；跳过目录 {skipped} 个")
    return 0


if __name__ == "__main__":
    apply_flag = "--apply" in sys.argv
    vault = SERVER_DIR / "data" / "vault"
    sys.exit(main(apply_flag, vault))
