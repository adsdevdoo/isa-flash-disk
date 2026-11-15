#!/usr/bin/env python3
"""Make a hard disk image for the ISA Flash Disk (written to the card with FLWRITE /D).

Usage:
  python tools/mkdisk.py DISK.IMG --chips 2 [--boot DOSBOOT.IMG] [--add FILE ...] [--label NAME] [--split KB]

Geometry matches the descriptor written by FLFORMAT (disk format 3): 127 cylinders x 2 heads x (logical
blocks / 2) sectors per track = 127 sectors per logical block: 1 chip = 127/2/7 (1778 sectors),
2 chips = 127/2/15 (3810 sectors). The image is a plain disk image (PC emulators can mount it); FLWRITE /D
cuts it into logical blocks and stores it on the card, FLREAD /D puts it back together.
Layout: MBR (dist/MBR.BIN, partition table filled here), one active FAT12 partition from C/H/S 0/1/1
(LBA = sectors per track) to the end of the disk, 4 sectors per cluster, 512 root entries.

--boot  a bootable DOS floppy image (raw .IMG with a FAT12 file system). Its boot sector code is used with
        this disk's BPB, and the system files are copied first and contiguous, as the DOS boot sector expects:
        IO.SYS + MSDOS.SYS (MS-DOS 4.0-6.22), IBMBIO.COM + IBMDOS.COM (PC DOS 4+), or KERNEL.SYS (FreeDOS);
        COMMAND.COM follows. DOS 3.x boot sectors (no extended BPB): EXPERIMENTAL, not tried on a real DOS 3.x:
        only the DOS 3.x BPB (0Bh..1Dh, 16-bit hidden sectors) is patched and the boot drive byte at 1FDh is
        set to 80h; the boot code is left as it is.
        Without --boot the partition gets dist/VBRSTUB.BIN, which only prints "no operating system".
--add   more files for the root directory (8.3 names).
--split write DISK.001, DISK.002, ... of at most KB kilobytes each (whole logical blocks of 127 sectors,
        63.5 KB) for floppies and print the FLWRITE commands with the /O:block offsets.
"""

import argparse
import datetime
import math
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
LBLK_SECTORS = 127               # disk format 3: sectors per logical block
CYLS, HEADS = 127, 2
SPT = PART_START = 15            # set by set_geometry(); the partition starts at C/H/S 0/1/1
SPC, RESERVED, NFATS, ROOT_ENTRIES, MEDIA = 4, 1, 2, 512, 0xF8
SYSTEM_SETS = [("IO.SYS", "MSDOS.SYS"), ("IBMBIO.COM", "IBMDOS.COM"), ("KERNEL.SYS",)]


def set_geometry(chips):
    """Logical blocks = chips * 16 - 2; sectors per track = half of them, so C*H*S = 127 * blocks."""
    global SPT, PART_START
    SPT = PART_START = (chips * 16 - 2) // 2
    return CYLS * HEADS * SPT


def chs(lba):
    c, rem = divmod(lba, HEADS * SPT)
    h, s = divmod(rem, SPT)
    return bytes([h, ((c >> 2) & 0xC0) | (s + 1), c & 0xFF])


# ---- reading a FAT12 floppy image ----
class Fat12Image:
    def __init__(self, data):
        self.d = data
        bps, spc, res, nfats, nroot, tot, media, spf = struct.unpack_from("<HBHBHHBH", data, 11)
        if data[510:512] != b"\x55\xaa" or bps != 512 or spf == 0:
            raise SystemExit("--boot image: not a FAT12 floppy image")
        self.spc, self.res, self.nfats, self.nroot, self.spf = spc, res, nfats, nroot, spf
        self.root = (res + nfats * spf) * 512
        self.data_start = self.root + nroot * 32

    def entries(self):
        for i in range(self.nroot):
            e = self.d[self.root + i * 32:self.root + i * 32 + 32]
            if e[0] in (0, 0xE5) or e[11] & 0x08:
                continue
            name = e[0:8].decode("ascii").strip() + "." + e[8:11].decode("ascii").strip()
            yield name.rstrip("."), e

    def fat_next(self, c):
        off = self.res * 512 + c * 3 // 2
        v = struct.unpack_from("<H", self.d, off)[0]
        return (v >> 4) if c & 1 else (v & 0xFFF)

    def read(self, entry):
        size = struct.unpack_from("<I", entry, 28)[0]
        c = struct.unpack_from("<H", entry, 26)[0]
        out = bytearray()
        while 2 <= c < 0xFF8 and len(out) < size:
            off = self.data_start + (c - 2) * self.spc * 512
            out += self.d[off:off + self.spc * 512]
            c = self.fat_next(c)
        return bytes(out[:size])


# ---- writing the FAT12 partition ----
def fat_layout(sectors):
    root_secs = ROOT_ENTRIES * 32 // 512
    spf = 1
    while True:
        data = sectors - RESERVED - root_secs - NFATS * spf
        clusters = data // SPC
        need = math.ceil((clusters + 2) * 3 / 2 / 512)
        if need <= spf:
            break
        spf = need
    if clusters >= 4085:
        raise SystemExit("too many clusters for FAT12")
    return spf, root_secs, clusters


def dos_name(name):
    base, _, ext = name.upper().partition(".")
    if not base or len(base) > 8 or len(ext) > 3:
        raise SystemExit("not an 8.3 name: %s" % name)
    return base.ljust(8).encode("ascii") + ext.ljust(3).encode("ascii")


def dos_datetime(ts):
    t = datetime.datetime.fromtimestamp(ts)
    year = max(t.year, 1980)
    return ((t.hour << 11) | (t.minute << 5) | (t.second // 2),
            ((year - 1980) << 9) | (t.month << 5) | t.day)


def build(args):
    total = set_geometry(args.chips)
    psecs = total - PART_START
    spf, root_secs, clusters = fat_layout(psecs)
    img = bytearray(total * 512)

    # MBR
    mbr = bytearray(open(os.path.join(DIST, "MBR.BIN"), "rb").read())
    entry = bytes([0x80]) + chs(PART_START) + bytes([0x01]) + chs(total - 1) + struct.pack("<II", PART_START, psecs)
    mbr[0x1BE:0x1CE] = entry
    img[0:512] = mbr

    # boot sector: DOS one (patched BPB) or our stub
    if args.boot:
        floppy = Fat12Image(open(args.boot, "rb").read())
        vbr = bytearray(floppy.d[0:512])
        dos3 = vbr[0x26] != 0x29
    else:
        dos3 = False
        floppy = None
        vbr = bytearray(open(os.path.join(DIST, "VBRSTUB.BIN"), "rb").read())
        vbr[3:11] = b"ISAFLASH"
    if dos3:
        # DOS 3.x BPB ends at 1Dh; 1Eh.. belongs to the boot code. The boot drive is the byte at 1FDh.
        jmp = vbr[1] + 2 if vbr[0] == 0xEB else 0
        if jmp < 0x1E:
            raise SystemExit("--boot: unknown boot sector (jump to %02Xh)" % jmp)
        struct.pack_into("<HBHBHHBHHHH", vbr, 0x0B, 512, SPC, RESERVED, NFATS, ROOT_ENTRIES,
                         psecs, MEDIA, spf, SPT, HEADS, PART_START)
        if vbr[0x1FD] not in (0x00, 0x80):
            raise SystemExit("--boot: DOS 3.x boot sector without a drive byte at 1FDh")
        vbr[0x1FD] = 0x80
        print("boot sector  DOS 3.x (no extended BPB): EXPERIMENTAL, check it on the target machine")
    else:
        struct.pack_into("<HBHBHHBHHHII", vbr, 0x0B, 512, SPC, RESERVED, NFATS, ROOT_ENTRIES,
                         psecs if psecs < 0x10000 else 0, MEDIA, spf, SPT, HEADS, PART_START, 0)
        vbr[0x24] = 0x80                 # drive number
        vbr[0x25] = 0
        vbr[0x26] = 0x29
        struct.pack_into("<I", vbr, 0x27, 0x15A0F1A5)
        vbr[0x2B:0x36] = args.label.upper().ljust(11)[:11].encode("ascii")
        vbr[0x36:0x3E] = b"FAT12   "
    base = PART_START * 512
    img[base:base + 512] = vbr

    fat = bytearray(spf * 512)
    fat[0:3] = bytes([MEDIA, 0xFF, 0xFF])
    root = bytearray(root_secs * 512)
    data_base = base + (RESERVED + NFATS * spf + root_secs) * 512
    state = {"next": 2, "slot": 0}

    def set_fat(c, v):
        off = c * 3 // 2
        cur = struct.unpack_from("<H", fat, off)[0]
        cur = (cur & 0x000F) | (v << 4) if c & 1 else (cur & 0xF000) | v
        struct.pack_into("<H", fat, off, cur)

    def add_file(name, data, attr, ts):
        n = max(1, math.ceil(len(data) / (SPC * 512))) if data else 0
        first = state["next"] if n else 0
        if state["next"] + n - 2 > clusters:
            raise SystemExit("disk full while adding %s" % name)
        for i in range(n):
            c = state["next"] + i
            set_fat(c, c + 1 if i < n - 1 else 0xFFF)
            off = data_base + (c - 2) * SPC * 512
            chunk = data[i * SPC * 512:(i + 1) * SPC * 512]
            img[off:off + len(chunk)] = chunk
        state["next"] += n
        if state["slot"] >= ROOT_ENTRIES:
            raise SystemExit("root directory full")
        t, d = dos_datetime(ts)
        e = dos_name(name) + bytes([attr]) + bytes(10) + struct.pack("<HHHI", t, d, first, len(data))
        root[state["slot"] * 32:state["slot"] * 32 + 32] = e
        state["slot"] += 1

    label = args.label.upper().ljust(11)[:11].encode("ascii")
    if floppy:
        files = dict(floppy.entries())
        chosen = next((s for s in SYSTEM_SETS if all(n in files for n in s)), None)
        if not chosen:
            raise SystemExit("--boot: no IO.SYS/MSDOS.SYS, IBMBIO.COM/IBMDOS.COM or KERNEL.SYS on the floppy")
        for n in list(chosen) + (["COMMAND.COM"] if "COMMAND.COM" in files else []):
            e = files[n]
            add_file(n, floppy.read(e), e[11], datetime.datetime.now().timestamp())
            print("system file  %-12s %7d bytes" % (n, struct.unpack_from("<I", e, 28)[0]))
    root_label = label + bytes([0x08]) + bytes(20)
    for path in args.add or []:
        data = open(path, "rb").read()
        add_file(os.path.basename(path), data, 0x20, os.path.getmtime(path))
        print("file         %-12s %7d bytes" % (os.path.basename(path).upper(), len(data)))
    if state["slot"] < ROOT_ENTRIES:
        root[state["slot"] * 32:state["slot"] * 32 + 32] = root_label

    for i in range(NFATS):
        off = base + (RESERVED + i * spf) * 512
        img[off:off + len(fat)] = fat
    off = base + (RESERVED + NFATS * spf) * 512
    img[off:off + len(root)] = root
    print("disk: %d sectors (%d KB), C/H/S %d/%d/%d, FAT12 %d clusters of %d bytes, %d free"
          % (total, total // 2, total // (HEADS * SPT), HEADS, SPT, clusters, SPC * 512, clusters - state["next"] + 2))
    return bytes(img)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out")
    ap.add_argument("--chips", type=int, choices=(1, 2), required=True)
    ap.add_argument("--boot")
    ap.add_argument("--add", nargs="*")
    ap.add_argument("--label", default="FLASHDISK")
    ap.add_argument("--split", type=int, help="part size in KB (rounded down to whole 63.5 KB blocks)")
    args = ap.parse_args()
    img = build(args)
    with open(args.out, "wb") as f:
        f.write(img)
    print("wrote %s" % args.out)
    if args.split:
        lblk = LBLK_SECTORS * 512
        part = args.split * 1024 // lblk * lblk
        if not part:
            sys.exit("--split must be at least 64 KB")
        stem = os.path.splitext(args.out)[0]
        for i in range(0, len(img), part):
            name = "%s.%03d" % (stem, i // part + 1)
            with open(name, "wb") as f:
                f.write(img[i:i + part])
            print("FLWRITE %s /D /O:%X" % (os.path.basename(name).upper(), i // lblk))


if __name__ == "__main__":
    main()
