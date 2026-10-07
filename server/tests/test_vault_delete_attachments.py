# -*- coding: utf-8 -*-
"""MD 删除与附件同存同删（2026-10-06 用户裁定）黑盒断言测试。

纯文件系统测试 delete_md_with_attachment_cleanup，不依赖 Flask/PG。
覆盖：独占图回收、共享图保留（多 MD/书籍分段）、URL 编码引用、空目录移除、
原件 PDF 不误删、无引用 MD 直删。
"""
from pathlib import Path

import pytest

from services import import_service as imp


def _mk(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def _att(tmp_path: Path, *names: str) -> None:
    d = tmp_path / "附件"
    d.mkdir(parents=True, exist_ok=True)
    for n in names:
        (d / n).write_bytes(b"\x89PNG fake")


class TestDeleteMdAttachmentCleanup:
    def test_exclusive_images_removed_shared_kept(self, tmp_path):
        """a.md 独占 img_a.png 被回收；img_shared.png 仍被 b.md 引用则保留。"""
        _att(tmp_path, "img_a.png", "img_shared.png")
        _mk(tmp_path, "a.md", "# A\n![图](附件/img_a.png)\n![共](附件/img_shared.png)\n")
        _mk(tmp_path, "b.md", "# B\n![共](附件/img_shared.png)\n")
        a = tmp_path / "a.md"

        ok, removed = imp.delete_md_with_attachment_cleanup(a)
        assert ok is True
        assert not a.exists()
        assert removed == ["img_a.png"]
        assert not (tmp_path / "附件" / "img_a.png").exists()
        assert (tmp_path / "附件" / "img_shared.png").exists()

    def test_book_segments_shared_attach_dir(self, tmp_path):
        """书籍分段场景：删 1-20 段，段内独占图回收；尾段仍引用的图保留。"""
        _att(tmp_path, "img_p1.png", "img_p2.png")
        _mk(tmp_path, "书·0001-0020.md", "![](附件/img_p1.png)\n![](附件/img_p2.png)\n")
        _mk(tmp_path, "书·0021-0040.md", "![](附件/img_p2.png)\n")
        ok, removed = imp.delete_md_with_attachment_cleanup(tmp_path / "书·0001-0020.md")
        assert ok and removed == ["img_p1.png"]
        assert (tmp_path / "附件" / "img_p2.png").exists()

    def test_percent_encoded_reference(self, tmp_path):
        """URL 编码引用（摘录截图形态）同样能定位并回收原始文件名。"""
        d = tmp_path / "附件"
        d.mkdir()
        (d / "截屏 1.png").write_bytes(b"x")
        _mk(tmp_path, "n.md", "![](%E9%99%84%E4%BB%B6/%E6%88%AA%E5%B1%8F%201.png)\n")
        ok, removed = imp.delete_md_with_attachment_cleanup(tmp_path / "n.md")
        assert ok is True
        assert removed == ["截屏 1.png"]
        assert not (d / "截屏 1.png").exists()

    def test_attach_dir_removed_only_when_empty(self, tmp_path):
        """附件目录清空后移除；仍有原件 PDF 则保留目录。"""
        _att(tmp_path, "img_x.png")
        (tmp_path / "附件" / "原稿.pdf").write_bytes(b"%PDF")
        _mk(tmp_path, "m.md", "![](附件/img_x.png)\n")
        ok, removed = imp.delete_md_with_attachment_cleanup(tmp_path / "m.md")
        assert ok and removed == ["img_x.png"]
        assert (tmp_path / "附件").is_dir()  # PDF 还在，目录不能删
        assert (tmp_path / "附件" / "原稿.pdf").exists()

        _mk(tmp_path, "m2.md", "![](附件/img_y.png)\n")
        (tmp_path / "附件" / "img_y.png").write_bytes(b"y")
        (tmp_path / "附件" / "原稿.pdf").unlink()
        ok2, rem2 = imp.delete_md_with_attachment_cleanup(tmp_path / "m2.md")
        assert ok2 and rem2 == ["img_y.png"]
        assert not (tmp_path / "附件").exists()  # 全空 → 空目录回收

    def test_md_without_references_and_no_attach_dir(self, tmp_path):
        """无引用/无附件目录的普通 MD：直删成功，不误伤。"""
        other = _mk(tmp_path, "keep.md", "# 无图笔记\n")
        ok, removed = imp.delete_md_with_attachment_cleanup(other)
        assert ok is True and removed == []
        assert not other.exists()

        lone = tmp_path / "solo.md"
        lone.write_text("![](附件/none.png)\n", encoding="utf-8")  # 引用悬空
        ok2, rem2 = imp.delete_md_with_attachment_cleanup(lone)
        assert ok2 is True and rem2 == [] and not lone.exists()

    def test_cross_form_reference_not_misdeleted(self, tmp_path):
        """评审 P0：删方全编码引用，存留方原始带空格/括号/尖括号/query 形态引用 → 不得误删。"""
        _att(tmp_path, "图 1.png", "图(2).png", "q.png")
        _mk(tmp_path, "del.md",
            "![](%E9%99%84%E4%BB%B6/%E5%9B%BE%201.png)\n![](%E9%99%84%E4%BB%B6/%E5%9B%BE(2).png)\n![](附件/q.png?v=2)\n")
        _mk(tmp_path, "keep.md", "![](附件/图 1.png)\n![](<附件/图(2).png>)\n![x](附件/q.png?v=2)\n")
        ok, removed = imp.delete_md_with_attachment_cleanup(tmp_path / "del.md")
        assert ok is True and removed == []
        for n in ("图 1.png", "图(2).png", "q.png"):
            assert (tmp_path / "附件" / n).exists()

    def test_windows_case_insensitive_survivor(self, tmp_path):
        """评审 P1-1：存留笔记大小写不同形态引用同一磁盘文件 → 保留。"""
        _att(tmp_path, "Pic.png")
        _mk(tmp_path, "del.md", "![](附件/Pic.png)\n")
        _mk(tmp_path, "keep.md", "![](附件/pic.PNG)\n")
        ok, removed = imp.delete_md_with_attachment_cleanup(tmp_path / "del.md")
        assert ok is True and removed == []
        assert (tmp_path / "附件" / "Pic.png").exists()

    def test_non_image_attachment_never_removed(self, tmp_path):
        """评审 P1-2：MD 链回原件 PDF，删 MD 不得回收非图片附件。"""
        _att(tmp_path, "img_z.png")
        (tmp_path / "附件" / "原稿.pdf").write_bytes(b"%PDF")
        _mk(tmp_path, "z.md", "![](附件/img_z.png)\n[原文](附件/原稿.pdf)\n")
        ok, removed = imp.delete_md_with_attachment_cleanup(tmp_path / "z.md")
        assert ok is True and removed == ["img_z.png"]
        assert (tmp_path / "附件" / "原稿.pdf").exists()

    def test_txt_and_markdown_survivors_counted(self, tmp_path):
        """评审 P1-4：同目录 .txt/.markdown 笔记的引用计入存留。"""
        _att(tmp_path, "img_t.png", "img_m.png")
        _mk(tmp_path, "del.md", "![](附件/img_t.png)\n![](附件/img_m.png)\n")
        _mk(tmp_path, "note.txt", "见附件/img_t.png 即可\n")
        _mk(tmp_path, "note.markdown", "![](附件/img_m.png)\n")
        ok, removed = imp.delete_md_with_attachment_cleanup(tmp_path / "del.md")
        assert ok is True and removed == []
        assert (tmp_path / "附件" / "img_t.png").exists()
        assert (tmp_path / "附件" / "img_m.png").exists()

    def test_txt_note_delete_also_cleans(self, tmp_path):
        """.txt 笔记删除同样走回收（与 bridge 扩展集分流一致）。"""
        _att(tmp_path, "img_o.png")
        t = _mk(tmp_path, "o.txt", "![](附件/img_o.png)\n")
        ok, removed = imp.delete_md_with_attachment_cleanup(t)
        assert ok is True and removed == ["img_o.png"]
        assert not (tmp_path / "附件").exists()  # 空目录随之移除

    def test_partial_encoded_form_survivor(self, tmp_path):
        """图片导入的局部编码形态（中文 raw + 空格 %20）计入存留。"""
        _att(tmp_path, "名片 甲.png")
        _mk(tmp_path, "del.md", "![](附件/名片%20甲.png)\n")
        _mk(tmp_path, "keep.md", "![](附件/名片%20甲.png)\n")
        ok, removed = imp.delete_md_with_attachment_cleanup(tmp_path / "del.md")
        assert ok is True and removed == []
        assert (tmp_path / "附件" / "名片 甲.png").exists()
