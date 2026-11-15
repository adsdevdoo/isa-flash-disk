#!/usr/bin/env python3
"""Build the option ROM and the DOS utilities with NASM into dist/.

Usage: python tools/build_dos.py [path-to-nasm]
       (or set NASM=...; default: "nasm" from PATH)

Outputs: dist/FLASHROM.BIN (8192 bytes, checksum fixed), dist/FLINFO.COM, FLREAD.COM, FLWRITE.COM, FLFORMAT.COM, FLTEST.COM.
All sources are assembled with "cpu 8086", so nothing newer than an 8088 instruction can slip in.
"""

import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
INC = ROOT / "firmware" / "include"
NASM = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("NASM", "nasm")

ROM = (ROOT / "firmware" / "option-rom" / "flashrom.asm", "FLASHROM.BIN")
COMS = [(ROOT / "software" / "dos" / n, n.replace(".asm", ".COM").upper())
        for n in ("flinfo.asm", "flread.asm", "flwrite.asm", "flformat.asm", "fltest.asm")]
SECTORS = [(ROOT / "firmware" / "mbr" / "mbr.asm", "MBR.BIN"), (ROOT / "firmware" / "mbr" / "vbrstub.asm", "VBRSTUB.BIN")]


def nasm(src, out):
    # Relative paths from the repository root: NASM for Windows cannot open non-ASCII absolute paths.
    rel = lambda p: os.path.relpath(p, ROOT).replace(os.sep, "/")
    # -w-reloc-abs-word: .COM code addresses its .bss directly, which is correct in a flat binary
    cmd = [NASM, "-f", "bin", "-w+all", "-w-reloc-abs-word", "-I", rel(INC) + "/", "-I", rel(src.parent) + "/",
           "-o", rel(out), rel(src)]
    subprocess.run(cmd, check=True, cwd=ROOT)


def main():
    DIST.mkdir(exist_ok=True)
    src, name = ROM
    out = DIST / name
    nasm(src, out)
    data = bytearray(out.read_bytes())
    if len(data) != 8192 or data[:2] != b"\x55\xAA":
        sys.exit("bad ROM image size or signature")
    data[-1] = (-sum(data[:-1])) & 0xFF
    out.write_bytes(bytes(data))
    print("%-13s %5d bytes, checksum %02X" % (name, len(data), data[-1]))
    for src, name in COMS:
        out = DIST / name
        nasm(src, out)
        size = out.stat().st_size
        if size > 0xFF00 - 0x100 - 8192:
            sys.exit("%s too large for a .COM with its buffers" % name)
        print("%-13s %5d bytes" % (name, size))
    for src, name in SECTORS:
        out = DIST / name
        nasm(src, out)
        data = out.read_bytes()
        if len(data) != 512 or data[510:] != bytes([0x55, 0xAA]):
            sys.exit("%s must be one boot sector" % name)
        print("%-13s %5d bytes" % (name, len(data)))


if __name__ == "__main__":
    main()
