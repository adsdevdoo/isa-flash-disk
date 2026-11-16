"""Silkscreen of the ISA Flash Disk board (KiCad 9 Python), board rev B.

Standalone, on the routed board (copper is not touched):
    "C:/Program Files/KiCad/9.0/bin/python.exe" tools/kicad/silk_board.py [--force]

Removes the board-level silkscreen of hardware/kicad/isa-flash-disk.kicad_pcb, places reference designators,
values, function labels, the top title, the bottom information block and the switch tables again, checks the
result and saves the board. Board graphics get UUIDs from their sorted content, so a rerun gives the same
file. Refuses to touch a board edited in KiCad after the last generation (.generated-pcb.sha256) unless
--force is given; exit code 1 if a label finds no free place or two silkscreen texts / a text and a pad
end up too close.

route_board.py calls place_silkscreen() before the GND stitching on a full re-route, so the stitching vias
still keep out of the text; this module is the only place where the silkscreen is defined.
"""

import hashlib
import pathlib
import re
import sys
import uuid

import pcbnew as p
import wx

wx.DisableAsserts()

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from make_board import OX, OY, W, BODY_BOTTOM, V  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
HW = ROOT / "hardware" / "kicad"
BOARD = HW / "isa-flash-disk.kicad_pcb"
STAMP = HW / ".generated-pcb.sha256"

REV = "B"
DATE = "2026-11-16"
# Silkscreen limits taken over from retro535 (JLCPCB): text >= 1.0 mm, stroke 0.15 mm, clearance 0.15 mm.
TEXT_SIZE = 1.0
TEXT_THICK = 0.15
PAD_GAP, TEXT_GAP = 0.2, 0.15  # final check: text to pad, text to text

TP_LABEL = {"TP1": "+12V", "TP2": "VPP", "TP3": "GND", "TP4": "+5V", "TP5": "WE#", "TP6": "R/B0", "TP7": "R/B1"}
TP_TOP_ROW = ("TP1", "TP2", "TP6", "TP7")  # along the top edge: label above the pad


def tp_prefer(ref):
    return ("above", "below", "right", "left") if ref in TP_TOP_ROW else ("below", "above", "right", "left")
# Part type printed next to the designator of ICs, transistors and resistor networks (value field of the
# footprint, shortened where noted).
VALUE_SHORT = {"PA28F008SA": "28F008SA", "6x10k bussed": "6x10k"}


def sha(path):
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def text(b, s, x, y, size=TEXT_SIZE, layer=p.F_SilkS, bold=False, justify=None):
    t = p.PCB_TEXT(b)
    t.SetText(s)
    t.SetPosition(V(x, y))
    t.SetLayer(layer)
    t.SetTextSize(p.VECTOR2I(p.FromMM(size), p.FromMM(size)))
    t.SetTextThickness(p.FromMM(TEXT_THICK * (1.4 if bold else 1.0)))
    if justify == "left":
        t.SetHorizJustify(p.GR_TEXT_H_ALIGN_LEFT)
    elif justify == "right":
        t.SetHorizJustify(p.GR_TEXT_H_ALIGN_RIGHT)
    if layer == p.B_SilkS:
        t.SetMirrored(True)
    b.Add(t)
    return t


def seg(b, a, z, layer, width=TEXT_THICK):
    s = p.PCB_SHAPE(b)
    s.SetShape(p.SHAPE_T_SEGMENT)
    s.SetStart(V(*a))
    s.SetEnd(V(*z))
    s.SetLayer(layer)
    s.SetWidth(p.FromMM(width))
    b.Add(s)
    return s


def mm_box(bb):
    return (p.ToMM(bb.GetLeft()) - OX, p.ToMM(bb.GetTop()) - OY, p.ToMM(bb.GetRight()) - OX,
            p.ToMM(bb.GetBottom()) - OY)


def shape_boxes(g, m=0.0):
    """Boxes of a silkscreen shape (drawing mm, grown by m); a rectangle outline is split into its sides."""
    w = p.ToMM(g.GetWidth()) / 2 + m
    if g.GetShape() == p.SHAPE_T_RECT and not g.IsFilled():
        a, z = g.GetStart(), g.GetEnd()
        x0, x1 = sorted((p.ToMM(a.x) - OX, p.ToMM(z.x) - OX))
        y0, y1 = sorted((p.ToMM(a.y) - OY, p.ToMM(z.y) - OY))
        return [(x0 - w, y0 - w, x1 + w, y0 + w), (x0 - w, y1 - w, x1 + w, y1 + w),
                (x0 - w, y0 - w, x0 + w, y1 + w), (x1 - w, y0 - w, x1 + w, y1 + w)]
    x0, y0, x1, y1 = mm_box(g.GetBoundingBox())
    return [(x0 - m, y0 - m, x1 + m, y1 + m)]


def text_box(t):
    """Exact box of the drawn strokes (drawing coordinates, mm)."""
    return mm_box(t.GetEffectiveTextShape().BBox())


class SilkPlacer:
    """Puts each text at the first candidate spot that clears all pads, all courtyards (so designators stay
    readable after assembly), the texts already placed, the card edge and the contact tab."""

    def __init__(self, fps, vias, bottom=False):
        self.obst, self.texts = [], []
        for f in fps.values():
            for pad in f.Pads():
                if bottom and not (pad.HasHole() or pad.IsOnLayer(p.B_Cu)):
                    continue
                self.obst.append(self.rect(pad.GetBoundingBox(), 0.25))
            crt = f.GetCourtyard(p.F_CrtYd)
            if crt.OutlineCount() and not bottom:
                self.obst.append(self.rect(crt.BBox(), 0.1))
            # the footprint's own silkscreen (outlines, pin-1 marks) may reach past the courtyard
            for g in f.GraphicalItems():
                if g.GetClass() == "PCB_SHAPE" and g.GetLayer() == (p.B_SilkS if bottom else p.F_SilkS):
                    self.obst.extend(shape_boxes(g, 0.2))
        for v in vias:
            self.obst.append(self.rect(v.GetBoundingBox(), 0.2))

    @staticmethod
    def rect(bb, m=0.0):
        return (p.ToMM(bb.GetLeft()) - OX - m, p.ToMM(bb.GetTop()) - OY - m,
                p.ToMM(bb.GetRight()) - OX + m, p.ToMM(bb.GetBottom()) - OY + m)

    @staticmethod
    def size(s, h):
        return len(s) * 0.92 * h + 0.3, h + 0.3

    def free(self, r):
        if r[0] < 0.8 or r[1] < 0.8 or r[2] > W - 0.8 or r[3] > BODY_BOTTOM - 0.8:
            return False
        return not any(r[0] < o[2] and o[0] < r[2] and r[1] < o[3] and o[1] < r[3] for o in self.obst + self.texts)

    def place(self, s, candidates, h=TEXT_SIZE):
        w, hh = self.size(s, h)
        for cx, cy in candidates:
            r = (cx - w / 2, cy - hh / 2, cx + w / 2, cy + hh / 2)
            if self.free(r):
                self.texts.append(r)
                return cx, cy
        raise RuntimeError("no free silkscreen spot for %r" % s)

    def around(self, box, s, h=TEXT_SIZE, prefer=("above", "below", "left", "right")):
        w, hh = self.size(s, h)
        x0, y0, x1, y1 = box
        cx, cy, g = (x0 + x1) / 2, (y0 + y1) / 2, 0.3
        spots = {
            "above": [(x0 + (x1 - x0) * k, y0 - g - hh / 2) for k in (0.5, 0.25, 0.75, 0.0, 1.0)],
            "below": [(x0 + (x1 - x0) * k, y1 + g + hh / 2) for k in (0.5, 0.25, 0.75, 0.0, 1.0)],
            "left": [(x0 - g - w / 2, y0 + (y1 - y0) * k) for k in (0.5, 0.0, 1.0)],
            "right": [(x1 + g + w / 2, y0 + (y1 - y0) * k) for k in (0.5, 0.0, 1.0)],
        }
        cands = [c for side in prefer for c in spots[side]]
        for d in (1.0, 2.0, 3.0):  # then a little further out
            cands += [(cx, y0 - g - hh / 2 - d), (cx, y1 + g + hh / 2 + d), (x0 - g - w / 2 - d, cy), (x1 + g + w / 2 + d, cy)]
        return self.place(s, cands, h)

    def box(self, f):
        crt = f.GetCourtyard(p.F_CrtYd)
        return self.rect(crt.BBox()) if crt.OutlineCount() else self.rect(f.GetBoundingBox(False, False))

    def claim(self, r, what):
        if not self.free(r):
            raise RuntimeError("%s overlaps copper or text at %s" % (what, tuple(round(v, 2) for v in r)))
        self.texts.append(r)


def place_silkscreen(b, fps):
    vias = []  # vias are tented; silkscreen may cross them
    sp = SilkPlacer(fps, vias)
    order = sorted(fps, key=lambda r: (not r.startswith("U"), not r.startswith("SW"), r))
    ref_at = {}
    for ref in order:
        f = fps[ref]
        fld = f.Reference()
        fld.SetTextSize(p.VECTOR2I(p.FromMM(TEXT_SIZE), p.FromMM(TEXT_SIZE)))
        fld.SetTextThickness(p.FromMM(TEXT_THICK))
        if ref.startswith("TP") or (ref.startswith("H") and ref[1:].isdigit()) or ref == "J1":
            fld.SetVisible(False)
            continue
        prefer = ("right", "left", "above", "below") if ref.startswith("RN") else ("above", "below", "left", "right")
        x, y = sp.around(sp.box(f), ref, prefer=prefer)
        fld.SetPosition(V(x, y))
        fld.SetTextAngle(p.EDA_ANGLE(0, p.DEGREES_T))
        ref_at[ref] = (x, y)
    # Function labels.
    for ref, label in TP_LABEL.items():
        x, y = sp.around(sp.box(fps[ref]), label, prefer=tp_prefer(ref))
        text(b, label, x, y)
    for ref, label in (("SW1", "MEM"), ("SW2", "I/O")):
        x, y = sp.around(sp.box(fps[ref]), label, prefer=("below", "above"))
        text(b, label, x, y)
    x, y = sp.around(sp.box(fps["JP1"]), "WRITE", prefer=("above", "left", "right", "below"))
    text(b, "WRITE", x, y)
    for ref, label in (("D1", "ACT"), ("D2", "VPP")):
        f = fps[ref]
        c = [pd for pd in f.Pads() if pd.GetNumber() == "1"][0]
        kx, ky, kx1, ky1 = sp.rect(c.GetBoundingBox(), 0.0)
        x, y = sp.around((kx, ky, kx1, ky1), "K", prefer=("left", "above", "below", "right"))
        text(b, "K", x, y)
        x, y = sp.around(sp.box(f), label, prefer=("below", "above", "right", "left"))
        text(b, label, x, y)
    # Title block in the free area between the flash and the logic rows.
    lines = [("ISA FLASH DISK  rev " + REV, 1.5), ("2x 28F008SA  1-2 MB", TEXT_SIZE),
             ("github.com/adsdevdoo/isa-flash-disk", TEXT_SIZE), ("SW: ON = 0, default MEM CC000 I/O 2A0", TEXT_SIZE),
             ("JP1 open = write protected", TEXT_SIZE)]
    y = 46.0
    for s, h in lines:
        cands = [(cx, cy) for cy in [y + d * 0.5 for d in range(0, 30)] for cx in [26.0 + dx for dx in (0, -4, 4, -8, 8, -12, 12)]]
        x, y = sp.place(s, cands, h)
        text(b, s, x, y, h, bold=(h > TEXT_SIZE))
        y += h + 0.9
    # Address bit next to every switch position (top side).
    for ref, bits in (("SW1", range(13, 18)), ("SW2", range(3, 9))):
        f = fps[ref]
        x0 = sp.box(f)[0]
        for n, bit in enumerate(bits, 1):
            pad = [pd for pd in f.Pads() if pd.GetNumber() == str(n)][0]
            py = p.ToMM(pad.GetPosition().y) - OY
            label = "A%d" % bit
            w, _ = sp.size(label, TEXT_SIZE)
            x, y = sp.place(label, [(x0 - 0.3 - w / 2, py)])
            text(b, label, x, y)
    # Slot orientation, as on other 8-bit cards: contact numbers at both ends, side name, arrow to the bracket.
    ty = BODY_BOTTOM - 1.6
    ys = [ty - 0.3 * k for k in range(0, 10)]
    for label, x in (("A31", 2.54), ("A1", 78.74)):
        x, y = sp.place(label, [(x + dx, yy) for yy in ys for dx in (0, 1.5, -1.5)])
        text(b, label, x, y)
    s = "8-BIT ISA  COMPONENT SIDE"
    x, y = sp.place(s, [(cx, yy) for yy in ys for cx in (40.6, 34.0, 47.0)])
    text(b, s, x, y)
    ay = BODY_BOTTOM - 4.0
    x0, x1 = 84.0, 96.0
    s = "BRACKET"
    tx, tyy = sp.place(s, [((x0 + x1) / 2, ay - 1.4), ((x0 + x1) / 2, ay - 2.0)])
    text(b, s, tx, tyy)
    sp.texts.append((x0 - 0.2, ay - 0.9, x1 + 0.2, ay + 0.9))
    for a, z in (((x0, ay), (x1, ay)), ((x1, ay), (x1 - 1.4, ay - 0.8)), ((x1, ay), (x1 - 1.4, ay + 0.8))):
        seg(b, a, z, p.F_SilkS, 0.2)
    # Rev B: part type next to the designator of every IC, transistor and resistor network.
    for ref in sorted(fps, key=lambda r: (re.sub(r"\d", "", r), int(re.sub(r"\D", "", r) or 0))):
        if not re.fullmatch(r"(U|Q|RN)\d+", ref) or ref not in ref_at:
            continue
        val = fps[ref].GetValue()
        val = VALUE_SHORT.get(val, val)
        place_value(b, sp, fps[ref], ref_at[ref], val)

    place_bottom(b, fps, vias, ys)
    return sp.texts


def place_value(b, sp, f, ref_xy, s):
    """Value after the designator on its line; else designator and value moved together around the part;
    else the value alone (left of the designator, around the part, finally vertical beside it)."""
    ref = f.GetReference()
    w, hh = sp.size(s, TEXT_SIZE)
    rw, _ = sp.size(ref, TEXT_SIZE)
    rx, ry = ref_xy
    try:
        x, y = sp.place(s, [(rx + rw / 2 + 0.4 + w / 2, ry)])
        text(b, s, x, y)
        return
    except RuntimeError:
        pass
    rrect = (rx - rw / 2, ry - hh / 2, rx + rw / 2, ry + hh / 2)
    sp.texts.remove(rrect)
    combo = ref + " " + s
    try:
        cx, cy = sp.around(sp.box(f), combo, prefer=("above", "below", "left", "right"))
    except RuntimeError:
        sp.texts.append(rrect)
    else:
        wc, _ = sp.size(combo, TEXT_SIZE)
        f.Reference().SetPosition(V(cx - wc / 2 + rw / 2, cy))
        text(b, s, cx + wc / 2 - w / 2, cy)
        return
    try:
        x, y = sp.place(s, [(rx - rw / 2 - 0.4 - w / 2, ry)])
    except RuntimeError:
        try:
            x, y = sp.around(sp.box(f), s, prefer=("below", "above", "right", "left"))
        except RuntimeError:
            # last resort: vertical, reading bottom to top, beside the part
            x0, y0, x1, y1 = sp.box(f)
            cy = (y0 + y1) / 2
            for g in (0.3, 0.6, 1.0, 1.5, 2.0):
                for cx in (x1 + g + hh / 2, x0 - g - hh / 2):
                    for dy in (0.0, -1.0, 1.0, -2.0, 2.0):
                        r = (cx - hh / 2, cy + dy - w / 2, cx + hh / 2, cy + dy + w / 2)
                        if sp.free(r):
                            sp.texts.append(r)
                            t = text(b, s, cx, cy + dy)
                            t.SetTextAngle(p.EDA_ANGLE(90, p.DEGREES_T))
                            return
            raise RuntimeError("no free silkscreen spot for %r (%s)" % (s, ref))
    text(b, s, x, y)


# ---------------------------------------------------------------------------------------------
# Bottom side. Seen from below the drawing is mirrored: view coordinate u (from the left edge seen from
# the bottom) = W - drawing x. Mirrored text with left justification starts at its anchor in the view.
# ---------------------------------------------------------------------------------------------

def place_bottom(b, fps, vias, ys):
    spb = SilkPlacer(fps, vias, bottom=True)
    BS = p.B_SilkS

    def btext(s, u, y, h=TEXT_SIZE, bold=False):
        t = text(b, s, W - u, y, h, layer=BS, bold=bold, justify="left")
        x0, y0, x1, y1 = text_box(t)
        spb.claim((x0 - 0.15, y0 - 0.15, x1 + 0.15, y1 + 0.15), "bottom text %r" % s)
        return W - x0  # right end in view coordinates

    def bline(u0, y0, u1, y1, width=TEXT_THICK):
        seg(b, (W - u0, y0), (W - u1, y1), BS, width)

    for label, x in (("B31", 2.54), ("B1", 78.74)):
        x, y = spb.place(label, [(x + dx, yy) for yy in ys for dx in (0, 1.5, -1.5)])
        text(b, label, x, y, layer=BS)
    s = "8-BIT ISA  SOLDER SIDE"
    x, y = spb.place(s, [(cx, yy) for yy in ys for cx in (40.6, 34.0, 47.0)])
    text(b, s, x, y, layer=BS)

    # Switch tables (right column seen from below), as on rev A.
    sw1 = ("SW1  MEM WINDOW   ON = 0", ["SW1", "1", "2", "3", "4", "5"], ["bit", "A13", "A14", "A15", "A16", "A17"],
           [["C8000", "ON", "ON", "OFF", "ON", "ON"], ["CC000 *", "ON", "OFF", "OFF", "ON", "ON"],
            ["D0000", "ON", "ON", "ON", "OFF", "ON"], ["E0000", "ON", "ON", "ON", "ON", "OFF"]])
    sw2 = ("SW2  I/O PORT   ON = 0", ["SW2", "1", "2", "3", "4", "5", "6"], ["bit", "A3", "A4", "A5", "A6", "A7", "A8"],
           [["280", "ON", "ON", "ON", "ON", "OFF", "ON"], ["2A0 *", "ON", "ON", "OFF", "ON", "OFF", "ON"],
            ["300", "ON", "ON", "ON", "ON", "ON", "OFF"]])
    rects = []
    y = 9.0
    for title, head1, head2, rows in (sw1, sw2):
        rects.append(silk_table(b, 44.0, y, title, [head1, head2] + rows))
        y = rects[-1][3] + 2.5
    for r in rects:
        spb.claim(r, "switch table")
    ru = W - 44.0  # left edge of the right column, view coordinates
    for s in ("* default", "JP1 WRITE open = write protected",
              "+12V for writing: 11.4..12.6 V at TP1",
              "D1 ACT green: card window accessed",
              "D2 VPP red: write voltage switched on",
              "DOS: FLINFO FLREAD FLWRITE FLFORMAT FLTEST"):
        btext(s, ru, y)
        y += 2.0

    # Title block (left column seen from below).
    u0, u1, y0, y1 = 6.0, 58.0, 41.0, 52.4
    end = btext("ISA FLASH DISK", u0 + 2.0, y0 + 2.6, 2.0, bold=True)
    btext("rev " + REV, end + 2.0, y0 + 2.75, 1.5, bold=True)
    btext("8-bit ISA flash disk for IBM PC XT, AT, 286-486", u0 + 2.0, y0 + 6.3)
    btext("1-2x Intel 28F008SA = 1-2 MB, boots DOS (INT 13h)", u0 + 2.0, y0 + 9.3)
    for a, z in (((u0, y0), (u1, y0)), ((u1, y0), (u1, y1)), ((u1, y1), (u0, y1)), ((u0, y1), (u0, y0))):
        bline(*a, *z, 0.2)
    spb.texts.append((W - u1 - 0.2, y0 - 0.2, W - u0 + 0.2, y1 + 0.2))

    # I/O registers (docs/memory-map.md).
    regs = ("I/O REGISTERS   base = SW2", ["port", "name", "write"],
            [["base+0", "BANK", "7: chip U1/U2, 6..0: bank"], ["base+1", "CTRL", "0: WE_EN, 1: VPP_EN"]])
    r = silk_table(b, W - u0, y1 + 2.4, regs[0], [regs[1]] + regs[2], widths=(12.0, 10.0, 30.0), bold_rows=1)
    spb.claim(r, "register table")
    y = r[3] + 1.9
    for s in ("After RESET DRV: BANK = CTRL = 00h:", "chip U1, bank 0, write and VPP off.",
              "Bank bits 6..0 = flash A19..A13.", "", "github.com/adsdevdoo/isa-flash-disk"):
        if s:
            btext(s, u0, y)
        y += 2.0

    # Test points, labelled on the bottom as well (measured from the solder side).
    for ref, label in TP_LABEL.items():
        x, y = spb.around(spb.box(fps[ref]), label, prefer=tp_prefer(ref))
        text(b, label, x, y, layer=BS)


def silk_table(b, x_left_seen_from_bottom, y_top, title, rows, cw0=10.0, cw=5.0, rh=2.3, widths=None, bold_rows=2):
    """A ruled table on the bottom silkscreen. It is mirrored on the drawing: seen from the bottom its left
    edge is at x_left_seen_from_bottom and its columns run towards smaller x on the top-view drawing."""
    ncol = len(rows[0])
    widths = list(widths) if widths else [cw0] + [cw] * (ncol - 1)
    total = sum(widths)
    x0 = x_left_seen_from_bottom          # drawing x of the visible left edge
    nrows = len(rows) + 1
    bottom = y_top + nrows * rh

    for k in range(nrows + 1):
        yy = y_top + k * rh
        seg(b, (x0, yy), (x0 - total, yy), p.B_SilkS)
    acc = 0.0
    for i in range(ncol + 1):
        seg(b, (x0 - acc, y_top + (0 if i in (0, ncol) else rh)), (x0 - acc, bottom), p.B_SilkS)
        if i < ncol:
            acc += widths[i]
    text(b, title, x0 - total / 2, y_top + rh / 2, TEXT_SIZE, layer=p.B_SilkS, bold=True)
    for r, cells in enumerate(rows, 1):
        acc = 0.0
        for i, cell in enumerate(cells):
            text(b, cell, x0 - acc - widths[i] / 2, y_top + r * rh + rh / 2, TEXT_SIZE, layer=p.B_SilkS,
                 bold=(r <= bold_rows or i == 0))
            acc += widths[i]
    return (x0 - total, y_top, x0, bottom)


def set_title_block(b):
    tb = b.GetTitleBlock()
    tb.SetTitle("ISA Flash Disk: 8-bit ISA flash disk, 2x Intel 28F008SA")
    tb.SetRevision(REV)
    tb.SetDate(DATE)
    tb.SetComment(0, "rev A ordered 2026-11-15; rev B: silkscreen only (values, bottom info block), copper as rev A")
    tb.SetComment(1, "Not tested in hardware")


# ---------------------------------------------------------------------------------------------
# Standalone run: checks and a deterministic file
# ---------------------------------------------------------------------------------------------

def final_check(b):
    """Exact stroke boxes: texts against texts and pads on the same side; bottom lines against pads."""
    fail = []
    for layer, cu in ((p.F_SilkS, p.F_Cu), (p.B_SilkS, p.B_Cu)):
        texts = [(text_box(d), "'%s'" % d.GetText()) for d in b.GetDrawings()
                 if d.GetLayer() == layer and d.GetClass() == "PCB_TEXT"]
        for f in b.GetFootprints():
            for fld in (f.Reference(), f.Value()):
                if fld.IsVisible() and fld.GetLayer() == layer:
                    texts.append((text_box(fld), "%s field" % f.GetReference()))
            for g in f.GraphicalItems():
                if g.GetClass() == "PCB_TEXT" and g.GetLayer() == layer and g.IsVisible():
                    texts.append((text_box(g), "%s text '%s'" % (f.GetReference(), g.GetText())))
        pads = [(mm_box(pd.GetBoundingBox()), "%s.%s" % (f.GetReference(), pd.GetNumber()))
                for f in b.GetFootprints() for pd in f.Pads() if pd.IsOnLayer(cu)]
        lines = [(mm_box(d.GetBoundingBox()), "line") for d in b.GetDrawings()
                 if d.GetLayer() == layer and d.GetClass() == "PCB_SHAPE"]
        fp_silk = [(bx, "silk of %s" % f.GetReference()) for f in b.GetFootprints() for g in f.GraphicalItems()
                   if g.GetClass() == "PCB_SHAPE" and g.GetLayer() == layer for bx in shape_boxes(g)]

        def hit(a, c, g):
            return a[0] < c[2] + g and c[0] < a[2] + g and a[1] < c[3] + g and c[1] < a[3] + g

        for i, (a, ta) in enumerate(texts):
            for c, tc in texts[i + 1:]:
                if hit(a, c, TEXT_GAP):
                    fail.append("%s overlaps %s" % (ta, tc))
            for c, tc in pads:
                if hit(a, c, PAD_GAP):
                    fail.append("%s too close to pad %s" % (ta, tc))
            for c, tc in fp_silk:
                if hit(a, c, TEXT_GAP):
                    fail.append("%s too close to %s" % (ta, tc))
        for a, _ in lines:
            for c, tc in pads:
                if hit(a, c, PAD_GAP):
                    fail.append("silkscreen line at %.1f,%.1f too close to pad %s" % (a[0], a[1], tc))
    return fail


def stable_uuids(path):
    """KiCad orders board graphics with the (random) UUID as a tie breaker: sort the top-level gr_* blocks
    by content and number them, so reruns give the same file."""
    lines = path.read_text(encoding="utf-8").split("\n")
    blocks, i, first, last = [], 0, None, None
    while i < len(lines):
        if re.match(r"^\t\(gr_\w+", lines[i]):
            j = i
            while lines[j] != "\t)":
                j += 1
            if last is not None and i != last + 1:
                raise SystemExit("board graphics are not contiguous in %s" % path)
            first = i if first is None else first
            blocks.append(lines[i:j + 1])
            last, i = j, j + 1
            continue
        i += 1
    if not blocks:
        return
    keyed = sorted(("\n".join(x for x in blk if not x.startswith("\t\t(uuid ")), blk) for blk in blocks)
    out = []
    for n, (_, blk) in enumerate(keyed):
        u = str(uuid.uuid5(uuid.NAMESPACE_URL, "isa-flash-disk/board/gr/%d" % n))
        out += ['\t\t(uuid "%s")' % u if x.startswith("\t\t(uuid ") else x for x in blk]
    lines[first:last + 1] = out
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main():
    if "--force" not in sys.argv:
        recorded = STAMP.read_text(encoding="utf-8").strip() if STAMP.exists() else ""
        if recorded != sha(BOARD):
            sys.exit("%s was changed after generation (edited in KiCad?). Refusing to overwrite it; "
                     "rerun with --force only if those edits may be discarded." % BOARD)
    b = p.LoadBoard(str(BOARD))
    for d in list(b.GetDrawings()):
        if d.GetLayer() in (p.F_SilkS, p.B_SilkS):
            b.Delete(d)
    fps = {f.GetReference(): f for f in b.GetFootprints()}
    try:
        place_silkscreen(b, fps)
    except RuntimeError as e:
        sys.exit("silkscreen: %s" % e)
    set_title_block(b)
    fail = final_check(b)
    b.SetFileName(str(BOARD))
    p.SaveBoard(str(BOARD), b, True)  # True: the .kicad_pro stays as it is
    stable_uuids(BOARD)
    STAMP.write_text(sha(BOARD) + "\n", encoding="utf-8", newline="\n")
    n = sum(1 for d in b.GetDrawings() if d.GetClass() == "PCB_TEXT")
    print("silkscreen rev %s: %d board texts" % (REV, n))
    if fail:
        print("SILKSCREEN PROBLEMS:\n  " + "\n  ".join(fail))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
