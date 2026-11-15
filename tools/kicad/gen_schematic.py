#!/usr/bin/env python3
"""Generate the rev A schematic of the ISA Flash Disk card (KiCad 9 format).

The schematic is built from an explicit pin -> net table (see build()).  Every pin of
every placed unit must be listed: a net name, a power net, or NC.  Connections are made
with short wire stubs and net labels / power symbols, so the drawing is a netlist
first and a picture second.  After the first commit the schematic is meant to be
edited in KiCad; this script documents how revision A was produced.

Usage: python tools/kicad/gen_schematic.py [--force]

The script refuses to overwrite a schematic whose SHA-256 differs from the one it
recorded last time (hardware/kicad/.generated.sha256), so edits made in KiCad are not
lost.  --force discards such edits.
Environment: KICAD9_SYMBOL_DIR overrides the KiCad symbol library location.
"""

import hashlib
import json
import os
import re
import sys
import uuid

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(REPO, "hardware", "kicad")
PROJECT = "isa-flash-disk"
KICAD_SYM = os.environ.get("KICAD9_SYMBOL_DIR", r"C:/Program Files/KiCad/9.0/share/kicad/symbols")
NS = uuid.UUID("0b7e5d1c-2f4a-4c8e-9d36-5a1f0e2b7c91")
ROOT_UUID = str(uuid.uuid5(NS, "root-sheet"))
PROJECT_LIB = "isa_flash_disk"

POWER_NETS = {"+5V": "power:+5V", "GND": "power:GND", "+12V": "power:+12V", "VPP": "power:VPP"}
NC = None
STUB = 2.54


def uid(key):
    return str(uuid.uuid5(NS, key))


def fmt(v):
    s = ("%.4f" % v).rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def file_sha256(path):
    """SHA-256 with CRLF folded to LF, so a git autocrlf checkout does not look like a manual edit."""
    with open(path, "rb") as f:
        return hashlib.sha256(f.read().replace(b"\r\n", b"\n")).hexdigest()


# --------------------------------------------------------------------------------------
# Symbol libraries
# --------------------------------------------------------------------------------------

def match_paren(text, start):
    depth = 0
    for j in range(start, len(text)):
        c = text[j]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return j + 1
    raise ValueError("unbalanced")


class SymbolLib:
    def __init__(self, nick, text):
        self.nick = nick
        self.text = text

    @classmethod
    def load(cls, nick, path):
        with open(path, encoding="utf-8") as f:
            return cls(nick, f.read())

    def raw(self, name):
        m = re.search(r'\n\t\(symbol "%s"\n' % re.escape(name), self.text)
        if not m:
            raise KeyError("%s:%s" % (self.nick, name))
        start = m.start() + 1
        return self.text[start:match_paren(self.text, start)]

    def flat(self, name):
        """Return the symbol block with any (extends ...) resolved."""
        block = self.raw(name)
        ext = re.search(r'\(extends "([^"]+)"\)', block)
        if not ext:
            return block
        parent_name = ext.group(1)
        out = self.flat(parent_name)
        out = out.replace('(symbol "%s"' % parent_name, '(symbol "%s"' % name, 1)
        out = out.replace('(symbol "%s_' % parent_name, '(symbol "%s_' % name)
        for prop in re.finditer(r'\(property "([^"]+)" "((?:[^"\\]|\\.)*)"', block):
            key, val = prop.group(1), prop.group(2)
            pat = r'(\(property "%s" ")((?:[^"\\]|\\.)*)(")' % re.escape(key)
            out = re.sub(pat, lambda mm: mm.group(1) + val.replace("\\", "\\\\") + mm.group(3), out, count=1)
        return out


class Symbol:
    """A flattened library symbol with its pins."""

    def __init__(self, lib, name):
        self.lib_id = "%s:%s" % (lib.nick, name)
        self.name = name
        self.block = lib.flat(name)
        self.pins = []  # dicts: unit, style, number, name, type, x, y, angle, hidden
        for m in re.finditer(r'\(symbol "%s_(\d+)_(\d+)"' % re.escape(name), self.block):
            sub = self.block[m.start():match_paren(self.block, m.start())]
            unit, style = int(m.group(1)), int(m.group(2))
            for p in re.finditer(
                    r'\(pin (\w+) (\w+)\s*\(at ([-\d.]+) ([-\d.]+) ([-\d.]+)\)\s*\(length ([\d.]+)\)\s*(\(hide yes\))?'
                    r'.*?\(name "((?:[^"\\]|\\.)*)".*?\(number "([^"]*)"', sub, re.S):
                self.pins.append({
                    "unit": unit, "style": style, "type": p.group(1), "x": float(p.group(3)),
                    "y": float(p.group(4)), "angle": int(float(p.group(5))), "hidden": bool(p.group(7)),
                    "name": p.group(8), "number": p.group(9),
                })
        self.units = max([p["unit"] for p in self.pins] + [1])

    def unit_pins(self, unit):
        return [p for p in self.pins if p["unit"] in (0, unit) and p["style"] in (0, 1)]

    def embedded(self):
        b = self.block.replace('(symbol "%s"' % self.name, '(symbol "%s"' % self.lib_id, 1)
        return "\t\t" + b.replace("\n", "\n\t") + "\n"


def flash_symbol_lib():
    """Project symbol library with the Intel 28F008SA (PSOP-44 pin numbers, DS fig. 3)."""
    name = "28F008SA"
    left = [("A%d" % i, n) for i, n in enumerate([16, 15, 14, 13, 10, 9, 8, 7, 6, 5, 4, 3, 42, 41, 40, 39, 38, 37, 36, 35])]
    ctrl = [("~{CE}", 43), ("~{OE}", 29), ("~{WE}", 30), ("~{RP}", 2)]
    right = [("DQ%d" % i, n) for i, n in enumerate([17, 18, 19, 20, 24, 25, 26, 27])]
    pins = []
    y = 27.94
    for pname, num in left:
        pins.append(("input", pname, num, -15.24, y, 0, False))
        y -= 2.54
    y = -25.4
    for pname, num in ctrl:
        pins.append(("input", pname, num, -15.24, y, 0, False))
        y -= 2.54
    y = 27.94
    for pname, num in right:
        pins.append(("bidirectional", pname, num, 15.24, y, 180, False))
        y -= 2.54
    pins.append(("output", "RY/~{BY}", 28, 15.24, 5.08, 180, False))
    pins.append(("power_in", "VCC", 44, -2.54, 38.1, 270, False))
    pins.append(("power_in", "VCC", 23, 0, 38.1, 270, False))
    pins.append(("power_in", "VPP", 1, 5.08, 38.1, 270, False))
    pins.append(("power_in", "GND", 21, -1.27, -40.64, 90, False))
    pins.append(("power_in", "GND", 22, 1.27, -40.64, 90, False))
    for i, num in enumerate((11, 12, 31, 32, 33, 34)):
        pins.append(("no_connect", "NC", num, 5.08, -12.7 - i * 2.54, 180, True))

    def font():
        return "(effects\n\t\t\t\t\t(font\n\t\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t\t)\n\t\t\t\t)"

    def prop(key, val, x, y, hide):
        h = "\n\t\t\t\t(hide yes)" if hide else ""
        return ('\t\t(property "%s" "%s"\n\t\t\t(at %s %s 0)\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n'
                '\t\t\t\t)%s\n\t\t\t)\n\t\t)\n' % (key, val, fmt(x), fmt(y), h))

    s = ['(kicad_symbol_lib\n\t(version 20241209)\n\t(generator "isa-flash-disk")\n\t(generator_version "1.0")\n']
    s.append('\t(symbol "%s"\n\t\t(exclude_from_sim no)\n\t\t(in_bom yes)\n\t\t(on_board yes)\n' % name)
    s.append(prop("Reference", "U", -10.16, 34.29, False))
    s.append(prop("Value", name, 3.81, -36.83, False))
    s.append(prop("Footprint", "%s:Intel_PSOP-44_P1.27mm" % PROJECT_LIB, 0, 0, True))
    s.append(prop("Datasheet", "docs/datasheets/intel-28f008sa-290429-008.pdf", 0, 0, True))
    s.append(prop("Description", "Intel 28F008SA 8 Mbit (1M x 8) FlashFile memory, 12 V VPP, 44-lead PSOP", 0, 0, True))
    s.append(prop("ki_keywords", "flash 28F008SA FlashFile Intel", 0, 0, True))
    s.append('\t\t(symbol "%s_0_1"\n\t\t\t(rectangle\n\t\t\t\t(start -10.16 33.02)\n\t\t\t\t(end 10.16 -35.56)\n'
             '\t\t\t\t(stroke\n\t\t\t\t\t(width 0.254)\n\t\t\t\t\t(type default)\n\t\t\t\t)\n'
             '\t\t\t\t(fill\n\t\t\t\t\t(type background)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n' % name)
    s.append('\t\t(symbol "%s_1_1"\n' % name)
    for ptype, pname, num, x, y, ang, hidden in pins:
        h = "\n\t\t\t\t(hide yes)" if hidden else ""
        s.append('\t\t\t(pin %s line\n\t\t\t\t(at %s %s %d)\n\t\t\t\t(length 5.08)%s\n\t\t\t\t(name "%s"\n\t\t\t\t\t%s\n'
                 '\t\t\t\t)\n\t\t\t\t(number "%d"\n\t\t\t\t\t%s\n\t\t\t\t)\n\t\t\t)\n'
                 % (ptype, fmt(x), fmt(y), ang, h, pname, font(), num, font()))
    s.append("\t\t)\n\t\t(embedded_fonts no)\n\t)\n)\n")
    return "".join(s)


# --------------------------------------------------------------------------------------
# Schematic writer
# --------------------------------------------------------------------------------------

class Schematic:
    def __init__(self):
        self.libs = {}
        self.symbols = {}
        self.items = []
        self.instances = []
        self.pwr_count = 0
        self.expected = {}  # net -> set of "REF.pin"

    def lib(self, nick):
        if nick not in self.libs:
            if nick == PROJECT_LIB:
                self.libs[nick] = SymbolLib(nick, flash_symbol_lib())
            else:
                self.libs[nick] = SymbolLib.load(nick, os.path.join(KICAD_SYM, nick + ".kicad_sym"))
        return self.libs[nick]

    def sym(self, lib_id):
        if lib_id not in self.symbols:
            nick, name = lib_id.split(":", 1)
            self.symbols[lib_id] = Symbol(self.lib(nick), name)
        return self.symbols[lib_id]

    # -- primitive items --------------------------------------------------------------

    def wire(self, x1, y1, x2, y2):
        self.items.append(
            "\t(wire\n\t\t(pts\n\t\t\t(xy %s %s) (xy %s %s)\n\t\t)\n\t\t(stroke\n\t\t\t(width 0)\n\t\t\t(type default)\n"
            '\t\t)\n\t\t(uuid "%s")\n\t)\n' % (fmt(x1), fmt(y1), fmt(x2), fmt(y2), uid("w%s%s%s%s" % (x1, y1, x2, y2))))

    def label(self, net, x, y, angle):
        just = {0: "left", 90: "left", 180: "right", 270: "right"}[angle]
        self.items.append(
            '\t(label "%s"\n\t\t(at %s %s %d)\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1.27 1.27)\n\t\t\t)\n'
            '\t\t\t(justify %s bottom)\n\t\t)\n\t\t(uuid "%s")\n\t)\n'
            % (net, fmt(x), fmt(y), angle, just, uid("l%s%s%s" % (net, x, y))))

    def no_connect(self, x, y):
        self.items.append('\t(no_connect\n\t\t(at %s %s)\n\t\t(uuid "%s")\n\t)\n' % (fmt(x), fmt(y), uid("nc%s%s" % (x, y))))

    def text(self, body, x, y, size=1.27):
        body = body.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        self.items.append(
            '\t(text "%s"\n\t\t(exclude_from_sim no)\n\t\t(at %s %s 0)\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size %s %s)\n'
            '\t\t\t)\n\t\t\t(justify left top)\n\t\t)\n\t\t(uuid "%s")\n\t)\n'
            % (body, fmt(x), fmt(y), fmt(size), fmt(size), uid("t" + body[:40] + str(x) + str(y))))

    def _symbol_instance(self, lib_id, ref, x, y, angle, unit, value, footprint, datasheet, fields, in_bom, hide_ref,
                         ref_xy, val_xy, justify=None, field_angle=0):
        s = self.sym(lib_id)
        key = "sym%s.%d" % (ref, unit)
        props = []

        def prop(k, v, px, py, hide, just=None, ang=0):
            h = "\n\t\t\t\t(hide yes)" if hide else ""
            j = "\n\t\t\t\t(justify %s)" % just if just else ""
            props.append('\t\t(property "%s" "%s"\n\t\t\t(at %s %s %d)\n\t\t\t(effects\n\t\t\t\t(font\n'
                         '\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)%s%s\n\t\t\t)\n\t\t)\n'
                         % (k, v.replace('"', '\\"'), fmt(px), fmt(py), ang, j, h))

        prop("Reference", ref, ref_xy[0], ref_xy[1], hide_ref, justify, field_angle)
        prop("Value", value, val_xy[0], val_xy[1], False, justify, field_angle)
        prop("Footprint", footprint, x, y, True)
        prop("Datasheet", datasheet, x, y, True)
        prop("Description", "", x, y, True)
        for k, v in fields.items():
            prop(k, v, x, y, True)
        pin_lines = "".join('\t\t(pin "%s"\n\t\t\t(uuid "%s")\n\t\t)\n' % (p["number"], uid(key + "pin" + p["number"]))
                            for p in s.unit_pins(unit))
        self.instances.append(
            '\t(symbol\n\t\t(lib_id "%s")\n\t\t(at %s %s %d)\n\t\t(unit %d)\n\t\t(exclude_from_sim no)\n'
            '\t\t(in_bom %s)\n\t\t(on_board yes)\n\t\t(dnp no)\n\t\t(uuid "%s")\n%s%s'
            '\t\t(instances\n\t\t\t(project "%s"\n\t\t\t\t(path "/%s"\n\t\t\t\t\t(reference "%s")\n'
            '\t\t\t\t\t(unit %d)\n\t\t\t\t)\n\t\t\t)\n\t\t)\n\t)\n'
            % (lib_id, fmt(x), fmt(y), angle, unit, "yes" if in_bom else "no", uid(key), "".join(props), pin_lines,
               PROJECT, ROOT_UUID, ref, unit))

    def power(self, net, x, y, direction):
        """Power symbol whose pin sits at (x, y), drawn pointing along direction."""
        self.pwr_count += 1
        ref = "#PWR%03d" % self.pwr_count
        if net == "GND":
            angle = {"down": 0, "up": 180, "left": 270, "right": 90}[direction]
        else:
            angle = {"up": 0, "left": 90, "down": 180, "right": 270}[direction]
        side = 3.3 if net == "GND" else 4.8
        off = {"up": (0, -3.81), "down": (0, 4.45), "left": (-side, 0), "right": (side, 0)}[direction]
        just = {"left": "right", "right": "left"}.get(direction)
        self._symbol_instance(POWER_NETS[net], ref, x, y, angle, 1, net, "", "", {}, False, True,
                              (x, y), (x + off[0], y + off[1]), just, 90 if just else 0)

    def pwr_flag(self, net, x, y):
        self.pwr_count += 1
        ref = "#FLG%03d" % self.pwr_count
        self._symbol_instance("power:PWR_FLAG", ref, x, y, 0, 1, "PWR_FLAG", "", "", {}, False, True,
                              (x, y - 5), (x, y - 3.2))
        self.wire(x, y, x + 7.62, y)
        self.power(net, x + 7.62, y, "down" if net == "GND" else "up")

    def junction(self, x, y):
        self.items.append('\t(junction\n\t\t(at %s %s)\n\t\t(diameter 0)\n\t\t(color 0 0 0 0)\n\t\t(uuid "%s")\n\t)\n'
                          % (fmt(x), fmt(y), uid("j%s%s" % (x, y))))

    def _finish_stubs(self, stubs):
        """Labels for signal stubs; neighbouring stubs of one power net share a wire and one symbol."""
        lines = {}
        for st in stubs:
            ex, ey, d, net = st
            key = (d, round(ex, 3)) if d in ("left", "right") else (d, round(ey, 3))
            lines.setdefault(key, []).append(st)
        for (d, _), line_stubs in sorted(lines.items()):
            along = 1 if d in ("left", "right") else 0
            line_stubs.sort(key=lambda st: st[along])
            runs = []
            for st in line_stubs:
                if runs and st[3] == runs[-1][-1][3] and st[3] in POWER_NETS:
                    runs[-1].append(st)
                else:
                    runs.append([st])
            for run in runs:
                net = run[0][3]
                if net not in POWER_NETS:
                    ex, ey, dd, nn = run[0]
                    self.label(nn, ex, ey, {"left": 180, "right": 0, "up": 90, "down": 270}[dd])
                    continue
                for a, b in zip(run, run[1:]):
                    self.wire(a[0], a[1], b[0], b[1])
                for mid in run[1:-1]:
                    self.junction(mid[0], mid[1])
                end = run[-1] if (net == "GND" and along == 1) else run[0]
                self.power(net, end[0], end[1], d)

    # -- parts --------------------------------------------------------------------------

    def place(self, ref, lib_id, x, y, nets, value, footprint="", datasheet="", fields=None, unit=1,
              side_text=False, text_offsets=None):
        s = self.sym(lib_id)
        pins = s.unit_pins(unit)
        numbers = {p["number"] for p in pins}
        nets = {str(k): v for k, v in nets.items()}
        unknown = set(nets) - {p["number"] for p in s.pins}
        if unknown:
            raise ValueError("%s: unknown pins %s" % (ref, sorted(unknown)))
        top = min([y - p["y"] for p in pins] + [y])
        bottom = max([y - p["y"] for p in pins] + [y])
        right = max([x + p["x"] for p in pins] + [x])
        if text_offsets:
            (rx, ry), (vx, vy) = text_offsets
            ref_xy, val_xy, just = (x + rx, y + ry), (x + vx, y + vy), "left"
        elif side_text:
            ref_xy, val_xy, just = (right + 1.27, y - 1.27), (right + 1.27, y + 1.27), "left"
        else:
            ref_xy, val_xy, just = (x + 2.54, top - 1.5), (x + 2.54, bottom + 2.5), None
        self._symbol_instance(lib_id, ref, x, y, 0, unit, value, footprint, datasheet, fields or {}, True, False,
                              ref_xy, val_xy, just)
        stubs = []
        seen = set()
        for p in pins:
            if p["number"] in seen:
                continue
            seen.add(p["number"])
            px, py = x + p["x"], y - p["y"]
            if p["hidden"]:
                if p["type"] != "no_connect":
                    raise ValueError("%s pin %s hidden but not NC" % (ref, p["number"]))
                continue
            if p["number"] not in nets:
                raise ValueError("%s unit %d pin %s (%s) not assigned" % (ref, unit, p["number"], p["name"]))
            net = nets[p["number"]]
            if net is NC:
                self.no_connect(px, py)
                continue
            self.expected.setdefault(net, set()).add("%s.%s" % (ref, p["number"]))
            dx, dy = {0: (-1, 0), 180: (1, 0), 90: (0, 1), 270: (0, -1)}[p["angle"]]
            ex, ey = px + dx * STUB, py + dy * STUB
            self.wire(px, py, ex, ey)
            direction = {(-1, 0): "left", (1, 0): "right", (0, 1): "down", (0, -1): "up"}[(dx, dy)]
            stubs.append((ex, ey, direction, net))
        self._finish_stubs(stubs)
        return numbers

    def write(self, path, title_block):
        lib_syms = "".join(self.symbols[k].embedded() for k in sorted(self.symbols))
        out = ['(kicad_sch\n\t(version 20250114)\n\t(generator "eeschema")\n\t(generator_version "9.0")\n',
               '\t(uuid "%s")\n\t(paper "A2")\n' % ROOT_UUID, title_block, "\t(lib_symbols\n", lib_syms, "\t)\n"]
        out.extend(self.items)
        out.extend(self.instances)
        out.append('\t(sheet_instances\n\t\t(path "/"\n\t\t\t(page "1")\n\t\t)\n\t)\n\t(embedded_fonts no)\n)\n')
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write("".join(out))


# --------------------------------------------------------------------------------------
# The card
# --------------------------------------------------------------------------------------

# All footprints live in the project library (copied by gen_footprints.py), hand-solder pads for 0805.
FP_SOIC20W = PROJECT_LIB + ":SOIC-20W_7.5x12.8mm_P1.27mm"
FP_SOIC16 = PROJECT_LIB + ":SOIC-16_3.9x9.9mm_P1.27mm"
FP_SOIC14 = PROJECT_LIB + ":SOIC-14_3.9x8.7mm_P1.27mm"
FP_SOT23 = PROJECT_LIB + ":SOT-23"
FP_R = PROJECT_LIB + ":R_0805_2012Metric_Pad1.20x1.40mm_HandSolder"
FP_C = PROJECT_LIB + ":C_0805_2012Metric_Pad1.18x1.45mm_HandSolder"
FP_LED = PROJECT_LIB + ":LED_0805_2012Metric_Pad1.15x1.40mm_HandSolder"
FP_TP = PROJECT_LIB + ":TestPoint_THTPad_D2.0mm_Drill1.0mm"
FP_SIP7 = PROJECT_LIB + ":R_Array_SIP7"
FP_SW5 = PROJECT_LIB + ":SW_DIP_SPSTx05_Slide_9.78x14.88mm_W7.62mm_P2.54mm"
FP_SW6 = PROJECT_LIB + ":SW_DIP_SPSTx06_Slide_9.78x17.42mm_W7.62mm_P2.54mm"
FP_JP = PROJECT_LIB + ":PinHeader_1x02_P2.54mm_Vertical"
DS = "docs/datasheets/"


def build():
    sch = Schematic()
    P5, G, P12, VPP = "+5V", "GND", "+12V", "VPP"

    # J1 - ISA 8-bit edge. Symbol pins 1..31 = B1..B31, 32..62 = A1..A31.
    isa = {1: G, 10: G, 31: G, 2: "RESET_DRV", 3: P5, 29: P5, 9: P12,
           11: "~{SMEMW}", 12: "~{SMEMR}", 13: "~{IOW}", 42: "AEN"}
    for i in range(8):
        isa[33 + i] = "SD%d" % (7 - i)
    for i in range(20):
        isa[43 + i] = "SA%d" % (19 - i)
    for p in (4, 5, 6, 7, 8, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 30, 32, 41):
        isa[p] = NC
    sch.place("J1", "Connector:Bus_ISA_8bit", 50.8, 139.7, isa, "ISA_8bit", "%s:ISA_8bit_Edge" % PROJECT_LIB,
              "docs/references/ibm-5160-technical-reference-6139821-1986.pdf")

    # Memory window decoder: SA19..SA13 vs (1, 1, SW1). P=Q low -> ~{MEM_HIT}.
    u3 = {1: G, 2: "SA13", 3: "MSW13", 4: "SA14", 5: "MSW14", 6: "SA15", 7: "MSW15", 8: "SA16", 9: "MSW16",
          11: "SA17", 12: "MSW17", 13: "SA18", 14: P5, 15: "SA19", 16: P5, 17: G, 18: G, 19: "~{MEM_HIT}",
          10: G, 20: P5}
    sch.place("U3", "74xx:74HCT688", 180.34, 88.9, u3, "74HCT688", FP_SOIC20W, DS + "ti-cd74hct688.pdf",
              {"MPN": "CD74HCT688M96"})
    # I/O port decoder: SA9..SA3, AEN vs (1, SW2, 0). P=Q low -> ~{IO_HIT}.
    u4 = {1: G, 2: "SA3", 3: "ISW3", 4: "SA4", 5: "ISW4", 6: "SA5", 7: "ISW5", 8: "SA6", 9: "ISW6",
          11: "SA7", 12: "ISW7", 13: "SA8", 14: "ISW8", 15: "SA9", 16: P5, 17: "AEN", 18: G, 19: "~{IO_HIT}",
          10: G, 20: P5}
    sch.place("U4", "74xx:74HCT688", 180.34, 172.72, u4, "74HCT688", FP_SOIC20W, DS + "ti-cd74hct688.pdf",
              {"MPN": "CD74HCT688M96"})

    # Address switches: ON = 0, OFF = 1 (pull-up).
    sw1 = {i: "MSW%d" % (12 + i) for i in range(1, 6)}
    sw1.update({i: G for i in range(6, 11)})
    sch.place("SW1", "Switch:SW_DIP_x05", 116.84, 76.2, sw1, "MEM SA13..SA17", FP_SW5)
    sw2 = {i: "ISW%d" % (2 + i) for i in range(1, 7)}
    sw2.update({i: G for i in range(7, 13)})
    sch.place("SW2", "Switch:SW_DIP_x06", 116.84, 114.3, sw2, "IO SA3..SA8", FP_SW6)
    # Pull-ups: bussed 6 x 10k SIP-7 networks, common pin 1 to +5 V (THT, easy to hand-solder).
    rn1 = {1: P5, 2: "MSW13", 3: "MSW14", 4: "MSW15", 5: "MSW16", 6: "MSW17", 7: NC}
    sch.place("RN1", "Device:R_Network06", 106.68, 152.4, rn1, "6x10k bussed", FP_SIP7, side_text=True)
    rn2 = {1: P5, 2: "ISW3", 3: "ISW4", 4: "ISW5", 5: "ISW6", 6: "ISW7", 7: "ISW8"}
    sch.place("RN2", "Device:R_Network06", 137.16, 152.4, rn2, "6x10k bussed", FP_SIP7, side_text=True)

    # Port strobes: Y0 = BANK (base+0), Y1 = CTRL (base+1), only on IOW with ~{IO_HIT}.
    u5 = {1: "SA0", 2: "SA1", 3: "SA2", 4: "~{IO_HIT}", 5: "~{IOW}", 6: P5, 15: "~{BANK_WR}", 14: "~{CTRL_WR}",
          13: NC, 12: NC, 11: NC, 10: NC, 9: NC, 7: NC, 8: G, 16: P5}
    sch.place("U5", "74xx:74HCT138", 254.0, 66.04, u5, "74HCT138", FP_SOIC16, DS + "ti-sn74hct138.pdf",
              {"MPN": "SN74HCT138DR"})
    # BANK register: Q6..Q0 -> flash A19..A13, Q7 -> CHIP (0 = U1, 1 = U2). Cleared by reset.
    u6 = {1: "~{RST}", 11: "~{BANK_WR}", 3: "SD0", 4: "SD1", 7: "SD2", 8: "SD3", 13: "SD4", 14: "SD5", 17: "SD6",
          18: "SD7", 2: "FA13", 5: "FA14", 6: "FA15", 9: "FA16", 12: "FA17", 15: "FA18", 16: "FA19", 19: "CHIP",
          10: G, 20: P5}
    sch.place("U6", "74xx:74HCT273", 254.0, 137.16, u6, "74HCT273", FP_SOIC20W, DS + "ti-sn74hct273.pdf",
              {"MPN": "SN74HCT273DWR"})
    # CTRL register: D0 = WE_EN, D1 = VPP_EN. Cleared by reset.
    u7 = {1: "~{RST}", 9: "~{CTRL_WR}", 4: "SD0", 5: "SD1", 12: G, 13: G, 2: NC, 3: "~{WE_EN}", 7: "VPP_EN",
          6: NC, 10: NC, 11: NC, 15: NC, 14: NC, 8: G, 16: P5}
    sch.place("U7", "74xx:74LS175", 254.0, 213.36, u7, "74HCT175", FP_SOIC16, DS + "ti-cd74hct175.pdf",
              {"MPN": "CD74HCT175M96"})

    # Data buffer: A = ISA, B = flash. DIR = ~{SMEMR} (high: ISA -> flash), enabled inside the window only.
    u8 = {1: "~{SMEMR}", 19: "~{MEM_HIT}", 10: G, 20: P5}
    for i in range(8):
        u8[2 + i] = "SD%d" % i
        u8[18 - i] = "FD%d" % i
    sch.place("U8", "74xx:74LS245", 327.66, 76.2, u8, "74LS245", FP_SOIC20W, DS + "ti-sn74ls245.pdf",
              {"MPN": "SN74LS245DWR"})

    # Glue: CE0 = MEM_HIT | CHIP, CE1 = MEM_HIT | ~CHIP, FWE = SMEMW | ~WE_EN.
    or_nets = {1: "~{MEM_HIT}", 2: "CHIP", 3: "~{CE0}", 4: "~{MEM_HIT}", 5: "~{CHIP}", 6: "~{CE1}",
               9: "~{SMEMW}", 10: "~{WE_EN}", 8: "~{FWE}", 12: G, 13: G, 11: NC, 7: G, 14: P5}
    for unit, y in ((1, 132.08), (2, 152.4), (3, 172.72), (4, 193.04), (5, 228.6)):
        sch.place("U9", "74xx:74LS32", 320.04, y, or_nets, "74HCT32", FP_SOIC14, DS + "ti-sn74hct32.pdf",
                  {"MPN": "SN74HCT32DR"}, unit=unit)
    inv_nets = {1: "RESET_DRV", 2: "~{RST}", 3: "CHIP", 4: "~{CHIP}", 5: G, 6: NC, 9: G, 8: NC, 11: G, 10: NC,
                13: G, 12: NC, 7: G, 14: P5}
    for unit, y in ((1, 132.08), (2, 147.32), (3, 162.56), (4, 177.8), (5, 193.04), (6, 208.28), (7, 241.3)):
        sch.place("U10", "74xx:74HCT04", 370.84, y, inv_nets, "74HCT04", FP_SOIC14, DS + "ti-sn74hct04.pdf",
                  {"MPN": "SN74HCT04DR"}, unit=unit)

    # Flash. A12..A0 straight from ISA, A19..A13 from BANK.
    for ref, x, ce, ryby in (("U1", 447.04, "~{CE0}", "RYBY0"), ("U2", 533.4, "~{CE1}", "RYBY1")):
        f = {43: ce, 29: "~{SMEMR}", 30: "~{FWE}", 2: "~{RST}", 28: ryby, 1: VPP, 44: P5, 23: P5, 21: G, 22: G}
        anum = [16, 15, 14, 13, 10, 9, 8, 7, 6, 5, 4, 3, 42, 41, 40, 39, 38, 37, 36, 35]
        for i, n in enumerate(anum):
            f[n] = "SA%d" % i if i <= 12 else "FA%d" % i
        for i, n in enumerate([17, 18, 19, 20, 24, 25, 26, 27]):
            f[n] = "FD%d" % i
        sch.place(ref, "%s:28F008SA" % PROJECT_LIB, x, 132.08, f, "PA28F008SA", "%s:Intel_PSOP-44_P1.27mm" % PROJECT_LIB,
                  DS + "intel-28f008sa-290429-008.pdf", {"MPN": "PA28F008SA-85 / -120 (salvaged)"},
                  text_offsets=((10.16, -35.56), (10.16, 38.1)))

    # VPP switch (AP-359 fig. 3): JP1 open -> no +12 V; VPP_EN = 1 -> Q2 pulls Q1 gate low.
    y0 = 287.02
    sch.place("JP1", "Jumper:Jumper_2_Open", 76.2, y0, {1: P12, 2: "12V_SW"}, "WRITE",
              FP_JP)
    sch.place("R1", "Device:R", 109.22, y0, {1: "12V_SW", 2: "Q1_G"}, "10k", FP_R, side_text=True)
    sch.place("Q1", "Transistor_FET:AO3401A", 134.62, y0, {1: "Q1_G", 2: "12V_SW", 3: VPP}, "AO3407A", FP_SOT23,
              DS + "aos-ao3407a.pdf", {"MPN": "AO3407A"}, side_text=True)
    sch.place("Q2", "Transistor_FET:2N7002", 160.02, y0, {1: "VPP_EN", 2: G, 3: "Q1_G"}, "2N7002L", FP_SOT23,
              DS + "onsemi-2n7002l.pdf", {"MPN": "2N7002LT1G"}, side_text=True)
    sch.place("R3", "Device:R", 185.42, y0, {1: "VPP_EN", 2: G}, "100k", FP_R, side_text=True)
    sch.place("R2", "Device:R", 210.82, y0, {1: VPP, 2: G}, "10k", FP_R, side_text=True)
    sch.place("R4", "Device:R", 236.22, y0, {1: VPP, 2: "VPP_LED"}, "4.7k", FP_R, side_text=True)
    sch.place("D2", "Device:LED", 261.62, y0, {2: "VPP_LED", 1: G}, "RED VPP", FP_LED)
    sch.place("C16", "Device:C", 287.02, y0, {1: P12, 2: G}, "1uF 25V", FP_C, side_text=True)
    sch.place("C13", "Device:C", 312.42, y0, {1: VPP, 2: G}, "100nF", FP_C, side_text=True)
    sch.place("C14", "Device:C", 337.82, y0, {1: VPP, 2: G}, "100nF", FP_C, side_text=True)

    # Activity LED: lit while the address is inside the window.
    sch.place("R5", "Device:R", 375.92, y0, {1: P5, 2: "ACT_LED"}, "1.5k", FP_R, side_text=True)
    sch.place("D1", "Device:LED", 401.32, y0, {2: "ACT_LED", 1: "~{MEM_HIT}"}, "GREEN ACT", FP_LED)

    # Test points.
    tps = [("TP1", P12), ("TP2", VPP), ("TP3", G), ("TP4", P5), ("TP5", "~{FWE}"), ("TP6", "RYBY0"), ("TP7", "RYBY1")]
    for i, (ref, net) in enumerate(tps):
        sch.place(ref, "Connector:TestPoint", 431.8 + i * 20.32, y0 - 7.62, {1: net}, net.replace("~{", "").replace("}", "#"),
                  FP_TP, side_text=True)

    # Decoupling: 100 nF per logic IC and per flash VCC pin, 10 uF bulk on +5 V.
    caps = ["C%d" % i for i in range(1, 13)] + ["C15"]
    for i, ref in enumerate(caps):
        sch.place(ref, "Device:C", 76.2 + i * 20.32, 335.28, {1: P5, 2: G}, "10uF" if ref == "C15" else "100nF", FP_C, side_text=True)

    # Power flags.
    for i, net in enumerate((P5, G, P12, VPP)):
        sch.pwr_flag(net, 353.06 + i * 25.4, 335.28)

    sch.text("ISA Flash Disk rev A - UNTESTED DESIGN, NOT FOR PRODUCTION\n"
             "Defaults: window CC000h (SW1: 1=SA13 ON, 2=SA14 OFF, 3=SA15 OFF, 4=SA16 ON, 5=SA17 ON)\n"
             "          ports 2A0h (SW2: 1=SA3 ON, 2=SA4 ON, 3=SA5 OFF, 4=SA6 ON, 5=SA7 OFF, 6=SA8 ON)\n"
             "Switch ON = 0, OFF = 1. SA19 = SA18 = 1 and SA9 = 1 are fixed; AEN must be 0 for ports.\n"
             "BANK (base+0): bits 6..0 = flash A19..A13, bit 7 = chip (0 = U1, 1 = U2).\n"
             "CTRL (base+1): bit 0 = WE_EN, bit 1 = VPP_EN. Both registers clear on RESET DRV.\n"
             "JP1 WRITE is NOT fitted by default: without it VPP < 6.5 V and the flash cannot be altered.\n"
             "See docs/architecture.md and docs/memory-map.md.", 20.32, 368.3, 1.778)
    sch.text("ISA edge: symbol pins 1..31 = B1..B31, 32..62 = A1..A31 (IBM XT Technical Reference 1-17, 1-18).\n"
             "B8 (XT -CARD SLCTD / AT 0WS) is not connected: do not use slot J8 of an IBM 5160.", 20.32, 30.48, 1.27)
    return sch


def main():
    sch = build()
    os.makedirs(OUT_DIR, exist_ok=True)
    tb = ('\t(title_block\n\t\t(title "ISA Flash Disk")\n\t\t(date "2026-11-15")\n\t\t(rev "A")\n'
          '\t\t(comment 1 "8-bit ISA flash disk, 1-2 x Intel 28F008SA")\n'
          '\t\t(comment 2 "Untested design - not for production")\n\t)\n')
    sch_path = os.path.join(OUT_DIR, PROJECT + ".kicad_sch")
    stamp_path = os.path.join(OUT_DIR, ".generated.sha256")
    if os.path.exists(sch_path) and "--force" not in sys.argv:
        recorded = open(stamp_path, encoding="utf-8").read().strip() if os.path.exists(stamp_path) else ""
        if recorded != file_sha256(sch_path):
            sys.exit("%s was changed after generation (edited in KiCad?). Refusing to overwrite it; "
                     "rerun with --force only if those edits may be discarded." % sch_path)
    sch.write(sch_path, tb)
    with open(stamp_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(file_sha256(sch_path) + "\n")
    with open(os.path.join(OUT_DIR, PROJECT_LIB + ".kicad_sym"), "w", encoding="utf-8", newline="\n") as f:
        f.write(flash_symbol_lib())
    with open(os.path.join(OUT_DIR, "sym-lib-table"), "w", encoding="utf-8", newline="\n") as f:
        f.write('(sym_lib_table\n\t(version 7)\n\t(lib (name "%s")(type "KiCad")(uri "${KIPRJMOD}/%s.kicad_sym")'
                '(options "")(descr "ISA Flash Disk project symbols"))\n)\n' % (PROJECT_LIB, PROJECT_LIB))
    with open(os.path.join(OUT_DIR, "fp-lib-table"), "w", encoding="utf-8", newline="\n") as f:
        f.write('(fp_lib_table\n\t(version 7)\n\t(lib (name "%s")(type "KiCad")(uri "${KIPRJMOD}/%s.pretty")'
                '(options "")(descr "ISA Flash Disk project footprints"))\n)\n' % (PROJECT_LIB, PROJECT_LIB))
    pro = os.path.join(OUT_DIR, PROJECT + ".kicad_pro")
    if not os.path.exists(pro):
        with open(pro, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"meta": {"filename": PROJECT + ".kicad_pro", "version": 3},
                       "sheets": [[ROOT_UUID, "Root"]]}, f, indent=2)
            f.write("\n")
    with open(os.path.join(OUT_DIR, "expected-nets.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump({k: sorted(v) for k, v in sorted(sch.expected.items())}, f, indent=1)
        f.write("\n")
    print("symbols:", len(sch.instances), "items:", len(sch.items), "nets:", len(sch.expected))


if __name__ == "__main__":
    main()
