"""Import the FreeRouting session, pour GND on both layers, add the silkscreen (silk_board.py), save the board.

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

# The silkscreen (designators, values, labels, bottom block) is defined only in silk_board.py; it also runs
# standalone on the routed board without touching copper.
from silk_board import TEXT_SIZE, TEXT_THICK, place_silkscreen, set_title_block, stable_uuids  # noqa: E402


def sha(path):
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


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
    set_title_block(b)

    b.SetFileName(str(BOARD))
    p.SaveBoard(str(BOARD), b, True)
    stable_uuids(BOARD)
    merge_project_rules()
    STAMP.write_text(sha(BOARD) + "\n", encoding="utf-8", newline="\n")
    tracks = [t for t in b.GetTracks() if t.GetClass() == "PCB_TRACK"]
    vias = [t for t in b.GetTracks() if t.GetClass() == "PCB_VIA"]
    print("saved %s: %d tracks, %d vias" % (BOARD, len(tracks), len(vias)))


if __name__ == "__main__":
    main()
