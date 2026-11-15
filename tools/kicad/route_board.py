"""Import the FreeRouting session, pour GND on both layers, add silkscreen, save the final board.

Run with KiCad 9 Python after make_board.py and FreeRouting:
    java -jar freerouting-2.5.0.jar -de hardware/kicad/build/placed.dsn -do hardware/kicad/build/placed.ses -mp 100
    "C:/Program Files/KiCad/9.0/bin/python.exe" tools/kicad/route_board.py [--force]

Writes hardware/kicad/isa-flash-disk.kicad_pcb and merges the board rules into isa-flash-disk.kicad_pro.
Refuses to overwrite a board that was edited in KiCad after the last run (see .generated-pcb.sha256).
"""

import hashlib
import json
import re
import pathlib
import sys

import pcbnew as p
import wx

wx.DisableAsserts()

ROOT = pathlib.Path(__file__).resolve().parents[2]
HW = ROOT / "hardware" / "kicad"
BUILD = HW / "build"
BOARD = HW / "isa-flash-disk.kicad_pcb"
PRO = HW / "isa-flash-disk.kicad_pro"
STAMP = HW / ".generated-pcb.sha256"

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from make_board import OX, OY, W, H, BODY_BOTTOM, V  # noqa: E402

# Silkscreen limits taken over from retro535 (JLCPCB): text >= 1.0 mm, stroke 0.15 mm, clearance 0.15 mm.
TEXT_SIZE = 1.0
TEXT_THICK = 0.15

TP_LABEL = {"TP1": "+12V", "TP2": "VPP", "TP3": "GND", "TP4": "+5V", "TP5": "WE#", "TP6": "R/B0", "TP7": "R/B1"}


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


def gnd_zone(b, layer):
    z = p.ZONE(b)
    z.SetLayer(layer)
    z.SetNet(b.FindNet("GND"))
    z.SetLocalClearance(p.FromMM(0.25))
    z.SetMinThickness(p.FromMM(0.2))
    z.SetPadConnection(p.ZONE_CONNECTION_THERMAL)
    z.SetThermalReliefGap(p.FromMM(0.3))
    z.SetThermalReliefSpokeWidth(p.FromMM(0.4))
    z.SetIslandRemovalMode(p.ISLAND_REMOVAL_MODE_ALWAYS)
    z.SetZoneName("GND_" + ("top" if layer == p.F_Cu else "bottom"))
    o = z.Outline()
    o.NewOutline()
    for x, y in ((0, 0), (W, 0), (W, BODY_BOTTOM - 0.4), (0, BODY_BOTTOM - 0.4)):
        o.Append(V(x, y))
    b.Add(z)


def stitch_gnd(b, avoid=(), pitch=3.0, via_d=0.8, via_drill=0.4, clearance=0.25):
    """Tracks cut the GND pours into islands that get removed. Drop GND vias on a grid wherever they clear
    every other-net object on both layers, refill, and keep only vias that landed in GND fill on both sides,
    so the islands are tied to the other layer."""
    gnd = b.FindNet("GND")
    segs, discs, rects = [], [], []
    for t in b.GetTracks():
        if t.GetNetCode() == gnd.GetNetCode():
            continue
        if t.GetClass() == "PCB_VIA":
            c = t.GetPosition()
            discs.append((p.ToMM(c.x) - OX, p.ToMM(c.y) - OY, p.ToMM(t.GetWidth(p.F_Cu)) / 2))
        else:
            s, e = t.GetStart(), t.GetEnd()
            segs.append(((p.ToMM(s.x) - OX, p.ToMM(s.y) - OY), (p.ToMM(e.x) - OX, p.ToMM(e.y) - OY),
                         p.ToMM(t.GetWidth()) / 2))
    for f in b.GetFootprints():
        for pad in f.Pads():
            if pad.GetNetCode() == gnd.GetNetCode() and not pad.HasHole():
                continue
            bb = pad.GetBoundingBox()
            rects.append((p.ToMM(bb.GetLeft()) - OX, p.ToMM(bb.GetTop()) - OY,
                          p.ToMM(bb.GetRight()) - OX, p.ToMM(bb.GetBottom()) - OY))
    rects.extend(avoid)  # keep stitching vias out of silkscreen text
    reach = via_d / 2 + clearance
    added = []
    y = 2.0
    while y < BODY_BOTTOM - 1.5:
        x = 2.0
        while x < W - 2.0:
            ok = all(not (r[0] - reach < x < r[2] + reach and r[1] - reach < y < r[3] + reach) for r in rects)
            ok = ok and all((x - cx) ** 2 + (y - cy) ** 2 >= (reach + cr) ** 2 for cx, cy, cr in discs)
            if ok:
                for a, z, hw in segs:
                    if min(a[0], z[0]) - 2 > x or max(a[0], z[0]) + 2 < x or min(a[1], z[1]) - 2 > y or max(a[1], z[1]) + 2 < y:
                        continue
                    if seg_dist((x, y), (x, y), a, z) < reach + hw:
                        ok = False
                        break
            if ok:
                v = p.PCB_VIA(b)
                v.SetPosition(V(x, y))
                v.SetWidth(p.FromMM(via_d))
                v.SetDrill(p.FromMM(via_drill))
                v.SetNet(gnd)
                b.Add(v)
                added.append(v)
                discs.append((x, y, via_d / 2))
            x += pitch
        y += pitch
    p.ZONE_FILLER(b).Fill(b.Zones())
    zones = {z.GetLayer(): z for z in b.Zones() if not z.GetIsRuleArea()}
    kept = 0
    for v in added:
        pos = v.GetPosition()
        if all(zones[layer].HitTestFilledArea(layer, pos) for layer in (p.F_Cu, p.B_Cu)):
            kept += 1
        else:
            b.Remove(v)
    p.ZONE_FILLER(b).Fill(b.Zones())
    print("GND stitching: %d candidate vias, %d kept" % (len(added), kept))


KICAD_3D = pathlib.Path(r"C:/Program Files/KiCad/9.0/share/kicad/3dmodels")
# PSOP-44: KiCad has no model of the Intel 13.3 mm body; its PSOP-44 model is used as an illustration only
# (docs/models.md lists the differences). Test pads, mounting holes and the edge contacts need no model.
ILLUSTRATIVE = {"Intel_PSOP-44_P1.27mm": "Package_SO.3dshapes/PSOP-44_16.9x27.17mm_P1.27mm.step"}


def set_models(fps):
    """Copy every 3D model into hardware/kicad/3d and point footprints at ${KIPRJMOD}/3d."""
    out = HW / "3d"
    out.mkdir(exist_ok=True)
    for ref, f in fps.items():
        name = f.GetFPID().GetLibItemName().wx_str()
        models = list(f.Models())
        if not models and name in ILLUSTRATIVE:
            m = p.FP_3DMODEL()
            m.m_Filename = "${KICAD9_3DMODEL_DIR}/" + ILLUSTRATIVE[name]
            models = [m]
        f.Models().clear()
        for m in models:
            rel = m.m_Filename.replace("${KICAD9_3DMODEL_DIR}/", "")
            src = KICAD_3D / rel
            if not src.exists():
                raise RuntimeError("%s: 3D model %s not found" % (ref, src))
            dst = out / src.name
            if not dst.exists():
                dst.write_bytes(src.read_bytes())
            m.m_Filename = "${KIPRJMOD}/3d/" + src.name
            f.Add3DModel(m)
    sums = ["%s  %s" % (hashlib.sha256(f.read_bytes()).hexdigest(), f.name) for f in sorted(out.glob("*.step"))]
    (out / "SHA256SUMS").write_text("\n".join(sums) + "\n", encoding="utf-8", newline="\n")


def rename_nets(b):
    """Use the exact netlist names: local labels are "/NAME" in KiCad (older placed boards had them stripped)."""
    text = (BUILD / "netlist.net").read_text(encoding="utf-8")
    names = set(re.findall(r'\(net \(code "\d+"\) \(name "([^"]*)"\)', text))
    renamed = 0
    for net in list(b.GetNetsByName().values()):
        name = net.GetNetname()
        if name and name not in names and "/" + name in names:
            net.SetNetname("/" + name)
            renamed += 1
    b.BuildConnectivity()
    print("renamed %d nets" % renamed)


def widen_neckdowns(b):
    """FreeRouting necks tracks down to 0.15 mm at some pins; JLCPCB/our rule minimum is 0.2 mm."""
    n = 0
    for t in b.GetTracks():
        if t.GetClass() == "PCB_TRACK" and t.GetWidth() < p.FromMM(0.2):
            t.SetWidth(p.FromMM(0.2))
            n += 1
    print("widened %d neck-down segments to 0.2 mm" % n)


def assign_unconnected_nets(b):
    """Give every no-connect pad the 'unconnected-(...)' net KiCad expects from the schematic."""
    text = (BUILD / "netlist.net").read_text(encoding="utf-8")
    fps = {f.GetReference(): f for f in b.GetFootprints()}
    n = 0
    for chunk in text.split("(net (code ")[1:]:
        name = re.search(r'\(name "([^"]*)"\)', chunk).group(1)
        if not name.startswith("unconnected-"):
            continue
        net = b.FindNet(name)
        if net is None:
            net = p.NETINFO_ITEM(b, name)
            b.Add(net)
        for ref, pin in re.findall(r'\(node \(ref "([^"]+)"\) \(pin "([^"]+)"\)', chunk):
            for pad in fps[ref].Pads():
                if pad.GetNumber() == pin and pad.GetNetCode() <= 0:
                    pad.SetNet(net)
                    n += 1
    print("assigned %d no-connect pads" % n)


def seg_dist(a0, a1, b0, b1):
    """Shortest distance between segments a0-a1 and b0-b1 (tuples in mm)."""
    def pt_seg(pt, s0, s1):
        dx, dy = s1[0] - s0[0], s1[1] - s0[1]
        L = dx * dx + dy * dy
        t = 0.0 if L == 0 else max(0.0, min(1.0, ((pt[0] - s0[0]) * dx + (pt[1] - s0[1]) * dy) / L))
        return ((pt[0] - s0[0] - t * dx) ** 2 + (pt[1] - s0[1] - t * dy) ** 2) ** 0.5

    def cross(o, a, c):
        return (a[0] - o[0]) * (c[1] - o[1]) - (a[1] - o[1]) * (c[0] - o[0])

    if (cross(a0, a1, b0) * cross(a0, a1, b1) < 0) and (cross(b0, b1, a0) * cross(b0, b1, a1) < 0):
        return 0.0
    return min(pt_seg(a0, b0, b1), pt_seg(a1, b0, b1), pt_seg(b0, a0, a1), pt_seg(b1, a0, a1))


def fix_clearance(b, clearance=0.2, margin=0.002):
    """Router rounding leaves a few track pairs microns short of 0.2 mm: narrow the signal track of such a pair
    (never below 0.2 mm, never a power track)."""
    power = {"GND", "+5V", "+12V", "VPP", "/12V_SW"}
    segs = []
    for t in b.GetTracks():
        if t.GetClass() != "PCB_TRACK":
            continue
        s, e = t.GetStart(), t.GetEnd()
        segs.append((t, t.GetLayer(), t.GetNetCode(), (p.ToMM(s.x), p.ToMM(s.y)), (p.ToMM(e.x), p.ToMM(e.y))))
    fixed = 0
    for i, (t1, l1, n1, a0, a1) in enumerate(segs):
        for t2, l2, n2, b0, b1 in segs[i + 1:]:
            if l1 != l2 or n1 == n2:
                continue
            w1, w2 = p.ToMM(t1.GetWidth()), p.ToMM(t2.GetWidth())
            reach = (w1 + w2) / 2 + clearance
            if min(b0[0], b1[0]) - reach > max(a0[0], a1[0]) or min(a0[0], a1[0]) - reach > max(b0[0], b1[0]):
                continue
            if min(b0[1], b1[1]) - reach > max(a0[1], a1[1]) or min(a0[1], a1[1]) - reach > max(b0[1], b1[1]):
                continue
            gap = seg_dist(a0, a1, b0, b1) - (w1 + w2) / 2
            if gap >= clearance:
                continue
            short = clearance - gap + margin
            for t, w in sorted(((t1, w1), (t2, w2)), key=lambda x: -x[1]):
                if t.GetNetname() in power or w - 2 * short < 0.2:
                    continue
                t.SetWidth(p.FromMM(w - 2 * short))
                fixed += 1
                break
            else:
                print("cannot fix clearance between %s and %s (gap %.4f mm)" % (t1.GetNetname(), t2.GetNetname(), gap))
    print("narrowed %d tracks to restore 0.2 mm clearance" % fixed)


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
        for v in vias:
            self.obst.append(self.rect(v.GetBoundingBox(), 0.2))

    def block(self, lines, anchors, h=TEXT_SIZE, step=1.65):
        """Place several lines as one left-aligned block at the first anchor where every line fits."""
        for ax, ay in anchors:
            rects = []
            wmax = max(self.size(s, h)[0] for s in lines)
            for i, s in enumerate(lines):
                if s:
                    hh = self.size(s, h)[1]
                    rects.append((ax, ay + i * step - hh / 2, ax + wmax, ay + i * step + hh / 2))
            if all(self.free(r) for r in rects):
                self.texts.extend(rects)
                return ax, ay
        raise RuntimeError("no room for block %r" % lines[0])

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


def place_silkscreen(b, fps):
    vias = []  # vias are tented; silkscreen may cross them
    sp = SilkPlacer(fps, vias)
    order = sorted(fps, key=lambda r: (not r.startswith("U"), not r.startswith("SW"), r))
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
    # Function labels.
    for ref, label in TP_LABEL.items():
        x, y = sp.around(sp.box(fps[ref]), label, prefer=("below", "above", "right", "left"))
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
    lines = [("ISA FLASH DISK  rev A", 1.5), ("2x 28F008SA  1-2 MB", TEXT_SIZE),
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
    # Bottom side: title and the full switch tables (text mirrored, reads from the bottom).
    spb = SilkPlacer(fps, vias, bottom=True)
    for s_, h_, cy in (("ISA FLASH DISK rev A", 1.5, 70.0), ("github.com/adsdevdoo/isa-flash-disk", TEXT_SIZE, 72.6)):
        x_, y_ = spb.place(s_, [(cx, cy + d) for d in (0, 2, 4, -2, -4) for cx in (W / 2, W / 2 - 10, W / 2 + 10)], s_ and h_)
        text(b, s_, x_, y_, h_, layer=p.B_SilkS, bold=(h_ > TEXT_SIZE))
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
    for s in ("* default", "JP1 WRITE open = write protected"):
        text(b, s, 44.0, y, TEXT_SIZE, layer=p.B_SilkS, justify="left")
        rects.append((44.0 - spb.size(s, TEXT_SIZE)[0], y - 0.8, 44.0, y + 0.8))
        y += 1.8
    for r in rects:
        if not spb.free(r):
            raise RuntimeError("switch table overlaps bottom-side copper at %s" % (r,))
    spb.texts.extend(rects)
    return sp.texts + spb.texts


def silk_table(b, x_left_seen_from_bottom, y_top, title, rows, cw0=10.0, cw=5.0, rh=2.3):
    """A ruled table on the bottom silkscreen. It is mirrored on the drawing: seen from the bottom its left
    edge is at x_left_seen_from_bottom and its columns run towards smaller x on the top-view drawing."""
    ncol = len(rows[0])
    widths = [cw0] + [cw] * (ncol - 1)
    total = sum(widths)
    x0 = x_left_seen_from_bottom          # drawing x of the visible left edge
    nrows = len(rows) + 1
    bottom = y_top + nrows * rh

    def line(a, z):
        s = p.PCB_SHAPE(b)
        s.SetShape(p.SHAPE_T_SEGMENT)
        s.SetStart(V(*a))
        s.SetEnd(V(*z))
        s.SetLayer(p.B_SilkS)
        s.SetWidth(p.FromMM(TEXT_THICK))
        b.Add(s)

    for k in range(nrows + 1):
        yy = y_top + k * rh
        line((x0, yy), (x0 - total, yy))
    acc = 0.0
    for i in range(ncol + 1):
        line((x0 - acc, y_top + (0 if i in (0, ncol) else rh)), (x0 - acc, bottom))
        if i < ncol:
            acc += widths[i]
    text(b, title, x0 - total / 2, y_top + rh / 2, TEXT_SIZE, layer=p.B_SilkS, bold=True)
    for r, cells in enumerate(rows, 1):
        acc = 0.0
        for i, cell in enumerate(cells):
            text(b, cell, x0 - acc - widths[i] / 2, y_top + r * rh + rh / 2, TEXT_SIZE, layer=p.B_SilkS,
                 bold=(r <= 2 or i == 0))
            acc += widths[i]
    return (x0 - total, y_top, x0, bottom)


def merge_project_rules():
    """Copy board rules and net classes that pcbnew stored next to the placed board into the project file."""
    src = json.loads((BUILD / "placed.kicad_pro").read_text(encoding="utf-8"))
    dst = json.loads(PRO.read_text(encoding="utf-8")) if PRO.exists() else {}
    dst["board"] = src["board"]
    dst["net_settings"] = src["net_settings"]
    for pat in dst["net_settings"].get("netclass_patterns", []):
        if pat["pattern"] == "12V_SW":
            pat["pattern"] = "/12V_SW"
    rules = dst["board"]["design_settings"]["rules"]
    rules["min_text_height"] = TEXT_SIZE
    rules["min_text_thickness"] = TEXT_THICK
    rules["min_silk_clearance"] = 0.15
    dst.setdefault("meta", {"filename": PRO.name, "version": 3})
    dst["meta"]["filename"] = PRO.name
    PRO.write_text(json.dumps(dst, indent=2) + "\n", encoding="utf-8", newline="\n")


def main():
    if BOARD.exists() and "--force" not in sys.argv:
        recorded = STAMP.read_text(encoding="utf-8").strip() if STAMP.exists() else ""
        if recorded != sha(BOARD):
            sys.exit("%s was changed after generation (edited in KiCad?). Refusing to overwrite it; "
                     "rerun with --force only if those edits may be discarded." % BOARD)

    b = p.LoadBoard(str(BUILD / "placed.kicad_pcb"))
    if not p.ImportSpecctraSES(b, str(BUILD / "placed.ses")):
        sys.exit("SES import failed")

    rename_nets(b)
    widen_neckdowns(b)
    assign_unconnected_nets(b)
    fix_clearance(b)
    fps = {f.GetReference(): f for f in b.GetFootprints()}
    set_models(fps)
    # Contact-end marks of the edge footprint sit on the card edge: drop them.
    for item in list(fps["J1"].GraphicalItems()):
        if item.GetLayer() in (p.F_SilkS, p.B_SilkS):
            fps["J1"].Remove(item)
    for layer in (p.F_Cu, p.B_Cu):
        gnd_zone(b, layer)
    p.ZONE_FILLER(b).Fill(b.Zones())
    silk_rects = place_silkscreen(b, fps)
    stitch_gnd(b, avoid=silk_rects)

    b.SetFileName(str(BOARD))
    p.SaveBoard(str(BOARD), b, True)
    merge_project_rules()
    STAMP.write_text(sha(BOARD) + "\n", encoding="utf-8", newline="\n")
    tracks = [t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK"]
    vias = [t for t in b.GetTracks() if t.GetClass() == "PCB_VIA"]
    print("saved %s: %d tracks, %d vias" % (BOARD, len(tracks), len(vias)))


if __name__ == "__main__":
    main()
