# -*- coding: utf-8 -*-
"""存量修复：vault 附件中 CMYK JPEG → RGB JPEG 就地重写（2026-11-04 黑图修复）。

判定与 import_service._cmyk_jpeg_to_rgb 同口径：仅处理 PIL 读出 CMYK/YCCK 的
文件；直接转 RGB 近黑则四通道反相复原。文件名不变 → md 引用与库内内容无需动。
"""
import os
import sys
from io import BytesIO

from PIL import Image, ImageStat

sys.stdout.reconfigure(encoding="utf-8")
VAULT = r"e:\LLM\LectureLearnLoop\server\data\vault"

fixed, skipped, dark_kept = 0, 0, 0


def repair_one(path: str) -> None:
    """单文件修复：全程 try 兜底不中断扫描；先写临时文件再原子替换（评审 M2）。"""
    global fixed, skipped, dark_kept
    try:
        im = Image.open(path)
        if im.mode not in ("CMYK", "YCCK"):
            return
        rgb = im.convert("RGB")
        if max(ImageStat.Stat(rgb).mean) < 60:
            inv = Image.merge("CMYK", tuple(ch.point(lambda v: 255 - v)
                                            for ch in im.split()))
            cand = inv.convert("RGB")
            if max(ImageStat.Stat(cand).mean) > max(ImageStat.Stat(rgb).mean):
                rgb = cand
            else:
                dark_kept += 1
        buf = BytesIO()
        rgb.save(buf, format="JPEG", quality=90)
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(buf.getvalue())
        os.replace(tmp, path)
        fixed += 1
    except Exception:  # noqa: BLE001 单文件失败不中断全库扫描
        skipped += 1
        if os.path.exists(path + ".tmp"):
            try:
                os.remove(path + ".tmp")
            except OSError:
                pass


n_files = 0
for root, _dirs, files in os.walk(VAULT):
    for fn in files:
        if fn.lower().endswith((".jpg", ".jpeg")):
            n_files += 1
            repair_one(os.path.join(root, fn))

print(f"扫描 jpg 文件: {n_files}")
print(f"已修复(CMYK→RGB): {fixed}  反相存疑保留直接转换: {dark_kept}  无法打开跳过: {skipped}")
