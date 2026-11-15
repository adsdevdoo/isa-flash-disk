"""End-to-end tests of FLASHROM.BIN and the DOS utilities on the emulated PC and card (tools/emu/emu86.py).

Usage:  python tools/build_dos.py <nasm>      (builds dist/)
        python tools/emu/test_isaflash.py
Needs the Unicorn engine importable (pip install unicorn==2.1.4, or ISAFLASH_PYLIB=<dir with unicorn>).
"""

import copy
import os
import random
import struct
import subprocess
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
LBLK = 127                      # disk format 3: sectors per logical block
GEO = {"heads": 2, "spt": 15}   # set per scenario


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


def chs_of(lba):
    c, rem = divmod(lba, GEO["heads"] * GEO["spt"])
    h, s = divmod(rem, GEO["spt"])
    return c, h, s + 1


def int13_regs(fn, lba, count, buf_seg, buf_off, drive):
    c, h, s = chs_of(lba)
    return {UC_X86_REG_AX: (fn << 8) | count, UC_X86_REG_CX: ((c & 0xFF) << 8) | ((c >> 2) & 0xC0) | s,
            UC_X86_REG_DX: (h << 8) | drive, UC_X86_REG_ES: buf_seg, UC_X86_REG_BX: buf_off}


def int13_read(pc, lba, count, buf_seg=0x5000, buf_off=0x0007, drive=0x80):
    pc.call_int(0x13, int13_regs(2, lba, count, buf_seg, buf_off, drive))
    ax = pc.r(UC_X86_REG_AX)
    cf = pc.r(UC_X86_REG_EFLAGS) & 1
    return ax, cf, pc.read(pc.lin(buf_seg, buf_off), count * 512)


def int13_write(pc, lba, data, buf_seg=0x5000, buf_off=0x0007, drive=0x80):
    pc.uc.mem_write(pc.lin(buf_seg, buf_off), bytes(data))
    stopped = pc.call_int(0x13, int13_regs(3, lba, len(data) // 512, buf_seg, buf_off, drive))
    return pc.r(UC_X86_REG_AX), pc.r(UC_X86_REG_EFLAGS) & 1, stopped


def inv(data):
    """Disk data are stored inverted."""
    return bytes(b ^ 0xFF for b in data)


def block_map(card, chips):
    """Same rule as the ROM and the utilities: for each logical block, the complete copy with the highest
    generation (firmware/include/isaflash.inc, HDR_*)."""
    img = card.image()
    nl, np_ = img[0x2016], img[0x2017]
    bad = struct.unpack_from("<I", img, 0x2018)[0]
    best = {}
    for p in range(1, np_ + 1):
        if bad >> p & 1:
            continue
        h = img[p * 0x10000 + 0xFE00:p * 0x10000 + 0xFE00 + 17]
        if h[0:4] != b"FLBK" or h[4] ^ 0xFF != h[5] or h[4] >= nl or h[16] != 0:
            continue
        g, ng = struct.unpack_from("<II", h, 8)
        if g ^ 0xFFFFFFFF != ng:
            continue
        if h[4] not in best or g > best[h[4]][1]:
            best[h[4]] = (p, g)
    return {lb: pg[0] for lb, pg in best.items()}


def logical_disk(card, chips):
    m = block_map(card, chips)
    img = card.image()
    if len(m) != img[0x2016]:
        return None
    return b"".join(inv(img[m[lb] * 0x10000:m[lb] * 0x10000 + LBLK * 512]) for lb in range(img[0x2016]))


def fltest_checks(port, window, args, tmp):
    """FLTEST and FLFORMAT /E /T on one chip with a worn block, a block with a stuck bit and a block that erases
    slower than 10 s."""
    print("\n--- FLTEST, FLFORMAT /E /T (1 chip) ---")
    card = emu86.Card(chips=1, jumper=True, port=port, window=window)
    pc = emu86.PC(card, tmp)
    code, out = pc.run_com(com("FLTEST.COM"), "/A /Y" + args)
    check(code == 0 and out.count(" OK\r\n") == 16 and "OK: 16, WORN: 0, BAD: 0" in out,
          "FLTEST /A on a new chip: 16 blocks OK, exit code 0")
    pc.run_com(com("FLFORMAT.COM"), "FLASHROM.BIN /Y /E" + args)
    disk = make_disk(1778, seed=7)
    with open(os.path.join(tmp, "DISK1.IMG"), "wb") as f:
        f.write(disk)
    pc.run_com(com("FLWRITE.COM"), "DISK1.IMG /D /Y" + args)
    f0 = card.flash[0]
    f0.erase_polls[5] = 120                     # about 6.6 s: worn
    code, out = pc.run_com(com("FLTEST.COM"), "/Y" + args)
    check(code == 4 and out.count("Block ") == 15 and "Block 5: erase" in out and out.count("WORN (") == 1
          and logical_disk(card, 1) == bytes(disk), "FLTEST: 15 disk blocks tested, block 5 WORN (exit 4), data kept")
    f0.stuck1[9 * 0x10000 + 0x1234] = 0x04      # a bit that cannot be programmed
    code, out = pc.run_com(com("FLTEST.COM"), "/Y" + args)
    check(code == 5 and "BAD (00h not programmed" in out and "the free block is bad" in out
          and logical_disk(card, 1) == bytes(disk), "FLTEST: block with a stuck bit BAD (exit 5), stops, data kept")
    f0.erase_polls[11] = 250                    # about 14 s: slower than the datasheet maximum
    code, out = pc.run_com(com("FLFORMAT.COM"), "FLASHROM.BIN /Y /E /T" + args)
    img = card.image()
    bad = struct.unpack_from("<I", img, 0x2018)[0]
    check(code == 0 and bad == (1 << 9) | (1 << 11) and img[0x2016] == 12
          and struct.unpack_from("<HHHH", img, 0x200C) == (127, 2, 6, 1524) and "Bad blocks left out: 2" in out,
          "FLFORMAT /E /T: blocks 9 and 11 bad, 12 logical blocks, 127/2/6")
    code, out = pc.run_com(com("FLINFO.COM"), args.strip())
    check("Bad blocks (not used): 9 11" in out, "FLINFO lists the bad blocks")
    card.reset()
    pc = emu86.PC(card, tmp)
    out = pc.far_call(window, 3)
    check("ISA Flash Disk: 762 KB" in out, "ROM mounts the smaller disk: %r" % out.strip())
    GEO["spt"] = 6
    e9, e11 = f0.block_erases[9], f0.block_erases[11]
    lba = 4 * LBLK + 3
    cur = bytearray(1524 * 512)
    ok = True
    for i in range(24):
        data = bytes([0x55 if i & 1 else 0xAA]) * 512
        ax, cf, _ = int13_write(pc, lba, data)
        cur[lba * 512:(lba + 1) * 512] = data
        ok = ok and cf == 0
    check(ok and logical_disk(card, 1) == bytes(cur) and f0.block_erases[9] == e9 and f0.block_erases[11] == e11,
          "24 rewrites through INT 13h never touch the bad blocks")


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


def mkdisk(*args):
    return subprocess.run([sys.executable, "-I", os.path.join(ROOT, "tools", "mkdisk.py")] + list(args),
                          capture_output=True, text=True)


def scenario(chips, port, window, tmp):
    print("\n=== %d chip(s), port %03Xh, window %04Xh ===" % (chips, port, window))
    nl, np_ = chips * 16 - 2, chips * 16 - 1
    spt = nl // 2
    total = 127 * 2 * spt
    GEO["spt"] = spt
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

    # 2. FLFORMAT /E with the jumper: ROM, descriptor, empty disk with a block header per logical block
    card.jumper = True
    code, out = pc.run_com(com("FLFORMAT.COM"), "FLASHROM.BIN /Y /E" + args)
    check(code == 0, "FLFORMAT exit code 0")
    img = card.flash[0].mem
    check(img[0:2] == b"\x55\xaa" and img[8:16] == b"ISAFLASH", "ROM image in bank 0")
    check(struct.unpack_from("<H", img, 0x10)[0] == port, "ROM header holds port %03Xh" % port)
    check(sum(img[0:0x2000]) & 0xFF == 0, "ROM checksum is zero")
    d = img[0x2000:0x2200]
    check(d[0:8] == b"ISAFLDSK" and sum(d) & 0xFF == 0, "descriptor signature and checksum")
    check(struct.unpack_from("<HHHHH", d, 0x0C) == (127, 2, spt, total, 128),
          "descriptor geometry 127/2/%d, %d sectors" % (spt, total))
    check(struct.unpack_from("<H", d, 0x08)[0] == 3 and d[0x16] == nl and d[0x17] == np_,
          "descriptor format 3, %d logical in %d flash blocks" % (nl, np_))
    check(block_map(card, chips) == {lb: lb + 1 for lb in range(nl)} and logical_disk(card, chips) == bytes(total * 512),
          "FLFORMAT /E: logical block n in flash block n+1, disk reads as zeros")
    check(card.bank == 0 and card.ctrl == 0, "card left with BANK=0, CTRL=0")

    # 3. FLINFO finds the ROM by itself (no /M /P), reads the jumper and the block map
    code, out = pc.run_com(com("FLINFO.COM"), "/J")
    check(code == 0 and "port in ROM %04Xh" % port in out, "FLINFO finds the ROM and its port")
    check(("127/2/%d" % spt) in out and ("%d sectors" % total) in out and "format 3" in out,
          "FLINFO reports the geometry and format 3")
    check("Blocks: %d logical in %d flash blocks, free block %d" % (nl, np_, np_) in out, "FLINFO reports the block map")
    check("JP1: fitted" in out, "FLINFO /J sees the jumper")
    check(("2 x 28F008SA" if chips == 2 else "1 x 28F008SA") in out, "FLINFO counts %d chip(s)" % chips)

    # 4. FLWRITE /D a disk image, again unchanged, then a change in one block
    disk = make_disk(total, seed=chips)
    with open(os.path.join(tmp, "DISK.IMG"), "wb") as f:
        f.write(disk)
    code, out = pc.run_com(com("FLWRITE.COM"), "DISK.IMG /D /Y")
    check(code == 0 and "FAILED" not in out, "FLWRITE /D exit code 0")
    check(logical_disk(card, chips) == bytes(disk), "the disk read through the block map equals the image")
    code, out = pc.run_com(com("FLWRITE.COM"), "DISK.IMG /D /Y")
    check(code == 0 and out.count("unchanged") == nl, "second FLWRITE: all %d blocks unchanged" % nl)
    disk2 = bytearray(disk)
    disk2[0x23456] ^= 0xFF                      # logical block 2
    with open(os.path.join(tmp, "DISK2.IMG"), "wb") as f:
        f.write(disk2)
    e0 = sum(f.erases for f in card.flash)
    code, out = pc.run_com(com("FLWRITE.COM"), "DISK2.IMG /D /Y")
    erases = sum(f.erases for f in card.flash) - e0
    m = block_map(card, chips)
    check(code == 0 and out.count("verified") == 1 and erases == 1 and "Block 2: to flash block" in out,
          "changed byte: only logical block 2 written, into the free block, one erase")
    check(logical_disk(card, chips) == bytes(disk2) and sorted(m.values()) != list(range(1, nl + 1))
          and len(set(m.values())) == nl, "the disk equals the changed image, block map still one-to-one")

    # 5. FLREAD /D and full
    code, out = pc.run_com(com("FLREAD.COM"), "BACK.IMG /D")
    with open(os.path.join(tmp, "BACK.IMG"), "rb") as f:
        back = f.read()
    check(code == 0 and back == bytes(disk2), "FLREAD /D returns the disk (%d sectors)" % total)
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
    check(base_kb == 637, "base memory reduced to 637 KB")
    check(pc.read(0x475, 1)[0] == 1, "hard disk count 1")
    vec13 = struct.unpack("<HH", pc.read(0x13 * 4, 4))
    vec19 = struct.unpack("<HH", pc.read(0x19 * 4, 4))
    check(vec13[1] == 637 * 64 and vec19[1] == 637 * 64, "INT 13h and INT 19h point into the reserved 3 KB")
    check(card.bank == 0 and card.ctrl == 0, "ROM init leaves BANK=0, CTRL=0")

    # 7. INT 13h reads
    pc.call_int(0x13, {UC_X86_REG_AX: 0x0800, UC_X86_REG_DX: 0x0080})
    cx, dx = pc.r(UC_X86_REG_CX), pc.r(UC_X86_REG_DX)
    maxcyl = ((cx & 0xC0) << 2) | (cx >> 8)
    check((pc.r(UC_X86_REG_EFLAGS) & 1) == 0 and maxcyl == 126 and (cx & 0x3F) == spt and (dx >> 8) == 1
          and (dx & 0xFF) == 1, "AH=08h geometry 127/2/%d, 1 drive" % spt)
    pc.call_int(0x13, {UC_X86_REG_AX: 0x1500, UC_X86_REG_DX: 0x0080})
    check((pc.r(UC_X86_REG_AX) >> 8) == 3 and pc.r(UC_X86_REG_DX) == total, "AH=15h fixed disk, %d sectors" % total)
    ax, cf, data = int13_read(pc, 0, 1)
    check(cf == 0 and ax == 0x0001 and data == bytes(disk2[0:512]), "read sector 0")
    ax, cf, data = int13_read(pc, 13, 40, buf_seg=0x4FFF, buf_off=0x0FF3)
    check(cf == 0 and (ax & 0xFF) == 40 and data == bytes(disk2[13 * 512:53 * 512]),
          "read 40 sectors across banks, odd buffer address")
    lba = (16 if chips == 2 else 3) * LBLK - 7
    ax, cf, data = int13_read(pc, lba, 16)
    check(cf == 0 and data == bytes(disk2[lba * 512:(lba + 16) * 512]),
          "read across logical blocks" + (" and the U1/U2 boundary" if chips == 2 else ""))
    ax, cf, _ = int13_read(pc, total - 2, 3)
    check(cf == 1 and (ax >> 8) == 0x04, "read past the end: CF=1, AH=04h")

    # 7a. INT 13h writes. cur = what the disk should hold now
    cur = bytearray(disk2)
    rnd = random.Random(100 + chips)

    def erases():
        return sum(f.erases for f in card.flash)

    def disk_ok():
        return logical_disk(card, chips) == bytes(cur)

    card.jumper = False
    before, e0 = card.image(), erases()
    new = bytes(b | 0x5A for b in cur[100 * 512:101 * 512])
    ax, cf, _ = int13_write(pc, 100, new)
    check(cf == 1 and (ax >> 8) == 0x03 and card.image() == before,
          "write without JP1 (in place): CF=1, AH=03h, flash unchanged")
    new = bytes(rnd.getrandbits(8) for _ in range(512))
    ax, cf, _ = int13_write(pc, 100, new)
    check(cf == 1 and (ax >> 8) == 0x03 and card.image() == before and erases() == e0,
          "write without JP1 (needs an erase): CF=1, AH=03h, nothing erased")
    check(card.bank == 0 and card.ctrl == 0, "failed write leaves BANK=0, CTRL=0")
    card.jumper = True

    new = bytes(b | rnd.getrandbits(8) for b in cur[200 * 512:202 * 512])
    ax, cf, _ = int13_write(pc, 200, new)
    cur[200 * 512:202 * 512] = new
    check(cf == 0 and ax == 0x0002 and erases() == e0 and disk_ok(),
          "write 2 sectors that only set bits: in place, no erase")

    m0 = block_map(card, chips)
    new = bytes(rnd.getrandbits(8) for _ in range(512))
    ax, cf, _ = int13_write(pc, 300, new)
    cur[300 * 512:301 * 512] = new
    m1 = block_map(card, chips)
    check(cf == 0 and ax == 0x0001 and erases() - e0 in (1, 2) and disk_ok() and m1[2] != m0[2],
          "write needing an erase: logical block 2 moved to the free block, the other 126 sectors kept")

    e1 = erases()
    lba = 2 * LBLK - 3
    new = bytes(rnd.getrandbits(8) for _ in range(6 * 512))
    ax, cf, _ = int13_write(pc, lba, new, buf_seg=0x4FFF, buf_off=0x0FF3)
    cur[lba * 512:(lba + 6) * 512] = new
    check(cf == 0 and ax == 0x0006 and 2 <= erases() - e1 <= 4 and disk_ok(),
          "write 6 sectors across logical blocks 1/2, odd buffer address")
    ax, cf, data = int13_read(pc, lba, 6)
    check(cf == 0 and data == bytes(cur[lba * 512:(lba + 6) * 512]), "INT 13h reads the written sectors back")

    if chips == 2:
        lba = 16 * LBLK - 2
        new = bytes(rnd.getrandbits(8) for _ in range(4 * 512))
        ax, cf, _ = int13_write(pc, lba, new)
        cur[lba * 512:(lba + 4) * 512] = new
        check(cf == 0 and ax == 0x0004 and disk_ok(), "write across logical blocks 15/16")

    before = card.image()
    ax, cf, _ = int13_write(pc, total - 1, bytes(1024))
    check(cf == 1 and (ax >> 8) == 0x04 and card.image() == before, "write past the end: CF=1, AH=04h, nothing written")
    pc.call_int(0x13, {UC_X86_REG_AX: 0x0501, UC_X86_REG_CX: 0x0001, UC_X86_REG_DX: 0x0080,
                       UC_X86_REG_ES: 0x5000, UC_X86_REG_BX: 0})
    check((pc.r(UC_X86_REG_EFLAGS) & 1) == 0 and card.image() == before, "AH=05h format track: OK, no change")
    check(card.bank == 0 and card.ctrl == 0, "writes leave BANK=0, CTRL=0 (VPP off)")
    code, out = pc.run_com(com("FLREAD.COM"), "BACK2.IMG /D")
    with open(os.path.join(tmp, "BACK2.IMG"), "rb") as f:
        check(code == 0 and f.read() == bytes(cur), "FLREAD /D after INT 13h writes returns the new disk")

    # 7b. FLWRITE with the ROM in memory: the ROM re-reads the block map (INT 13h AH=F1h)
    part = bytes(rnd.getrandbits(8) for _ in range(LBLK * 512))
    with open(os.path.join(tmp, "PART.IMG"), "wb") as f:
        f.write(part)
    code, out = pc.run_com(com("FLWRITE.COM"), "PART.IMG /D /O:2 /Y")
    cur[2 * LBLK * 512:3 * LBLK * 512] = part
    ax, cf, data = int13_read(pc, 2 * LBLK + 5, 2)
    check(code == 0 and disk_ok() and cf == 0 and data == part[5 * 512:7 * 512],
          "FLWRITE /D /O:2 under the resident ROM: INT 13h reads the new block (map re-read)")
    new = bytes(rnd.getrandbits(8) for _ in range(512))
    ax, cf, _ = int13_write(pc, 2 * LBLK + 9, new)
    cur[(2 * LBLK + 9) * 512:(2 * LBLK + 10) * 512] = new
    check(cf == 0 and disk_ok(), "INT 13h write after FLWRITE goes by the new block map")
    pc.call_int(0x13, {UC_X86_REG_AX: 0x0201, UC_X86_REG_CX: 0x0001, UC_X86_REG_DX: 0x0081,
                       UC_X86_REG_ES: 0x5000, UC_X86_REG_BX: 0})
    check((pc.r(UC_X86_REG_EFLAGS) & 1) == 1 and (pc.r(UC_X86_REG_AX) >> 8) == 0x01, "drive 81h chained to the BIOS")
    check(card.bank == 0 and card.ctrl == 0, "INT 13h leaves BANK=0")

    # 8. INT 19h: floppy fails, the flash MBR (55AA) is loaded to 0:7C00 and started with DL=80h
    stopped = pc.call_int(0x19, {})
    check(stopped == "stop" and pc.r(UC_X86_REG_CS) == 0 and pc.r(UC_X86_REG_IP) == 0x7C02
          and (pc.r(UC_X86_REG_DX) & 0xFF) == 0x80, "INT 19h boots the flash MBR with DL=80h")

    # 9. mkdisk image written in parts with /O, then booted: INT 19h -> our MBR -> partition boot sector
    note = os.path.join(tmp, "README.TXT")
    with open(note, "wb") as f:
        f.write(b"hello from the flash disk\r\n" * 100)
    stem = os.path.join(tmp, "MK")
    res = mkdisk(stem + ".IMG", "--chips", str(chips), "--add", note, "--split", "512")
    check(res.returncode == 0, "mkdisk builds a %d-chip image" % chips)
    cmds = [ln.split()[1:] for ln in res.stdout.splitlines() if ln.startswith("FLWRITE ")]
    pc = emu86.PC(card, tmp)
    ok = True
    for c in cmds:
        code, out = pc.run_com(com("FLWRITE.COM"), " ".join(c) + " /Y")
        ok = ok and code == 0
    with open(stem + ".IMG", "rb") as f:
        mk = f.read()
    check(ok and len(cmds) > 1 and len(mk) == total * 512 and logical_disk(card, chips) == mk,
          "image written in %d parts with /O equals the whole image" % len(cmds))
    root_off = (spt + 1 + 2 * struct.unpack_from("<H", mk, spt * 512 + 0x16)[0]) * 512
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
        res = mkdisk(stem + "B.IMG", "--chips", str(chips), "--boot", fpath)
        with open(stem + "B.IMG", "rb") as f:
            vbr = f.read()[spt * 512:(spt + 1) * 512]
        bpb = struct.unpack_from("<HBHBHHBHHHH", vbr, 0x0B)
        good = (res.returncode == 0 and bpb[0:7] == (512, 4, 1, 2, 512, total - spt, 0xF8)
                and bpb[8:] == (spt, 2, spt) and vbr[0:11] == fl[0:11])
        if dos3:
            good = good and vbr[0x1E:0x1FD] == fl[0x1E:0x1FD] and vbr[0x1FD] == 0x80 and "EXPERIMENTAL" in res.stdout
            check(good, "mkdisk --boot DOS 3.x: BPB 0Bh..1Dh patched, boot code kept, drive byte 1FDh = 80h")
        else:
            good = good and vbr[0x24] == 0x80 and vbr[0x26] == 0x29 and vbr[0x3E:0x1FD] == fl[0x3E:0x1FD]
            check(good, "mkdisk --boot DOS 4+: BPB and extended BPB patched, boot code kept")

    # 10. Power failure in every phase of a block rewrite, on a fresh disk
    card = emu86.Card(chips=chips, jumper=True, port=port, window=window)
    emu86.PC(card, tmp).run_com(com("FLFORMAT.COM"), "FLASHROM.BIN /Y /E" + args)

    def boot(c):
        c.reset()
        p = emu86.PC(c, tmp)
        return p, p.far_call(window, 3)

    lba = 3 * LBLK + 10
    a_data, b_data = bytes([0x55]) * 512, bytes([0xAA]) * 512
    pc, _ = boot(card)
    int13_write(pc, lba, a_data)                # in place on the empty disk
    expect_a = bytearray(total * 512)
    expect_a[lba * 512:(lba + 1) * 512] = a_data
    snap = copy.deepcopy(card)
    card.ops = 0
    ax, cf, _ = int13_write(pc, lba, b_data)    # needs an erase: block 3 moves
    full_ops = card.ops
    expect_b = bytearray(expect_a)
    expect_b[lba * 512:(lba + 1) * 512] = b_data
    check(cf == 0 and logical_disk(card, chips) == bytes(expect_b), "rewrite on the fresh disk (%d operations)" % full_ops)
    results = []
    for n in (0, 1, 2, 300, full_ops - 14, full_ops - 6, full_ops - 1, full_ops):
        c = copy.deepcopy(snap)
        p, _ = boot(c)
        c.fail_at, c.ops = n, 0
        _, _, stopped = int13_write(p, lba, b_data)
        p, out = boot(c)
        ax, cf, data = int13_read(p, lba, 1)
        want = a_data if n < full_ops else b_data
        exp = expect_a if n < full_ops else expect_b
        results.append("ISA Flash Disk:" in out and "damaged" not in out and cf == 0 and data == want
                       and logical_disk(c, chips) == bytes(exp)
                       and stopped == ("powerfail" if n < full_ops else "stop"))
    check(all(results), "power failure after 0..%d operations: old sector until the header is complete, then new;"
          " nothing else lost (%s)" % (full_ops, results))

    # power failure inside the wear-leveling move that follows every 8th generation
    pc, _ = boot(card)
    state, cur3 = None, bytearray(expect_b)
    for i in range(16):
        snap = copy.deepcopy(card)
        e = sum(f.erases for f in card.flash)
        data = (a_data, b_data)[i & 1]
        card.ops = 0
        int13_write(pc, lba, data)
        if sum(f.erases for f in card.flash) - e == 2:
            state = (snap, data, card.ops, bytes(cur3))
            cur3[lba * 512:(lba + 1) * 512] = data
            break
        cur3[lba * 512:(lba + 1) * 512] = data
    check(state is not None and logical_disk(card, chips) == bytes(cur3), "a rewrite with a wear-leveling move found")
    if state:
        snap, data, ops, old = state
        new_disk = bytearray(old)
        new_disk[lba * 512:(lba + 1) * 512] = data
        c = copy.deepcopy(snap)
        p, _ = boot(c)
        c.fail_at, c.ops = ops - 1, 0           # the moved block's VALID byte is lost
        int13_write(p, lba, data)
        p, out = boot(c)
        check("damaged" not in out and logical_disk(c, chips) == bytes(new_disk),
              "power failure in the wear-leveling move: the written sector kept, the moved block intact")

    # 11. Wear leveling: one sector rewritten over and over spreads the erases over many flash blocks
    pc, _ = boot(card)
    card2_before = [list(f.block_erases) for f in card.flash]
    n = 64
    for i in range(n):
        data = (a_data, b_data)[i & 1]
        int13_write(pc, lba, data)
        cur3[lba * 512:(lba + 1) * 512] = data
    per_block = [f.block_erases[b] - card2_before[k][b] for k, f in enumerate(card.flash) for b in range(16)]
    used = sum(1 for x in per_block if x)
    check(logical_disk(card, chips) == bytes(cur3) and max(per_block) <= n // 4 and used >= 8,
          "%d rewrites of one sector: at most %d erases per flash block, %d blocks used" % (n, max(per_block), used))

    # 12. No disk: ROM gives the memory back and installs nothing
    blank = emu86.Card(chips=chips, jumper=True, port=port, window=window)
    blank.flash[0].mem[0:0x2000] = card.flash[0].mem[0:0x2000]
    pc = emu86.PC(blank, tmp)
    out = pc.far_call(window, 3)
    vec13 = struct.unpack("<HH", pc.read(0x13 * 4, 4))
    check("no disk (format 3)" in out and struct.unpack("<H", pc.read(0x413, 2))[0] == 640
          and vec13[1] == emu86.STUB_SEG, "no disk: message, 640 KB kept, INT 13h untouched")

    if chips == 1:
        fltest_checks(port, window, args, tmp)
        GEO["spt"] = spt

    # 13. Descriptor without block headers: "block map damaged"
    nohdr = copy.deepcopy(card)
    for f in nohdr.flash:
        for b in range(16):
            if (f is not nohdr.flash[0]) or b:
                f.mem[b * 0x10000 + 0xFE00:b * 0x10000 + 0xFE11] = b"\xff" * 17
    nohdr.reset()
    out = emu86.PC(nohdr, tmp).far_call(window, 3)
    check("block map damaged" in out, "no block headers: 'block map damaged'")


def main():
    tmp = tempfile.mkdtemp(prefix="isaflash-")
    scenario(2, 0x2A0, 0xCC00, tmp)
    scenario(1, 0x300, 0xD000, tmp)
    print("\n%d failure(s)" % len(FAILS))
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
