#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for patch_dt.py (standard library only).

The end-to-end tests run on the real exe when DT_EXE points to it; they copy it into a
temporary folder first, so the original is never touched.
"""
import contextlib
import io
import os
import random
import shutil
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import patch_dt  # noqa: E402
from patch_dt import (  # noqa: E402
    CODE, ENTRY, FIX_ABS, FIX_REL, LAYOUT, PIC_H, PIC_W, PatchError,
    decode_png, make_pictures, resize_rgb, encode_caption, encode_url, pe_checksum,
)

CAPSULE = ROOT / "capsule.png"


# ---------------------------------------------------------------- PNG helpers

def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _filter_row(ftype, raw, prev, bpp):
    out = bytearray(len(raw))
    for i in range(len(raw)):
        left = raw[i - bpp] if i >= bpp else 0
        up = prev[i]
        upleft = prev[i - bpp] if i >= bpp else 0
        if ftype == 0:
            pred = 0
        elif ftype == 1:
            pred = left
        elif ftype == 2:
            pred = up
        elif ftype == 3:
            pred = (left + up) // 2
        else:
            pred = _paeth(left, up, upleft)
        out[i] = (raw[i] - pred) & 0xFF
    return bytes(out)


def _chunk(ctype, body):
    return (struct.pack(">I", len(body)) + ctype + body
            + struct.pack(">I", zlib.crc32(ctype + body) & 0xFFFFFFFF))


def make_png(width, height, rows_rgb_or_rgba, colour_type, filters=None, bit_depth=8,
             interlace=0, zlib_level=6):
    """Build a PNG in memory. rows are lists of byte tuples; filters[y] picks the filter per row."""
    bpp = 3 if colour_type == 2 else 4
    stride = width * bpp
    raw = bytearray()
    prev = bytes(stride)
    for y in range(height):
        row = bytearray()
        for px in rows_rgb_or_rgba[y]:
            row += bytes(px)
        row = bytes(row)
        ftype = filters[y] if filters else 0
        raw += bytes([ftype]) + _filter_row(ftype, row, prev, bpp)
        prev = row
    ihdr = struct.pack(">IIBBBBB", width, height, bit_depth, colour_type, 0, 0, interlace)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(bytes(raw), zlib_level)) + _chunk(b"IEND", b""))


def _random_rows(rng, width, height, bpp):
    return [[tuple(rng.randrange(256) for _ in range(bpp)) for _ in range(width)] for _ in range(height)]


class PngDecoderTests(unittest.TestCase):

    def test_rgb_all_five_filters(self):
        rng = random.Random(1)
        w, h = 7, 5
        rows = _random_rows(rng, w, h, 3)
        filters = [0, 1, 2, 3, 4]
        png = make_png(w, h, rows, 2, filters=filters)
        dw, dh, rgb = decode_png(png)
        self.assertEqual((dw, dh), (w, h))
        expected = bytes(c for row in rows for px in row for c in px)
        self.assertEqual(rgb, expected)

    def test_rgb_filters_mixed_per_row_and_compressed_level_zero(self):
        rng = random.Random(2)
        w, h = 11, 9
        rows = _random_rows(rng, w, h, 3)
        filters = [(y * 3) % 5 for y in range(h)]
        png = make_png(w, h, rows, 2, filters=filters, zlib_level=0)
        _, _, rgb = decode_png(png)
        self.assertEqual(rgb, bytes(c for row in rows for px in row for c in px))

    def test_rgba_is_composited_on_black(self):
        # alpha 255 keeps the colour, 0 gives black, 128 halves it (rounded)
        rows = [[(200, 100, 50, 255), (200, 100, 50, 0)],
                [(255, 255, 255, 128), (10, 20, 30, 255)]]
        for filters in ([0, 0], [1, 2], [3, 4], [4, 1]):
            png = make_png(2, 2, rows, 6, filters=filters)
            w, h, rgb = decode_png(png)
            self.assertEqual((w, h), (2, 2))
            self.assertEqual(rgb[0:3], bytes((200, 100, 50)))
            self.assertEqual(rgb[3:6], bytes((0, 0, 0)))
            self.assertEqual(rgb[6:9], bytes((128, 128, 128)))
            self.assertEqual(rgb[9:12], bytes((10, 20, 30)))

    def test_rgba_all_filters_random(self):
        rng = random.Random(3)
        w, h = 6, 5
        rows = _random_rows(rng, w, h, 4)
        png = make_png(w, h, rows, 6, filters=[0, 1, 2, 3, 4])
        _, _, rgb = decode_png(png)
        expected = bytearray()
        for row in rows:
            for r, g, b, a in row:
                expected += bytes(((r * a + 127) // 255, (g * a + 127) // 255, (b * a + 127) // 255))
        self.assertEqual(rgb, bytes(expected))

    def test_refuses_bad_crc(self):
        png = bytearray(make_png(2, 1, [[(1, 2, 3), (4, 5, 6)]], 2))
        png[8 + 8 + 13] ^= 0xFF  # corrupt the IHDR CRC
        with self.assertRaises(PatchError):
            decode_png(bytes(png))

    def test_refuses_interlaced(self):
        png = make_png(2, 1, [[(1, 2, 3), (4, 5, 6)]], 2, interlace=1)
        with self.assertRaises(PatchError):
            decode_png(png)

    def test_refuses_palette_and_16_bit(self):
        with self.assertRaises(PatchError):
            decode_png(make_png(2, 1, [[(1, 2, 3), (4, 5, 6)]], 3))
        with self.assertRaises(PatchError):
            decode_png(make_png(2, 1, [[(1, 2, 3), (4, 5, 6)]], 2, bit_depth=16))

    def test_refuses_not_png(self):
        with self.assertRaises(PatchError):
            decode_png(b"GIF89a" + bytes(20))

    def test_capsule_decodes_to_462x174(self):
        w, h, rgb = decode_png(CAPSULE.read_bytes())
        self.assertEqual((w, h), (462, 174))
        self.assertEqual(len(rgb), 462 * 174 * 3)


class ResizeTests(unittest.TestCase):

    def test_box_2x_exact_values(self):
        # 4x2 source -> 2x1 output; each output pixel averages a 2x2 block
        rgb = bytes([
            0, 0, 0,    10, 10, 10,   255, 0, 0,   255, 0, 0,
            20, 20, 20, 30, 30, 30,   0, 255, 0,   0, 255, 0,
        ])
        # right block: red and green halves -> (255+255+0+0)/4 = 127.5 -> 128 (round half up)
        self.assertEqual(resize_rgb(4, 2, rgb, 2, 1),
                         bytes([15, 15, 15, 128, 128, 0]))

    def test_box_2x_rounds_half_up(self):
        # first output pixel's block: R values 1, 2 / 2, 2 -> 7/4 = 1.75 -> 2
        rgb = bytes([1, 0, 0, 2, 0, 0, 9, 0, 0, 9, 0, 0,
                     2, 0, 0, 2, 0, 0, 9, 0, 0, 9, 0, 0])
        self.assertEqual(resize_rgb(4, 2, rgb, 2, 1)[0], 2)

    def test_area_average_general_path(self):
        # 3x1 -> 1x1: (0 + 0 + 255) / 3 = 85 exactly
        rgb = bytes([0, 0, 0, 0, 0, 0, 255, 255, 255])
        self.assertEqual(resize_rgb(3, 1, rgb, 1, 1), bytes([85, 85, 85]))

    def test_area_average_identity(self):
        rgb = bytes(range(3 * 4 * 2))
        self.assertEqual(resize_rgb(4, 2, rgb, 4, 2), rgb)


class PictureTests(unittest.TestCase):

    def test_ring_colours(self):
        white = bytes([255, 255, 255]) * (462 * 174)
        normal, lit = make_pictures(462, 174, white)
        self.assertEqual(len(normal), PIC_W * PIC_H * 3)
        self.assertEqual(len(lit), PIC_W * PIC_H * 3)

        def px(buf, x, y):
            i = (y * PIC_W + x) * 3
            return tuple(buf[i:i + 3])

        dark, gold, white_px = (20, 13, 8), (255, 209, 107), (255, 255, 255)
        self.assertEqual(px(normal, 0, 0), dark)
        self.assertEqual(px(normal, PIC_W - 1, 40), dark)
        self.assertEqual(px(normal, 1, 40), white_px)
        self.assertEqual(px(lit, 0, 40), dark)
        self.assertEqual(px(lit, 1, 40), gold)
        self.assertEqual(px(lit, 2, 40), gold)
        self.assertEqual(px(lit, 3, 40), white_px)
        self.assertEqual(px(lit, PIC_W - 2, 40), gold)
        self.assertEqual(px(lit, 40, PIC_H - 3), gold)
        self.assertEqual(px(lit, 40, PIC_H - 4), white_px)
        self.assertEqual(px(lit, 40, 0), dark)


class ValidationTests(unittest.TestCase):

    def test_default_caption_and_url_pass(self):
        self.assertEqual(encode_caption(patch_dt.DEFAULT_CAPTION).decode("cp1251"),
                         patch_dt.DEFAULT_CAPTION)
        self.assertEqual(encode_url(patch_dt.DEFAULT_URL), patch_dt.DEFAULT_URL.encode("ascii"))

    def test_caption_refuses_characters_outside_font(self):
        with self.assertRaises(PatchError):
            encode_caption("«Времена»")  # French quotes are not in the font
        with self.assertRaises(PatchError):
            encode_caption("Hello, World #1")  # '#' is not in the glyph set

    def test_caption_length_limit(self):
        encode_caption("а" * 255)
        with self.assertRaises(PatchError):
            encode_caption("а" * 256)

    def test_caption_empty_refused(self):
        with self.assertRaises(PatchError):
            encode_caption("")

    def test_url_rules(self):
        with self.assertRaises(PatchError):
            encode_url("ftp://example.com/")
        with self.assertRaises(PatchError):
            encode_url("https://example.com/я")
        with self.assertRaises(PatchError):
            encode_url("https://example.com/a b")
        with self.assertRaises(PatchError):
            encode_url("https://example.com/" + "a" * 240)


# ---------------------------------------------------------------- end to end on the real exe

def _sections(data):
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    nsec = struct.unpack_from("<H", data, e_lfanew + 6)[0]
    opt_size = struct.unpack_from("<H", data, e_lfanew + 20)[0]
    opt = e_lfanew + 24
    table = opt + opt_size
    secs = []
    for i in range(nsec):
        f = struct.unpack_from("<8sIIIIIIHHI", data, table + 40 * i)
        secs.append(dict(name=f[0].rstrip(b"\0"), vsize=f[1], va=f[2], rawsize=f[3],
                         rawptr=f[4], chars=f[9], hdr=table + 40 * i))
    return dict(e_lfanew=e_lfanew, opt=opt, nsec=nsec, sections=secs,
                size_of_image=struct.unpack_from("<I", data, opt + 56)[0],
                section_align=struct.unpack_from("<I", data, opt + 32)[0],
                file_align=struct.unpack_from("<I", data, opt + 36)[0],
                checksum=struct.unpack_from("<I", data, opt + 64)[0])


def _off(data, va):
    """File offset of a VA through the original section table (test-side, independent of patch_dt)."""
    rva = va - 0x400000
    for s in _sections(data)["sections"]:
        if s["va"] <= rva < s["va"] + max(s["vsize"], 1) and rva < s["va"] + s["rawsize"]:
            return s["rawptr"] + rva - s["va"]
    raise AssertionError("no section for %#x" % va)


class EndToEndTests(unittest.TestCase):
    """Runs only when DT_EXE is set to a DiscordTimes.exe build."""

    @classmethod
    def setUpClass(cls):
        exe = os.environ.get("DT_EXE")
        if not exe or not os.path.isfile(exe):
            raise unittest.SkipTest("set DT_EXE to a DiscordTimes.exe to run the end-to-end tests")
        cls.original = Path(exe).read_bytes()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.exe = Path(self.tmp.name) / "DiscordTimes.exe"
        self.exe.write_bytes(self.original)
        self.bak = Path(self.tmp.name) / "DiscordTimes.exe.bak"

    def _patch(self):
        patch_dt.patch(self.exe, str(CAPSULE), log=lambda s: None)
        return self.exe.read_bytes()

    def test_new_section_header_fields(self):
        before = _sections(self.original)
        out = self._patch()
        after = _sections(out)
        self.assertEqual(after["nsec"], before["nsec"] + 1)
        new = after["sections"][-1]
        self.assertEqual(new["name"], b".banner")
        self.assertEqual(new["chars"], 0xE0000060)
        va = patch_dt.align_up(before["size_of_image"], before["section_align"])
        self.assertEqual(new["va"], va)
        content_len = LAYOUT["PIX_L"] + PIC_W * PIC_H * 3
        self.assertEqual(new["vsize"], content_len)
        self.assertEqual(new["rawptr"], patch_dt.align_up(len(self.original), before["file_align"]))
        self.assertEqual(new["rawsize"], patch_dt.align_up(content_len, before["file_align"]))
        self.assertEqual(new["rawsize"] % before["file_align"], 0)
        self.assertEqual(after["size_of_image"],
                         patch_dt.align_up(va + content_len, before["section_align"]))
        # the old sections are untouched
        for old, now in zip(before["sections"], after["sections"]):
            self.assertEqual(old["name"], now["name"])
            self.assertEqual(old["rawptr"], now["rawptr"])
        # the new header slot was free space in the original
        self.assertEqual(self.original[new["hdr"]:new["hdr"] + 40], bytes(40))

    def test_hooks_jump_to_entries(self):
        before = _sections(self.original)
        out = self._patch()
        va = patch_dt.align_up(before["size_of_image"], before["section_align"])
        S = 0x400000 + va
        off = _off(self.original, 0x4D2A27)
        self.assertEqual(out[off], 0xE9)
        rel = struct.unpack_from("<i", out, off + 1)[0]
        self.assertEqual(0x4D2A27 + 5 + rel, S + ENTRY["build_hook"])
        self.assertEqual(out[off + 5], 0x90)
        off = _off(self.original, 0x4C7D24)
        self.assertEqual(out[off], 0xE8)
        rel = struct.unpack_from("<i", out, off + 1)[0]
        self.assertEqual(0x4C7D24 + 5 + rel, S + ENTRY["draw_hook"])
        # every other byte of the two hook sites is what the original had after the hook
        self.assertEqual(out[_off(self.original, 0x4D2A27) + 6:_off(self.original, 0x4D2A27) + 8],
                         self.original[_off(self.original, 0x4D2A27) + 6:_off(self.original, 0x4D2A27) + 8])

    def test_section_code_is_code_with_fixups(self):
        before = _sections(self.original)
        out = self._patch()
        new = _sections(out)["sections"][-1]
        va = patch_dt.align_up(before["size_of_image"], before["section_align"])
        S = 0x400000 + va
        raw = bytearray(out[new["rawptr"]:new["rawptr"] + len(CODE)])
        for off in FIX_ABS:
            v = struct.unpack_from("<I", raw, off)[0]
            struct.pack_into("<I", raw, off, (v - S) & 0xFFFFFFFF)
        for off in FIX_REL:
            v = struct.unpack_from("<I", raw, off)[0]
            struct.pack_into("<I", raw, off, (v + S) & 0xFFFFFFFF)
        self.assertEqual(bytes(raw), CODE)
        # build_hook starts with `call AddChild` (0x47f6bc)
        self.assertEqual(CODE[0], 0xE8)
        rel = struct.unpack_from("<i", out, new["rawptr"] + 1)[0]
        self.assertEqual(S + 5 + rel, 0x47F6BC)

    def test_fixup_offsets_are_inside_code(self):
        for off in FIX_ABS + FIX_REL:
            self.assertLessEqual(off + 4, len(CODE))
        for name, off in ENTRY.items():
            self.assertLess(off, len(CODE), name)

    def test_data_fields(self):
        before = _sections(self.original)
        out = self._patch()
        new = _sections(out)["sections"][-1]
        base = new["rawptr"]
        self.assertEqual(out[base + LAYOUT["OPEN"]:base + LAYOUT["OPEN"] + 5], b"open\0")
        cap = patch_dt.DEFAULT_CAPTION.encode("cp1251")
        self.assertEqual(out[base + LAYOUT["CAPTION"]], len(cap))
        self.assertEqual(out[base + LAYOUT["CAPTION"] + 1:base + LAYOUT["CAPTION"] + 1 + len(cap)], cap)
        url = patch_dt.DEFAULT_URL.encode("ascii")
        self.assertEqual(out[base + LAYOUT["URL"]:base + LAYOUT["URL"] + len(url) + 1], url + b"\0")
        w, h, rgb = decode_png(CAPSULE.read_bytes())
        normal, lit = make_pictures(w, h, rgb)
        n = PIC_W * PIC_H * 3
        self.assertEqual(out[base + LAYOUT["PIX_N"]:base + LAYOUT["PIX_N"] + n], normal)
        self.assertEqual(out[base + LAYOUT["PIX_L"]:base + LAYOUT["PIX_L"] + n], lit)

    def test_checksum_is_correct(self):
        out = self._patch()
        stored = _sections(out)["checksum"]
        self.assertEqual(stored, pe_checksum(out, _sections(out)["opt"] + 64))
        self.assertNotEqual(stored, 0)

    def test_backup_then_second_run_refused_then_restore(self):
        self._patch()
        self.assertTrue(self.bak.is_file())
        self.assertEqual(self.bak.read_bytes(), self.original)
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = patch_dt.main([str(self.exe), "--image", str(CAPSULE)])
        self.assertNotEqual(code, 0)
        self.assertIn("--restore", err.getvalue())
        self.assertEqual(self.bak.read_bytes(), self.original)

        with contextlib.redirect_stdout(io.StringIO()):
            code = patch_dt.main([str(self.exe), "--restore"])
        self.assertEqual(code, 0)
        self.assertEqual(self.exe.read_bytes(), self.original)
        self.assertFalse(self.bak.exists())

    def test_patched_file_refused_by_checks(self):
        out = self._patch()
        with self.assertRaises(PatchError) as cm:
            patch_dt.build_patched(out, CAPSULE.read_bytes(), patch_dt.DEFAULT_URL,
                                   patch_dt.DEFAULT_CAPTION)
        self.assertIn(".banner", str(cm.exception))

    def test_cli_refuses_missing_bak_on_restore(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = patch_dt.main([str(self.exe), "--restore"])
        self.assertNotEqual(code, 0)
        self.assertEqual(self.exe.read_bytes(), self.original)

    def test_wrong_bytes_refused(self):
        bad = bytearray(self.original)
        off = _off(self.original, 0x4797F0)
        bad[off] ^= 0x01
        with self.assertRaises(PatchError):
            patch_dt.build_patched(bytes(bad), CAPSULE.read_bytes(), patch_dt.DEFAULT_URL,
                                   patch_dt.DEFAULT_CAPTION)

    def test_overlay_kept_and_new_section_after_it(self):
        end = max(s["rawptr"] + s["rawsize"] for s in _sections(self.original)["sections"])
        out = self._patch()
        self.assertEqual(out[end:len(self.original)], self.original[end:])
        new = _sections(out)["sections"][-1]
        self.assertGreaterEqual(new["rawptr"], len(self.original))

    def test_truncated_file_refused(self):
        end = max(s["rawptr"] + s["rawsize"] for s in _sections(self.original)["sections"])
        with self.assertRaises(PatchError):
            patch_dt.build_patched(self.original[:end - 1], CAPSULE.read_bytes(),
                                   patch_dt.DEFAULT_URL, patch_dt.DEFAULT_CAPTION)


if __name__ == "__main__":
    unittest.main()
