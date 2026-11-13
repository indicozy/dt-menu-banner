"""Assemble the banner code and write it into patch_dt.py (dev tool; needs keystone-engine).

The code is assembled at two different bases. Every 32-bit field that differs between the two
is a fixup: an absolute address inside the new section ("abs": add the section's offset) or a
rel32 call/jump to a fixed address in the game ("rel": subtract it). patch_dt.py applies the
fixups for the section address it actually gets, so the patcher itself needs no assembler.

Addresses of DiscordTimes.exe 1.8.1 (Community Update 1.2 build, image base 0x400000) used here:
  0x4797f0  widget constructor (eax = object, edx = VMT)
  0x473ebc  pointer to the hotspot widget VMT the main menu uses
  0x47f6bc  AddChild(eax = window, edx = widget)
  0x6594c8  main menu window
  0x4774a0  ImgNew(ax = w, dx = h) -> eax image (u16 w, u16 h, u16 pixels[w*h])
  0x476374  RGB(al = r, dl = g, cl = b) -> ax, screen pixel format
  0x476ea8  SurfDraw(eax = x, edx = y, ecx = image) onto the locked back buffer
  0x4788ec  TextMeasure(eax = font, edx = pstr, ecx = &w, [stack] &h)
  0x478cac  SurfTextDraw(eax = x, edx = y, ecx = font, [stack] mode, pstr)
  0x476d68  SurfUnlock
  0xae24dc  the font of the menu's copyright line
  0x481420  Sound_Play(eax = sound, dl = restart, cl = loop)
  0xae1244  MainMenuSelect-1 sound, 0xae125c MainMenuPress sound
  0x4f1c44  main window HWND
  0xc0b778  IAT ShellExecuteA, 0xc0b5e0 IAT ShowWindow
Hook sites (patched by patch_dt.py):
  0x4d2a27  BuildMainMenu: `call AddChild; ret` (6 bytes) -> `jmp build_hook; nop`
  0x4c7d24  DrawMainMenuBackground: `call SurfUnlock` (5 bytes) -> `call draw_hook`
"""
import re
import sys
from pathlib import Path

import keystone

# Layout inside the new section (offsets from its start). patch_dt.py fills the data part.
L = dict(
    WIDGET=0x400,   # 0x4c-byte hotspot widget object (0x80 reserved)
    HOVER=0x480,    # byte: cursor over the banner
    INITED=0x481,   # byte: images built
    IMG_N=0x484,    # Image16* normal picture
    IMG_L=0x488,    # Image16* lit picture (gold edge)
    TW=0x48C,       # caption width
    TH=0x490,       # caption height
    OPEN=0x4A0,     # "open\0"
    CAPTION=0x4B0,  # Pascal ShortString, CP1251 (len byte + up to 255 bytes)
    URL=0x5B0,      # C string, up to 255 bytes + NUL
    PIX_N=0x700,    # W*H*3 bytes, R G B, normal picture
)
W, H = 231, 87                     # picture size (half of the 462x174 Steam capsule, as Razdor)
X, Y = 1024 - 16 - W, 658          # right margin 16; bottom 745 = 6 px above the copyright line
L["PIX_L"] = L["PIX_N"] + W * H * 3
RIGHT = 1024 - 16                  # caption right edge
HOT_Y = Y - 20                     # the hotspot also covers the caption line
HOT_H = Y + H - HOT_Y

SRC = """
build_hook:
    call 0x47f6bc
    mov edx, dword ptr [0x473ebc]
    mov eax, {WIDGET}
    call 0x4797f0
    mov byte ptr [{WIDGET}+0x0e], 0
    mov dword ptr [{WIDGET}+0x11], {X}
    mov dword ptr [{WIDGET}+0x15], {HOT_Y}
    mov dword ptr [{WIDGET}+0x19], {W}
    mov dword ptr [{WIDGET}+0x1d], {HOT_H}
    mov dword ptr [{WIDGET}+0x2f], {on_press}
    mov dword ptr [{WIDGET}+0x2b], {on_click}
    mov dword ptr [{WIDGET}+0x43], {on_enter}
    mov dword ptr [{WIDGET}+0x47], {on_leave}
    mov edx, {WIDGET}
    mov eax, 0x6594c8
    call 0x47f6bc
    ret

draw_hook:
    pushal
    cmp byte ptr [{INITED}], 0
    jne draw
    mov byte ptr [{INITED}], 1
    mov esi, {PIX_N}
    call make_img
    mov dword ptr [{IMG_N}], eax
    mov esi, {PIX_L}
    call make_img
    mov dword ptr [{IMG_L}], eax
draw:
    mov ecx, dword ptr [{IMG_N}]
    cmp byte ptr [{HOVER}], 0
    je pic
    mov ecx, dword ptr [{IMG_L}]
pic:
    mov eax, {X}
    mov edx, {Y}
    call 0x476ea8
    push {TH}
    mov ecx, {TW}
    mov edx, {CAPTION}
    mov eax, dword ptr [0xae24dc]
    call 0x4788ec
    push 2
    push {CAPTION}
    mov eax, {RIGHT}
    sub eax, dword ptr [{TW}]
    mov edx, {Y} - 4
    sub edx, dword ptr [{TH}]
    mov ecx, dword ptr [0xae24dc]
    call 0x478cac
    popal
    jmp 0x476d68

make_img:
    mov eax, {W}
    mov edx, {H}
    call 0x4774a0
    push eax
    lea edi, [eax+4]
    mov ebx, {N}
px:
    movzx eax, byte ptr [esi]
    movzx edx, byte ptr [esi+1]
    movzx ecx, byte ptr [esi+2]
    call 0x476374
    stosw
    add esi, 3
    dec ebx
    jnz px
    pop eax
    ret

on_enter:
    mov byte ptr [{HOVER}], 1
    xor ecx, ecx
    mov dl, 1
    mov eax, dword ptr [0xae1244]
    call 0x481420
    ret

on_leave:
    mov byte ptr [{HOVER}], 0
    ret

on_press:
    xor ecx, ecx
    mov dl, 1
    mov eax, dword ptr [0xae125c]
    call 0x481420
    ret

on_click:
    push 1
    push 0
    push 0
    push {URL}
    push {OPEN}
    push 0
    call dword ptr [0xc0b778]
    push 6
    push dword ptr [0x4f1c44]
    call dword ptr [0xc0b5e0]
    ret
"""
LABELS = ["build_hook", "draw_hook", "on_enter", "on_leave", "on_press", "on_click"]


def assemble(base):
    ks = keystone.Ks(keystone.KS_ARCH_X86, keystone.KS_MODE_32)
    # Pass 1 with placeholder handler addresses to find the label offsets.
    offs = {}
    handlers = {n: base for n in LABELS}
    for _ in range(2):
        vals = {k: base + v for k, v in L.items()}
        vals.update(X=X, Y=Y, W=W, H=H, N=W * H, RIGHT=RIGHT, HOT_Y=HOT_Y, HOT_H=HOT_H)
        vals.update(handlers)
        src = SRC.format(**{k: hex(v) for k, v in vals.items()})
        code, _ = ks.asm(src, base)
        code = bytes(code)
        # find label offsets: assemble prefixes up to each label
        for name in LABELS:
            prefix = src.split(f"\n{name}:")[0]
            pc, _ = ks.asm(prefix, base) if prefix.strip() else ([], 0)
            offs[name] = len(pc or [])
        handlers = {n: base + offs[n] for n in LABELS}
    return code, offs


def main():
    a, b = 0x10000000, 0x10010000
    ca, offs = assemble(a)
    cb, offs_b = assemble(b)
    assert offs == offs_b and len(ca) == len(cb)
    assert len(ca) <= L["WIDGET"], "code overlaps the data"
    fix_abs, fix_rel = [], []
    i = 0
    while i < len(ca):
        if ca[i] != cb[i]:
            # the first differing byte may sit inside the 4-byte field (low bytes equal)
            last = max(fix_abs + fix_rel + [-4]) + 4
            for j in range(max(i - 3, last), i + 1):
                va = int.from_bytes(ca[j:j + 4], "little")
                vb = int.from_bytes(cb[j:j + 4], "little")
                if (vb - va) & 0xFFFFFFFF == b - a:
                    fix_abs.append(j)
                    break
                if (va - vb) & 0xFFFFFFFF == b - a:
                    fix_rel.append(j)
                    break
            else:
                sys.exit(f"unexpected difference at {i:#x}")
            i = j + 4
        else:
            i += 1
    # normalise to base 0: abs fields hold the offset, rel fields hold target - (field_end)
    code = bytearray(ca)
    for i in fix_abs:
        v = int.from_bytes(code[i:i + 4], "little") - a
        code[i:i + 4] = (v & 0xFFFFFFFF).to_bytes(4, "little")
    for i in fix_rel:
        v = int.from_bytes(code[i:i + 4], "little") + a
        code[i:i + 4] = (v & 0xFFFFFFFF).to_bytes(4, "little")
    gen = (
        "# --- generated by tools/build_code.py: do not edit by hand ---\n"
        f"CODE = bytes.fromhex(\n    \"{code.hex()}\"\n)\n"
        f"FIX_ABS = {fix_abs}\n"
        f"FIX_REL = {fix_rel}\n"
        f"ENTRY = {offs}\n"
        f"LAYOUT = {{{', '.join(f'{k!r}: {v:#x}' for k, v in L.items())}}}\n"
        f"PIC_W, PIC_H, PIC_X, PIC_Y = {W}, {H}, {X}, {Y}\n"
        "# --- end of generated code ---\n"
    )
    target = Path(__file__).resolve().parent.parent / "patch_dt.py"
    text = target.read_text(encoding="utf-8") if target.exists() else ""
    pat = re.compile(r"# --- generated by tools/build_code.py.*?# --- end of generated code ---\n", re.S)
    if pat.search(text):
        text = pat.sub(lambda _: gen, text)
        target.write_text(text, encoding="utf-8")
        print(f"updated {target}")
    else:
        print(gen)
    print(f"code {len(code)} bytes, abs fixups {len(fix_abs)}, rel fixups {len(fix_rel)}", file=sys.stderr)


if __name__ == "__main__":
    main()
