"""End-to-end tests of FLASHROM.BIN and the DOS utilities on the emulated PC and card (tools/emu/emu86.py).

Usage:  python tools/build_dos.py <nasm>      (builds dist/)
        python tools/emu/test_isaflash.py
Needs the Unicorn engine importable (pip install unicorn==2.1.4, or ISAFLASH_PYLIB=<dir with unicorn>).
"""

import os
import random
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if os.environ.get("ISAFLASH_PYLIB"):
    sys.path.insert(0, os.environ["ISAFLASH_PYLIB"])
sys.path.insert(0, HERE)

import emu86  # noqa: E402
from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_BX, UC_X86_REG_CX, UC_X86_REG_DX, UC_X86_REG_ES, \
    UC_X86_REG_EFLAGS, UC_X86_REG_CS, UC_X86_REG_IP  # noqa: E402

DIST = os.path.join(ROOT, "dist")
FAILS = []


def check(cond, what):
    print(("PASS  " if cond else "FAIL  ") + what)
    if not cond:
        FAILS.append(what)


def com(name):
    with open(os.path.join(DIST, name), "rb") as f:
        return f.read()


def make_disk(sectors, seed):
    rnd = random.Random(seed)
    data = bytearray(rnd.getrandbits(8) for _ in range(sectors * 512))
    data[0:2] = bytes([0xCD, emu86.STOP_INT])   # "boot code": stops the emulator at 0000:7C02
    data[510:512] = b"\x55\xaa"
    return data


def chs_of(lba, heads=4, spt=16):
    c, rem = divmod(lba, heads * spt)
    h, s = divmod(rem, spt)
    return c, h, s + 1


def int13_read(pc, lba, count, buf_seg=0x5000, buf_off=0x0007, drive=0x80):
    c, h, s = chs_of(lba)
    regs = {UC_X86_REG_AX: 0x0200 | count, UC_X86_REG_CX: ((c & 0xFF) << 8) | ((c >> 2) & 0xC0) | s,
            UC_X86_REG_DX: (h << 8) | drive, UC_X86_REG_ES: buf_seg, UC_X86_REG_BX: buf_off}
    pc.call_int(0x13, regs)
    ax = pc.r(UC_X86_REG_AX)
    cf = pc.r(UC_X86_REG_EFLAGS) & 1
    return ax, cf, pc.read(pc.lin(buf_seg, buf_off), count * 512)


def inv(data):
    """Disk format 2 stores every byte inverted."""
    return bytes(b ^ 0xFF for b in data)


def int13_write(pc, lba, data, buf_seg=0x5000, buf_off=0x0007, drive=0x80):
    count = len(data) // 512
    pc.uc.mem_write(pc.lin(buf_seg, buf_off), bytes(data))
    c, h, s = chs_of(lba)
    regs = {UC_X86_REG_AX: 0x0300 | count, UC_X86_REG_CX: ((c & 0xFF) << 8) | ((c >> 2) & 0xC0) | s,
            UC_X86_REG_DX: (h << 8) | drive, UC_X86_REG_ES: buf_seg, UC_X86_REG_BX: buf_off}
    pc.call_int(0x13, regs)
    return pc.r(UC_X86_REG_AX), pc.r(UC_X86_REG_EFLAGS) & 1


def make_floppy(dos3):
    """A 360 KB FAT12 floppy with IO.SYS, MSDOS.SYS, COMMAND.COM. The boot code is only 'int 0FDh' at the jump
    target: enough to check what mkdisk patches, not a real DOS."""
    img = bytearray(720 * 512)
    target = 0x36 if dos3 else 0x3E
    img[0:3] = bytes([0xEB, target - 2, 0x90])
    img[3:11] = b"MSDOS3.3" if dos3 else b"MSDOS5.0"
    struct.pack_into("<HBHBHHBHHHH", img, 0x0B, 512, 2, 1, 2, 112, 720, 0xFD, 2, 9, 2, 0)
    if not dos3:
        img[0x24], img[0x26] = 0, 0x29
    img[target:target + 2] = bytes([0xCD, emu86.STOP_INT])
    img[0x1F0:0x1FD] = b"BOOT CODE END"
    img[510:512] = b"\x55\xaa"
    fat, root, data = 512, 512 * 5, 512 * 12
    img[fat:fat + 3] = bytes([0xFD, 0xFF, 0xFF])
    clus = 2
    for i, (name, size) in enumerate((("IO      SYS", 3000), ("MSDOS   SYS", 5000), ("COMMANDCOM", 1500))):
        n = (size + 1023) // 1024
        e = name.encode("ascii") + bytes([0x07 if i < 2 else 0x20]) + bytes(14) + struct.pack("<HI", clus, size)
        img[root + 32 * i:root + 32 * i + 32] = e
        for k in range(n):
            c, v = clus + k, (clus + k + 1 if k < n - 1 else 0xFFF)
            off = fat + c * 3 // 2
            cur = struct.unpack_from("<H", img, off)[0]
            cur = (cur & 0x000F) | (v << 4) if c & 1 else (cur & 0xF000) | v
            struct.pack_into("<H", img, off, cur)
        off = data + (clus - 2) * 1024
        img[off:off + size] = bytes([0x41 + i]) * size
        clus += n
    return bytes(img)


def scenario(chips, port, window, tmp):
    print("\n=== %d chip(s), port %03Xh, window %04Xh ===" % (chips, port, window))
    total = chips * 2048 - 256
    cyls = total // 64
    args = "" if (port, window) == (0x2A0, 0xCC00) else " /M:%04X /P:%X" % (window, port)
    rom = com("FLASHROM.BIN")
    with open(os.path.join(tmp, "FLASHROM.BIN"), "wb") as f:
        f.write(rom)

    # 1. WRITE jumper removed: FLFORMAT must refuse and leave the flash untouched
    card = emu86.Card(chips=chips, jumper=False, port=port, window=window)
    pc = emu86.PC(card, tmp)
    code, out = pc.run_com(com("FLFORMAT.COM"), "FLASHROM.BIN /Y" + args)
    check(code == 1 and "VPP is low" in out, "FLFORMAT without JP1 stops with 'VPP is low'")
    check(card.image() == b"\xff" * (chips << 20), "flash unchanged without JP1")
    check(card.bank == 0 and card.ctrl == 0, "card left with BANK=0, CTRL=0")

    # 2. FLFORMAT with the jumper
    card.jumper = True
    code, out = pc.run_com(com("FLFORMAT.COM"), "FLASHROM.BIN /Y /E" + args)
    check(code == 0, "FLFORMAT exit code 0")
    img = card.flash[0].mem
    check(img[0:2] == b"\x55\xaa" and img[8:16] == b"ISAFLASH", "ROM image in bank 0")
    check(struct.unpack_from("<H", img, 0x10)[0] == port, "ROM header holds port %03Xh" % port)
    check(sum(img[0:0x2000]) & 0xFF == 0, "ROM checksum is zero")
    d = img[0x2000:0x2200]
    check(d[0:8] == b"ISAFLDSK" and sum(d) & 0xFF == 0, "descriptor signature and checksum")
    check(struct.unpack_from("<HHHHH", d, 0x0C) == (cyls, 4, 16, total, 128),
          "descriptor geometry %d/4/16, %d sectors" % (cyls, total))
    check(struct.unpack_from("<H", d, 0x08)[0] == 2 and d[0x16] == chips * 16 - 1,
          "descriptor format 2, spare block %d" % (chips * 16 - 1))
    check(card.bank == 0 and card.ctrl == 0, "card left with BANK=0, CTRL=0")

    # 3. FLINFO finds the ROM by itself (no /M /P), reads the jumper
    code, out = pc.run_com(com("FLINFO.COM"), "/J")
    check(code == 0 and "port in ROM %04Xh" % port in out, "FLINFO finds the ROM and its port")
    check(("%d/4/16" % cyls) in out and ("%d sectors" % total) in out, "FLINFO reports the geometry")
    check("JP1: fitted" in out, "FLINFO /J sees the jumper")
    check("format 2, spare block %d" % (chips * 16 - 1) in out, "FLINFO reports format 2 and the spare block")
    check(("2 x 28F008SA" if chips == 2 else "1 x 28F008SA") in out, "FLINFO counts %d chip(s)" % chips)

    # 4. FLWRITE /D a disk image, again unchanged, then a change that needs an erase
    disk = make_disk(total, seed=chips)
    with open(os.path.join(tmp, "DISK.IMG"), "wb") as f:
        f.write(disk)
    code, out = pc.run_com(com("FLWRITE.COM"), "DISK.IMG /D /Y")
    check(code == 0 and "FAILED" not in out, "FLWRITE /D exit code 0")
    check(card.image()[0x10000:0x10000 + len(disk)] == inv(disk), "flash data area holds the image inverted")
    code, out = pc.run_com(com("FLWRITE.COM"), "DISK.IMG /D /Y")
    blocks = (len(disk) + 0xFFFF) // 0x10000
    check(code == 0 and out.count("unchanged") == blocks, "second FLWRITE: all %d blocks unchanged" % blocks)
    disk2 = bytearray(disk)
    disk2[0x23456] ^= 0xFF                      # some bits 0 -> 1: block needs an erase
    with open(os.path.join(tmp, "DISK2.IMG"), "wb") as f:
        f.write(disk2)
    erases_before = card.flash[0].erases + sum(f.erases for f in card.flash[1:])
    code, out = pc.run_com(com("FLWRITE.COM"), "DISK2.IMG /D /Y")
    erases = card.flash[0].erases + sum(f.erases for f in card.flash[1:]) - erases_before
    check(code == 0 and out.count("erased, programmed, verified") == 1 and erases == 1,
          "changed byte: exactly one block erased and rewritten")
    check(card.image()[0x10000:0x10000 + len(disk2)] == inv(disk2), "flash holds the changed image")
    check(card.image()[(chips * 16 - 1) << 16:chips << 20] == b"\xff" * 0x10000, "FLWRITE /D leaves the spare block")

    # 5. FLREAD /D and full
    code, out = pc.run_com(com("FLREAD.COM"), "BACK.IMG /D")
    with open(os.path.join(tmp, "BACK.IMG"), "rb") as f:
        back = f.read()
    check(code == 0 and back[:len(disk2)] == bytes(disk2) and len(back) == total * 512, "FLREAD /D returns the disk")
    code, out = pc.run_com(com("FLREAD.COM"), "FULL.BIN")
    with open(os.path.join(tmp, "FULL.BIN"), "rb") as f:
        full = f.read()
    check(code == 0 and full == card.image(), "FLREAD returns the whole flash")

    # 6. Option ROM: BIOS-style far call to window:0003
    pc = emu86.PC(card, tmp)
    card.bank, card.ctrl = 0, 0
    out = pc.far_call(window, 3)
    check("ISA Flash Disk: %d KB, drive 80h, port %04Xh, ROM %05Xh" % (total // 2, port, window * 16) in out,
          "ROM banner: %r" % out.strip())
    base_kb = struct.unpack("<H", pc.read(0x413, 2))[0]
    check(base_kb == 638, "base memory reduced to 638 KB")
    check(pc.read(0x475, 1)[0] == 1, "hard disk count 1")
    vec13 = struct.unpack("<HH", pc.read(0x13 * 4, 4))
    vec19 = struct.unpack("<HH", pc.read(0x19 * 4, 4))
    check(vec13[1] == 638 * 64 and vec19[1] == 638 * 64, "INT 13h and INT 19h point into the reserved 2 KB")
    check(card.bank == 0 and card.ctrl == 0, "ROM init leaves BANK=0, CTRL=0")

    # 7. INT 13h
    pc.call_int(0x13, {UC_X86_REG_AX: 0x0800, UC_X86_REG_DX: 0x0080})
    cx, dx = pc.r(UC_X86_REG_CX), pc.r(UC_X86_REG_DX)
    maxcyl = ((cx & 0xC0) << 2) | (cx >> 8)
    check((pc.r(UC_X86_REG_EFLAGS) & 1) == 0 and maxcyl == cyls - 1 and (cx & 0x3F) == 16 and (dx >> 8) == 3
          and (dx & 0xFF) == 1, "AH=08h geometry %d/4/16, 1 drive" % cyls)
    pc.call_int(0x13, {UC_X86_REG_AX: 0x1500, UC_X86_REG_DX: 0x0080})
    check((pc.r(UC_X86_REG_AX) >> 8) == 3 and pc.r(UC_X86_REG_DX) == total, "AH=15h fixed disk, %d sectors" % total)
    ax, cf, data = int13_read(pc, 0, 1)
    check(cf == 0 and ax == 0x0001 and data == bytes(disk2[0:512]), "read sector 0")
    ax, cf, data = int13_read(pc, 13, 40, buf_seg=0x4FFF, buf_off=0x0FF3)
    check(cf == 0 and (ax & 0xFF) == 40 and data == bytes(disk2[13 * 512:53 * 512]),
          "read 40 sectors across banks, odd buffer address")
    if chips == 2:
        lba = 1920 - 7
        ax, cf, data = int13_read(pc, lba, 16)
        check(cf == 0 and data == bytes(disk2[lba * 512:(lba + 16) * 512]), "read across the U1/U2 boundary")
    ax, cf, _ = int13_read(pc, total - 2, 3)
    check(cf == 1 and (ax >> 8) == 0x04, "read past the end: CF=1, AH=04h")

    # 7a. INT 13h writes. cur = what the disk should hold now
    cur = bytearray(disk2)
    rnd = random.Random(100 + chips)

    def erases():
        return sum(f.erases for f in card.flash)

    def disk_ok():
        return card.image()[0x10000:0x10000 + total * 512] == inv(cur)

    card.jumper = False
    before, e0 = card.image(), erases()
    new = bytes(b | 0x5A for b in cur[100 * 512:101 * 512])
    ax, cf = int13_write(pc, 100, new)
    check(cf == 1 and (ax >> 8) == 0x03 and card.image() == before,
          "write without JP1 (in place): CF=1, AH=03h, flash unchanged")
    new = bytes(rnd.getrandbits(8) for _ in range(512))
    ax, cf = int13_write(pc, 100, new)
    check(cf == 1 and (ax >> 8) == 0x03 and card.image() == before and erases() == e0,
          "write without JP1 (needs an erase): CF=1, AH=03h, nothing erased")
    check(card.bank == 0 and card.ctrl == 0, "failed write leaves BANK=0, CTRL=0")
    card.jumper = True

    new = bytes(b | rnd.getrandbits(8) for b in cur[200 * 512:202 * 512])
    ax, cf = int13_write(pc, 200, new)
    cur[200 * 512:202 * 512] = new
    check(cf == 0 and ax == 0x0002 and erases() == e0 and disk_ok(),
          "write 2 sectors that only set bits: in place, no erase")

    new = bytes(rnd.getrandbits(8) for _ in range(512))
    ax, cf = int13_write(pc, 300, new)
    cur[300 * 512:301 * 512] = new
    check(cf == 0 and ax == 0x0001 and erases() == e0 + 2 and disk_ok(),
          "write needing an erase: spare and block erased, the other 127 sectors kept")

    new = bytes(rnd.getrandbits(8) for _ in range(6 * 512))
    ax, cf = int13_write(pc, 256 - 3, new, buf_seg=0x4FFF, buf_off=0x0FF3)
    cur[253 * 512:259 * 512] = new
    check(cf == 0 and ax == 0x0006 and erases() == e0 + 6 and disk_ok(),
          "write 6 sectors across a 64 KB block boundary, odd buffer address")
    ax, cf, data = int13_read(pc, 253, 6)
    check(cf == 0 and data == bytes(cur[253 * 512:259 * 512]), "INT 13h reads the written sectors back")

    if chips == 2:
        new = bytes(rnd.getrandbits(8) for _ in range(4 * 512))
        ax, cf = int13_write(pc, 1920 - 2, new)
        cur[1918 * 512:1922 * 512] = new
        check(cf == 0 and ax == 0x0004 and disk_ok(), "write across the U1/U2 boundary")

    before = card.image()
    ax, cf = int13_write(pc, total - 1, bytes(1024))
    check(cf == 1 and (ax >> 8) == 0x04 and card.image() == before, "write past the end: CF=1, AH=04h, nothing written")
    pc.call_int(0x13, {UC_X86_REG_AX: 0x0501, UC_X86_REG_CX: 0x0001, UC_X86_REG_DX: 0x0080,
                       UC_X86_REG_ES: 0x5000, UC_X86_REG_BX: 0})
    check((pc.r(UC_X86_REG_EFLAGS) & 1) == 0 and card.image() == before, "AH=05h format track: OK, no change")
    check(card.bank == 0 and card.ctrl == 0, "writes leave BANK=0, CTRL=0 (VPP off)")
    code, out = pc.run_com(com("FLREAD.COM"), "BACK2.IMG /D")
    with open(os.path.join(tmp, "BACK2.IMG"), "rb") as f:
        check(code == 0 and f.read() == bytes(cur), "FLREAD /D after INT 13h writes returns the new disk")
    pc.call_int(0x13, {UC_X86_REG_AX: 0x0201, UC_X86_REG_CX: 0x0001, UC_X86_REG_DX: 0x0081,
                       UC_X86_REG_ES: 0x5000, UC_X86_REG_BX: 0})
    check((pc.r(UC_X86_REG_EFLAGS) & 1) == 1 and (pc.r(UC_X86_REG_AX) >> 8) == 0x01, "drive 81h chained to the BIOS")
    check(card.bank == 0 and card.ctrl == 0, "INT 13h leaves BANK=0")

    # 8. INT 19h: floppy fails, the flash MBR (55AA) is loaded to 0:7C00 and started with DL=80h
    stopped = pc.call_int(0x19, {})
    check(stopped == "stop" and pc.r(UC_X86_REG_CS) == 0 and pc.r(UC_X86_REG_IP) == 0x7C02
          and (pc.r(UC_X86_REG_DX) & 0xFF) == 0x80, "INT 19h boots the flash MBR with DL=80h")

    # 9. mkdisk image written in parts with /O, then booted: INT 19h -> our MBR -> partition boot sector
    import subprocess
    note = os.path.join(tmp, "README.TXT")
    with open(note, "wb") as f:
        f.write(b"hello from the flash disk\r\n" * 100)
    stem = os.path.join(tmp, "MK")
    res = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "tools", "mkdisk.py"), stem + ".IMG",
                          "--chips", str(chips), "--add", note, "--split", "512"],
                         capture_output=True, text=True)
    check(res.returncode == 0, "mkdisk builds a %d-chip image" % chips)
    cmds = [l.split()[1:] for l in res.stdout.splitlines() if l.startswith("FLWRITE ")]
    pc = emu86.PC(card, tmp)
    ok = True
    for c in cmds:
        code, out = pc.run_com(com("FLWRITE.COM"), " ".join(c) + " /Y")
        ok = ok and code == 0
    with open(stem + ".IMG", "rb") as f:
        mk = f.read()
    check(ok and len(cmds) > 1 and card.image()[0x10000:0x10000 + len(mk)] == inv(mk),
          "image written in %d parts with /O equals the whole image" % len(cmds))
    root_off = (16 + 1 + 2 * struct.unpack_from("<H", mk, 16 * 512 + 0x16)[0]) * 512
    check(mk[root_off:root_off + 11] == b"README  TXT", "README.TXT is in the FAT12 root directory")
    pc = emu86.PC(card, tmp)
    card.bank, card.ctrl = 0, 0
    pc.far_call(window, 3)
    pc.call_int(0x19, {})
    check("no operating system on this disk" in "".join(pc.console),
          "INT 19h -> MBR -> partition boot sector runs")

    # 9b. --boot: what mkdisk patches in a DOS 4+ and in a DOS 3.x boot sector
    for dos3 in (False, True):
        fl = make_floppy(dos3)
        fpath = os.path.join(tmp, "FLOPPY.IMG")
        with open(fpath, "wb") as f:
            f.write(fl)
        res = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "tools", "mkdisk.py"), stem + "B.IMG",
                              "--chips", str(chips), "--boot", fpath], capture_output=True, text=True)
        with open(stem + "B.IMG", "rb") as f:
            vbr = f.read()[16 * 512:17 * 512]
        bpb = struct.unpack_from("<HBHBHHBHHHH", vbr, 0x0B)
        good = (res.returncode == 0 and bpb[0:7] == (512, 4, 1, 2, 512, total - 16, 0xF8)
                and bpb[8:] == (16, 4, 16) and vbr[0:11] == fl[0:11])
        if dos3:
            good = good and vbr[0x1E:0x1FD] == fl[0x1E:0x1FD] and vbr[0x1FD] == 0x80 and "EXPERIMENTAL" in res.stdout
            check(good, "mkdisk --boot DOS 3.x: BPB 0Bh..1Dh patched, boot code kept, drive byte 1FDh = 80h")
        else:
            good = good and vbr[0x24] == 0x80 and vbr[0x26] == 0x29 and vbr[0x3E:0x1FD] == fl[0x3E:0x1FD]
            check(good, "mkdisk --boot DOS 4+: BPB and extended BPB patched, boot code kept")

    # 10. No descriptor: ROM gives the memory back and installs nothing
    blank = emu86.Card(chips=chips, jumper=True, port=port, window=window)
    blank.flash[0].mem[0:0x2000] = card.flash[0].mem[0:0x2000]
    pc = emu86.PC(blank, tmp)
    out = pc.far_call(window, 3)
    vec13 = struct.unpack("<HH", pc.read(0x13 * 4, 4))
    check("no disk descriptor" in out and struct.unpack("<H", pc.read(0x413, 2))[0] == 640
          and vec13[1] == emu86.STUB_SEG, "no descriptor: message, 640 KB kept, INT 13h untouched")


def main():
    tmp = tempfile.mkdtemp(prefix="isaflash-")
    scenario(2, 0x2A0, 0xCC00, tmp)
    scenario(1, 0x300, 0xD000, tmp)
    print("\n%d failure(s)" % len(FAILS))
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
