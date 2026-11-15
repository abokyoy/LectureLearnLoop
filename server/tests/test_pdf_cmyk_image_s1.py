# -*- coding: utf-8 -*-
"""PDF 内嵌 CMYK JPEG 黑图修复（2026-11-04，课本图片全黑根因）。

背景：书籍 PDF（Adobe 排版导出）内嵌图多为 CMYK JPEG 且按"0=满墨"反相存储
（APP14 常错标 YCCK）。旧实现 DCTDecode 原样落盘 → 浏览器不支持 CMYK JPEG，
笔记/预览里成片的黑图（义务教育教科书_数学九年级下册 67/68 张实测复现）。

修复口径：DCTDecode 不再无脑透传，CMYK/YCCK 图用 PIL 解码后转 RGB 存盘；
近黑图（直接转换均值过低）按四通道反相复原；RGB/L 图保持原样透传不重编码。
另：非 DCT 路径的 CMYK 位图存 PNG 前同样必须转 RGB（PNG-CMYK 浏览器也不显示）。

运行（server/ 目录）：python -m pytest tests/test_pdf_cmyk_image_s1.py -v
"""
import sys
from pathlib import Path
from io import BytesIO

import pytest
from PIL import Image, ImageStat

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import import_service as imp  # noqa: E402


class FakeXObj:
    """最小 pypdf 图像对象替身：get/下标/get_data 三个接口。"""

    def __init__(self, data: bytes, filt: str, w: int, h: int, cs=None, bpc=8):
        self._d = {"/Filter": filt, "/Width": w, "/Height": h,
                   "/BitsPerComponent": bpc}
        if cs is not None:
            self._d["/ColorSpace"] = cs
        self._data = data

    def get(self, key, default=None):
        return self._d.get(key, default)

    def __getitem__(self, key):
        return self._d[key]

    def get_data(self, apply_predictor=False):
        return self._data


def _make_inverted_cmyk_jpeg(w=120, h=80) -> bytes:
    """构造反相存储的 CMYK JPEG：正片是白底黑字，存储值四通道全反。"""
    good = Image.new("RGB", (w, h), "white")
    for x in range(w // 4, w // 4 * 3):
        for y in range(h // 3, h // 3 * 2):
            good.putpixel((x, y), (0, 0, 0))
    cmyk = good.convert("CMYK")
    c, m, y, k = cmyk.split()
    inv = Image.merge("CMYK", tuple(ch.point(lambda v: 255 - v)
                                    for ch in (c, m, y, k)))
    buf = BytesIO()
    inv.save(buf, format="JPEG")
    return buf.getvalue()


def _mean(img: Image.Image) -> float:
    return max(ImageStat.Stat(img.convert("RGB")).mean)


# ---------------------------------------------------------------- DCTDecode

def test_cmyk_jpeg_repaired_not_black(tmp_path):
    """反相 CMYK JPEG 经 _save_pdf_image 落盘后必须是亮底图（旧实现原样透传→黑）。"""
    data = _make_inverted_cmyk_jpeg()
    # 前置自证：原始字节直接打开转 RGB 确实近黑（复现 bug 形态）
    raw = Image.open(BytesIO(data))
    assert raw.mode == "CMYK"
    assert _mean(raw) < 60, "构造样张应直接转换为黑，否则样本无效"

    xob = FakeXObj(data, "/DCTDecode", 120, 80, cs="/DeviceCMYK")
    name = imp._save_pdf_image(xob, tmp_path, "img_t_0_1")
    assert name and name.endswith(".jpg")
    out = Image.open(tmp_path / name)
    assert out.mode in ("RGB", "L", "P", "RGBA")
    assert _mean(out) > 120, f"修复后应恢复白底，实际均值 {_mean(out):.1f}"
    # 黑块仍在：反相复原后中心区域应显著暗于整体
    px = out.convert("L").load()
    dark = sum(1 for x in range(35, 85) for y in range(30, 50) if px[x, y] < 100)
    assert dark > (85 - 35) * (50 - 30) * 0.7, "黑字内容应保留（不能整图刷白）"


def test_rgb_jpeg_passthrough(tmp_path):
    """RGB JPEG 保持原样透传（不重编码、不损画质）。"""
    buf = BytesIO()
    Image.new("RGB", (60, 40), "white").save(buf, format="JPEG")
    data = buf.getvalue()
    xob = FakeXObj(data, "/DCTDecode", 60, 40, cs="/DeviceRGB")
    name = imp._save_pdf_image(xob, tmp_path, "img_t_0_2")
    assert name
    assert (tmp_path / name).read_bytes() == data


def test_legit_dark_cmyk_not_inverted(tmp_path):
    """合法暗图（K 通道占重的夜空类）不得被反相成亮图（评审 m3 回归线）。"""
    buf = BytesIO()
    Image.new("RGB", (60, 40), (25, 25, 30)).convert("CMYK").save(buf, format="JPEG")
    xob = FakeXObj(buf.getvalue(), "/DCTDecode", 60, 40, cs="/DeviceCMYK")
    name = imp._save_pdf_image(xob, tmp_path, "img_t_0_4")
    assert name
    out = Image.open(tmp_path / name)
    assert _mean(out) < 60, f"暗图应保持暗，实际均值 {_mean(out):.1f}"


# ---------------------------------------------------------------- 位图路径

def test_raw_cmyk_bitmap_saved_as_rgb(tmp_path):
    """非 DCT 的 CMYK 位图存 PNG 前必须转 RGB（CMYK PNG 浏览器同样不显示）。"""
    w, h = 10, 8
    data = bytes([255] * (w * h * 4))  # 反相存储的白底（全 255）
    xob = FakeXObj(data, "/FlateDecode", w, h, cs="/DeviceCMYK")
    name = imp._save_pdf_image(xob, tmp_path, "img_t_0_3")
    assert name
    out = Image.open(tmp_path / name)
    assert out.mode != "CMYK", "落盘不得保留 CMYK 模式"
