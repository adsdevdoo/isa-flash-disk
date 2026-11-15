"""8086 PC model for testing the ISA Flash Disk option ROM and DOS utilities without hardware.

Needs the Unicorn engine (pip install unicorn==2.1.4). Models:
* the card: BANK/CTRL registers, 8 KB memory window, WE# gated by CTRL.WE_EN, VPP present only with
  CTRL.VPP_EN and the WRITE jumper (docs/architecture.md);
* two 28F008SA chips: Read Array / Intelligent Identifier / Status modes, byte write (only 1 -> 0), 64 KB block
  erase, SR.3 when VPP is low, command sequence errors (datasheet 290429-008, tables 3 and 4);
* a minimal BIOS: real interrupt vectoring through the IVT, INT 10h teletype, a floppy that is never ready,
  INT 16h keys, BIOS data area with a tick counter that advances on every read of 0040:006C;
* a minimal DOS: INT 21h file I/O on a host directory, memory allocation, console, exit codes;
* power failure: Card.fail_at = n lets n program/erase operations complete, the next one is lost and the run
  stops ("powerfail"); Card.reset() is the power-on reset (RESET DRV, RP#).

This is a functional model, not a timing model: it shows that the code drives the card as the datasheet
describes, it does not prove ISA bus timing.
"""

import os
import struct

from unicorn import Uc, UcError, UC_ARCH_X86, UC_MODE_16, UC_HOOK_INTR, UC_HOOK_INSN, UC_HOOK_MEM_READ, \
    UC_HOOK_MEM_WRITE, UC_PROT_ALL
from unicorn.x86_const import UC_X86_REG_AX, UC_X86_REG_BX, UC_X86_REG_CX, UC_X86_REG_DX, UC_X86_REG_SI, \
    UC_X86_REG_DI, UC_X86_REG_BP, UC_X86_REG_SP, UC_X86_REG_IP, UC_X86_REG_CS, UC_X86_REG_DS, UC_X86_REG_ES, \
    UC_X86_REG_SS, UC_X86_REG_EFLAGS, UC_X86_INS_IN, UC_X86_INS_OUT

CF, IF, TF = 0x0001, 0x0200, 0x0100
STUB_SEG = 0xF000          # every IVT entry points to F000:n*8 = "int 0FEh; retf 2" until code hooks it
STOP_INT = 0xFD            # "int 0FDh" ends a run


class Flash:
    """One 28F008SA."""

    def __init__(self):
        self.mem = bytearray(b"\xff" * 0x100000)
        self.mode = "array"
        self.sr = 0x80
        self.expect = None
        self.programs = 0
        self.erases = 0
        self.block_erases = [0] * 16
        self.busy = 0                   # status reads that still show SR.7 = 0 (busy)
        self.erase_polls = {}           # block -> status reads an erase takes (a worn block erases slowly)
        self.erase_fail = set()         # blocks whose erase ends with SR.5 (erase error)
        self.stuck1 = {}                # address -> bits that cannot be programmed to 0

    def read(self, addr):
        if self.mode == "array":
            return self.mem[addr]
        if self.mode == "id":
            return 0x89 if (addr & 1) == 0 else 0xA2
        if self.busy:
            self.busy -= 1
            return self.sr & 0x7F
        return self.sr

    def write(self, addr, val, vpp_ok):
        if self.expect == "program":
            self.expect = None
            self.mode = "status"
            if not vpp_ok:
                self.sr |= 0x08 | 0x10
            else:
                self.mem[addr] &= val
                self.mem[addr] |= self.stuck1.get(addr, 0)
                if self.mem[addr] != (self.mem[addr] & val):
                    self.sr |= 0x10     # the write state machine could not program every bit
                self.programs += 1
            self.sr |= 0x80
            return
        if self.expect == "erase":
            self.expect = None
            self.mode = "status"
            if val != 0xD0:
                self.sr |= 0x30
            elif not vpp_ok:
                self.sr |= 0x08 | 0x20
            elif (addr >> 16) in self.erase_fail:
                self.sr |= 0x20
            else:
                base = addr & 0xF0000
                self.busy = self.erase_polls.get(addr >> 16, 0)
                self.mem[base:base + 0x10000] = b"\xff" * 0x10000
                self.erases += 1
                self.block_erases[base >> 16] += 1
            self.sr |= 0x80
            return
        if val == 0xFF:
            self.mode = "array"
        elif val == 0x90:
            self.mode = "id"
        elif val == 0x70:
            self.mode = "status"
        elif val == 0x50:
            self.sr = 0x80
        elif val in (0x40, 0x10):
            self.expect = "program"
            self.mode = "status"
        elif val == 0x20:
            self.expect = "erase"
            self.mode = "status"


class Card:
    def __init__(self, chips=2, jumper=True, port=0x2A0, window=0xCC00):
        self.flash = [Flash() for _ in range(chips)]
        self.jumper = jumper
        self.port = port
        self.window = window
        self.bank = 0
        self.ctrl = 0
        self.bank_writes = 0
        self.ops = 0                    # completed program and erase operations
        self.fail_at = None             # power fails before operation number fail_at + 1
        self.dead = False

    def reset(self):
        """Power on: RESET DRV clears BANK and CTRL, RP# puts the chips into Read Array."""
        self.bank = self.ctrl = 0
        self.dead, self.fail_at = False, None
        for f in self.flash:
            f.mode, f.expect, f.sr = "array", None, 0x80

    def linear(self, off):
        return self.bank >> 7, ((self.bank & 0x7F) << 13) | off

    def win_read(self, off):
        chip, addr = self.linear(off)
        if chip >= len(self.flash):
            return 0xFF                 # nothing drives the bus
        return self.flash[chip].read(addr)

    def win_write(self, off, val):
        if not (self.ctrl & 0x01):
            return                      # WE# held high by the CTRL register
        chip, addr = self.linear(off)
        if self.dead or chip >= len(self.flash):
            return
        f = self.flash[chip]
        if f.expect in ("program", "erase"):
            if self.fail_at is not None and self.ops >= self.fail_at:
                self.dead = True        # the operation never happens
                return
            self.ops += 1
        f.write(addr, val, bool(self.ctrl & 0x02) and self.jumper)

    def out(self, port, val):
        if port == self.port:
            self.bank = val & 0xFF
            self.bank_writes += 1
        elif port == self.port + 1:
            self.ctrl = val & 0xFF

    def image(self):
        return b"".join(bytes(f.mem) for f in self.flash)

    def view(self):
        """What the 8 KB window shows now (same as win_read for every offset, built with slices)."""
        chip, base = self.bank >> 7, (self.bank & 0x7F) << 13
        if chip >= len(self.flash):
            return bytes([0xFF]) * 0x2000
        f = self.flash[chip]
        if f.mode == "array":
            return bytes(f.mem[base:base + 0x2000])
        if f.mode == "id":
            return bytes([0x89, 0xA2]) * 0x1000
        return bytes([f.sr]) * 0x2000


class PC:
    def __init__(self, card, files_dir, keys=b"Y"):
        self.card = card
        self.files_dir = files_dir
        self.keys = bytearray(keys)
        self.console = []
        self.exit_code = None
        self.stopped_by = None
        self.handles = {}
        self.next_handle = 5
        self.next_seg = 0x2000
        uc = self.uc = Uc(UC_ARCH_X86, UC_MODE_16)
        win = card.window * 16
        uc.mem_map(0, 0x100000, UC_PROT_ALL)
        self.view_key = None
        uc.hook_add(UC_HOOK_MEM_READ, self._win_rd, None, win, win + 0x1FFF)
        uc.hook_add(UC_HOOK_MEM_WRITE, self._win_wr, None, win, win + 0x1FFF)
        self.refresh_window(force=True)
        for n in range(256):
            uc.mem_write(n * 4, struct.pack("<HH", n * 8, STUB_SEG))
            uc.mem_write(STUB_SEG * 16 + n * 8, bytes([0xCD, 0xFE, 0xCA, 0x02, 0x00]))
        uc.mem_write(0x413, struct.pack("<H", 640))
        uc.mem_write(0x475, b"\x00")
        self.ticks = 0
        uc.hook_add(UC_HOOK_INTR, self._intr)
        uc.hook_add(UC_HOOK_INSN, self._in, None, 1, 0, UC_X86_INS_IN)
        uc.hook_add(UC_HOOK_INSN, self._out, None, 1, 0, UC_X86_INS_OUT)
        uc.hook_add(UC_HOOK_MEM_READ, self._tick, None, 0x46C, 0x46D)

    # ---- hardware ----
    # The window is ordinary RAM (Unicorn cannot fetch instructions from MMIO): every data read is preceded by
    # a hook that stores the model's value at that address, every write goes to the model, and the RAM copy is
    # re-rendered when the visible bank or the chip mode changes, so the option ROM can run from it.
    def _win_rd(self, uc, access, address, size, value, user):
        base = self.card.window * 16
        uc.mem_write(address, bytes(self.card.win_read(address - base + i) for i in range(size)))

    def _win_wr(self, uc, access, address, size, value, user):
        base = self.card.window * 16
        for i in range(size):
            self.card.win_write(address - base + i, (value >> (8 * i)) & 0xFF)
        if self.card.dead:
            self.stopped_by = "powerfail"
            uc.emu_stop()
            return
        self.refresh_window()

    def refresh_window(self, force=False):
        chip = self.card.bank >> 7
        f = self.card.flash[chip] if chip < len(self.card.flash) else None
        key = (self.card.bank, f.mode if f else None, f.sr if f and f.mode == "status" else None)
        if not force and key == self.view_key:
            return
        self.view_key = key
        if not force and key != (0, "array", None):
            return                      # data reads are hooked; only the ROM code in bank 0 is fetched from RAM
        self.uc.mem_write(self.card.window * 16, self.card.view())

    def _in(self, uc, port, size, user):
        return 0xFF

    def _out(self, uc, port, size, value, user):
        self.card.out(port, value)
        self.refresh_window()

    def _tick(self, uc, access, address, size, value, user):
        if address == 0x46C:
            self.ticks = (self.ticks + 1) & 0xFFFF
            uc.mem_write(0x46C, struct.pack("<H", self.ticks))

    # ---- registers and memory ----
    def r(self, reg):
        return self.uc.reg_read(reg)

    def w(self, reg, val):
        self.uc.reg_write(reg, val)

    def lin(self, seg, off):
        return (seg * 16 + off) & 0xFFFFF

    def read(self, addr, n):
        return bytes(self.uc.mem_read(addr, n))

    def set_cf(self, on):
        fl = self.r(UC_X86_REG_EFLAGS)
        self.w(UC_X86_REG_EFLAGS, (fl | CF) if on else (fl & ~CF))

    def push(self, val):
        sp = (self.r(UC_X86_REG_SP) - 2) & 0xFFFF
        self.w(UC_X86_REG_SP, sp)
        self.uc.mem_write(self.lin(self.r(UC_X86_REG_SS), sp), struct.pack("<H", val & 0xFFFF))

    # ---- interrupts ----
    def _intr(self, uc, intno, user):
        if intno == STOP_INT:
            self.stopped_by = "stop"
            uc.emu_stop()
            return
        if intno == 0xFE:
            n = (self.r(UC_X86_REG_IP) - 2) // 8
            self.service(n)
            return
        # real vectoring through the IVT (the INT instruction has already advanced IP)
        seg_off = struct.unpack("<HH", self.read(intno * 4, 4))
        self.push(self.r(UC_X86_REG_EFLAGS))
        self.push(self.r(UC_X86_REG_CS))
        self.push(self.r(UC_X86_REG_IP))
        self.w(UC_X86_REG_EFLAGS, self.r(UC_X86_REG_EFLAGS) & ~(IF | TF))
        self.w(UC_X86_REG_CS, seg_off[1])
        self.w(UC_X86_REG_IP, seg_off[0])

    def service(self, n):
        ah = (self.r(UC_X86_REG_AX) >> 8) & 0xFF
        al = self.r(UC_X86_REG_AX) & 0xFF
        if n == 0x10:
            if ah == 0x0E:
                self.console.append(chr(al))
        elif n == 0x13:
            dl = self.r(UC_X86_REG_DX) & 0xFF
            if dl < 0x80:
                self.w(UC_X86_REG_AX, (0x80 << 8) | al)   # floppy: timeout, no disk
            else:
                self.w(UC_X86_REG_AX, (0x01 << 8) | al)
            self.set_cf(ah != 0x00 or dl < 0x80)
        elif n == 0x16:
            key = self.keys.pop(0) if self.keys else 0x0D
            self.w(UC_X86_REG_AX, key)
        elif n == 0x18:
            self.stopped_by = "bios-int18"
            self.uc.emu_stop()
        elif n == 0x19:
            self.stopped_by = "bios-int19"
            self.uc.emu_stop()
        elif n == 0x20:
            self.exit_code = 0
            self.uc.emu_stop()
        elif n == 0x21:
            self.dos(ah, al)
        elif n == 0x23:
            self.exit_code = 3
            self.uc.emu_stop()

    def dos_str(self, seg, off, term=0):
        out = bytearray()
        addr = self.lin(seg, off)
        while True:
            c = self.read(addr, 1)[0]
            if c == term:
                return bytes(out)
            out.append(c)
            addr += 1

    def host(self, name):
        return os.path.join(self.files_dir, name.decode("ascii").upper())

    def dos(self, ah, al):
        R = self.r
        ds, dx, bx, cx = R(UC_X86_REG_DS), R(UC_X86_REG_DX), R(UC_X86_REG_BX), R(UC_X86_REG_CX)
        ok = True
        if ah == 0x01:
            key = self.keys.pop(0) if self.keys else 0x0D
            self.console.append(chr(key))
            self.w(UC_X86_REG_AX, (ah << 8) | key)
        elif ah == 0x02:
            self.console.append(chr(dx & 0xFF))
        elif ah == 0x09:
            self.console.append(self.dos_str(ds, dx, ord("$")).decode("latin-1"))
        elif ah == 0x25:
            self.uc.mem_write(al * 4, struct.pack("<HH", dx, ds))
        elif ah == 0x35:
            off, seg = struct.unpack("<HH", self.read(al * 4, 4))
            self.w(UC_X86_REG_BX, off)
            self.w(UC_X86_REG_ES, seg)
        elif ah in (0x3C, 0x3D):
            path = self.host(self.dos_str(ds, dx))
            try:
                f = open(path, "w+b" if ah == 0x3C else "rb")
            except OSError:
                ok = False
                self.w(UC_X86_REG_AX, 2)
            else:
                h = self.next_handle
                self.next_handle += 1
                self.handles[h] = f
                self.w(UC_X86_REG_AX, h)
        elif ah == 0x3E:
            self.handles.pop(bx).close()
        elif ah == 0x3F:
            data = self.handles[bx].read(cx)
            self.uc.mem_write(self.lin(ds, dx), data)
            self.w(UC_X86_REG_AX, len(data))
        elif ah == 0x40:
            self.handles[bx].write(self.read(self.lin(ds, dx), cx))
            self.w(UC_X86_REG_AX, cx)
        elif ah == 0x42:
            off = (cx << 16) | dx
            pos = self.handles[bx].seek(off, al)
            self.w(UC_X86_REG_AX, pos & 0xFFFF)
            self.w(UC_X86_REG_DX, pos >> 16)
        elif ah == 0x48:
            seg = self.next_seg
            self.next_seg += bx
            if self.next_seg > 0x9000:
                ok = False
                self.w(UC_X86_REG_AX, 8)
            else:
                self.w(UC_X86_REG_AX, seg)
        elif ah == 0x4A:
            pass
        elif ah == 0x4C:
            self.exit_code = al
            self.uc.emu_stop()
        else:
            raise RuntimeError("DOS function %02Xh not modelled" % ah)
        self.set_cf(not ok)

    # ---- running code ----
    def run(self, cs, ip, timeout_s=120):
        self.stopped_by = None
        try:
            # 16-bit mode: emu_start takes a linear address and sets IP = address - CS base, so CS first
            self.w(UC_X86_REG_CS, cs)
            self.uc.emu_start(self.lin(cs, ip), 0xFFFFFF, timeout=int(timeout_s * 1e6))
        except UcError as e:
            raise RuntimeError("CPU fault at %04X:%04X: %s" % (self.r(UC_X86_REG_CS), self.r(UC_X86_REG_IP), e))

    def run_com(self, com_bytes, args=""):
        """Load a .COM at 1000:0100 with a PSP and run it until it exits."""
        seg = 0x1000
        psp = bytearray(256)
        psp[0:2] = b"\xcd\x20"
        tail = (" " + args) if args else ""
        psp[0x80] = len(tail)
        psp[0x81:0x81 + len(tail)] = tail.encode("ascii")
        psp[0x81 + len(tail)] = 0x0D
        self.uc.mem_write(self.lin(seg, 0), bytes(psp) + com_bytes)
        # programs are loaded at the same address one after another: drop translated code of the previous one
        self.uc.ctl_remove_cache(self.lin(seg, 0), self.lin(seg, 0) + 0x10000)
        for reg in (UC_X86_REG_CS, UC_X86_REG_DS, UC_X86_REG_ES, UC_X86_REG_SS):
            self.w(reg, seg)
        self.w(UC_X86_REG_SP, 0xFFFE)
        self.uc.mem_write(self.lin(seg, 0xFFFE), b"\x00\x00")
        self.w(UC_X86_REG_EFLAGS, IF | 0x0002)
        self.exit_code = None
        self.console = []
        self.run(seg, 0x100)
        if self.exit_code is None:
            raise RuntimeError("program did not exit, stopped at %04X:%04X" % (self.r(UC_X86_REG_CS), self.r(UC_X86_REG_IP)))
        return self.exit_code, "".join(self.console)

    def far_call(self, seg, off, stack=(0x0030, 0x0400)):
        """Far-call seg:off like the BIOS ROM scan; returns when the code does RETF."""
        self.w(UC_X86_REG_SS, stack[0])
        self.w(UC_X86_REG_SP, stack[1])
        stop_off = 0x0F00
        self.uc.mem_write(self.lin(STUB_SEG, stop_off), bytes([0xCD, STOP_INT]))
        self.push(STUB_SEG)
        self.push(stop_off)
        self.w(UC_X86_REG_EFLAGS, IF | 0x0002)
        self.console = []
        self.refresh_window(force=True)
        self.run(seg, off, timeout_s=60)
        if self.stopped_by is None:
            raise RuntimeError("far call %04X:%04X did not return (timeout?)" % (seg, off))
        return "".join(self.console)

    def call_int(self, n, regs, stack=(0x0030, 0x0400)):
        """Execute 'int n' with the given registers (dict of UC regs) and stop right after it returns."""
        code_seg, code_off = 0x0070, 0
        self.uc.mem_write(self.lin(code_seg, code_off), bytes([0xCD, n, 0xCD, STOP_INT]))
        self.uc.ctl_remove_cache(self.lin(code_seg, code_off), self.lin(code_seg, code_off) + 16)
        self.w(UC_X86_REG_SS, stack[0])
        self.w(UC_X86_REG_SP, stack[1])
        for reg, val in regs.items():
            self.w(reg, val)
        self.w(UC_X86_REG_EFLAGS, IF | 0x0002)
        self.console = []
        self.run(code_seg, code_off, timeout_s=600)
        if self.stopped_by is None:
            raise RuntimeError("int %02Xh did not return (timeout?), at %04X:%04X"
                               % (n, self.r(UC_X86_REG_CS), self.r(UC_X86_REG_IP)))
        return self.stopped_by
