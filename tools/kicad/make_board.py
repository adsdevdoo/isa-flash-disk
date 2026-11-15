"""Build the placed, unrouted ISA Flash Disk board and export it for FreeRouting.

Run with KiCad 9 Python:
    "C:/Program Files/KiCad/9.0/bin/python.exe" tools/kicad/make_board.py

Inputs:  hardware/kicad/isa-flash-disk.kicad_sch (netlist is exported with kicad-cli).
Outputs: hardware/kicad/build/placed.kicad_pcb and build/placed.dsn (build/ is not committed).
route_board.py turns them into the routed hardware/kicad/isa-flash-disk.kicad_pcb.

Mechanics follow the XT-CF-Lite V4 outline for a Keystone 9202 bracket (docs/isa-interface.md):
length 4.10" (104.14 mm), A1..A31 contact centres 3.10"..0.10" from the far edge, bracket holes
0.15" from the bracket edge at 0.425" and 2.65" above the contact bottom.
"""

import math
import os
import pathlib
import re
import subprocess
import sys

import pcbnew as p
import wx

wx.DisableAsserts()

ROOT = pathlib.Path(__file__).resolve().parents[2]
HW = ROOT / "hardware" / "kicad"
BUILD = HW / "build"
LIB = "isa_flash_disk"
KICAD_CLI = os.environ.get("KICAD_CLI", r"C:/Program Files/KiCad/9.0/bin/kicad-cli.exe")

# Board geometry, mm. Origin of the drawing = top-left corner of the card.
OX, OY = 100.0, 100.0
W = 104.14          # 4.10"
H = 100.0           # card height incl. contacts (user limit: 100 mm)
TAB_L, TAB_R = 0.635, 80.645   # contact tab, 0.025" .. 3.175"
STEP_X = 81.28                 # 3.20"
BODY_BOTTOM = H - 7.62         # card body edge above the contact tab (0.3")
CONTACT_A1_X = 78.74           # 3.10"
CONTACT_Y = H - 1.0 - 3.09     # footprint origin: contacts end 1.0 mm above the tab edge (bevel)
HOLE_X = W - 3.81              # 0.15" from the bracket edge
HOLE_Y = (H - 10.795, H - 67.31)  # 0.425" and 2.65" above the contact bottom
BRACKET_KEEPOUT_X = 94.0       # components stay left of this line

POWER_NETS = ("GND", "+5V", "+12V", "VPP", "/12V_SW")  # names exactly as in the netlist


def V(x, y):
    return p.VECTOR2I(p.FromMM(OX + x), p.FromMM(OY + y))


# ---------------------------------------------------------------------------------------------
# Netlist
# ---------------------------------------------------------------------------------------------

def export_netlist():
    BUILD.mkdir(exist_ok=True)
    out = BUILD / "netlist.net"
    subprocess.run([KICAD_CLI, "sch", "export", "netlist", "--format", "kicadsexpr", "-o", str(out),
                    str(HW / "isa-flash-disk.kicad_sch")], check=True, capture_output=True)
    return out.read_text(encoding="utf-8")


def parse_netlist(text):
    comps = {}
    for chunk in text.split("(comp (ref ")[1:]:
        ref = re.match(r'"([^"]+)"', chunk).group(1)
        fp = re.search(r'\(footprint "([^"]*)"\)', chunk)
        value = re.search(r'\(value "([^"]*)"\)', chunk).group(1)
        tstamps = re.search(r'\(tstamps "([^"]+)"', chunk.split("(sheetpath")[1]).group(1)
        comps[ref] = {"fp": fp.group(1) if fp else "", "value": value, "uuid": tstamps, "pins": {}}
    nets_part = text.split("(nets", 1)[1]
    for chunk in nets_part.split("(net (code ")[1:]:
        name = re.search(r'\(name "([^"]*)"\)', chunk).group(1)
        for ref, pin in re.findall(r'\(node \(ref "([^"]+)"\) \(pin "([^"]+)"\)', chunk):
            if ref in comps:
                comps[ref]["pins"][pin] = name
    return comps


# ---------------------------------------------------------------------------------------------
# Placement (x, y, rotation in degrees), board coordinates in mm
# ---------------------------------------------------------------------------------------------

PLACE = {
    # Flash, long axis vertical, address side towards the contacts on the left.
    "U1": (14.0, 28.0, 0), "U2": (37.0, 28.0, 0),
    # Row next to the contacts.
    "U5": (9.0, 74.0, 90), "U4": (26.5, 74.0, 90), "U3": (44.0, 74.0, 90), "U8": (70.0, 74.0, 90),
    # Middle row.
    "U9": (53.0, 56.0, 90), "U10": (65.0, 56.0, 90), "U6": (80.0, 56.0, 90), "U7": (88.0, 74.0, 90),
    # Address switches and pull-ups.
    "SW1": (51.5, 7.0, 0), "SW2": (65.5, 7.0, 0),
    "RN1": (50.5, 31.0, 0), "RN2": (50.5, 36.0, 0),
    # VPP switch and write jumper.
    "JP1": (80.0, 7.0, 0), "R1": (86.5, 8.0, 90), "Q1": (90.5, 12.5, 0), "Q2": (85.5, 15.5, 0),
    "R3": (85.5, 20.0, 90), "R2": (90.5, 19.0, 90), "R4": (80.0, 19.0, 90), "D2": (80.0, 24.0, 90),
    "C16": (80.0, 14.0, 90),
    # LEDs, test points.
    "R5": (87.0, 30.0, 0), "D1": (91.0, 30.0, 0),
    "TP1": (76.0, 4.0, 0), "TP2": (90.0, 4.0, 0), "TP3": (82.0, 36.0, 0), "TP4": (86.0, 36.0, 0),
    "TP5": (90.0, 36.0, 0), "TP6": (6.0, 4.0, 0), "TP7": (29.0, 4.0, 0),
    # Bracket screws.
    "H1": (HOLE_X, HOLE_Y[0], 0), "H2": (HOLE_X, HOLE_Y[1], 0),
    # Bulk capacitors.
    "C15": (58.0, 66.0, 0),
    "C13": (6.5, 9.5, 0), "C14": (29.5, 9.5, 0),
}

# Decoupling capacitor -> (IC, power pad): placed just outside the IC next to that pad.
DECOUPLING = {
    "C1": ("U3", "20"), "C2": ("U4", "20"), "C3": ("U5", "16"), "C4": ("U6", "20"), "C5": ("U7", "16"),
    "C6": ("U8", "20"), "C7": ("U9", "14"), "C8": ("U10", "14"),
    "C9": ("U1", "44"), "C10": ("U1", "23"), "C11": ("U2", "44"), "C12": ("U2", "23"),
}


def main():
    comps = parse_netlist(export_netlist())
    b = p.BOARD()
    b.SetCopperLayerCount(2)
    nets = {}
    for c in comps.values():
        for net in c["pins"].values():
            if net not in nets:
                nets[net] = p.NETINFO_ITEM(b, net)
                b.Add(nets[net])

    ds = b.GetDesignSettings()
    ds.m_MinClearance = p.FromMM(0.2)
    ds.m_TrackMinWidth = p.FromMM(0.2)
    ds.m_ViasMinSize = p.FromMM(0.6)
    ds.m_MinThroughDrill = p.FromMM(0.3)
    ds.m_CopperEdgeClearance = p.FromMM(0.3)
    ns = ds.m_NetSettings
    dflt = ns.GetDefaultNetclass()
    dflt.SetTrackWidth(p.FromMM(0.25))
    dflt.SetClearance(p.FromMM(0.2))
    dflt.SetViaDiameter(p.FromMM(0.7))
    dflt.SetViaDrill(p.FromMM(0.3))
    power = p.NETCLASS("Power")
    power.SetClearance(p.FromMM(0.2))
    power.SetTrackWidth(p.FromMM(0.4))
    power.SetViaDiameter(p.FromMM(0.8))
    power.SetViaDrill(p.FromMM(0.4))
    ns.SetNetclass("Power", power)
    for name in POWER_NETS:
        ns.SetNetclassPatternAssignment(name, "Power")
        nets[name].SetNetClass(power)

    fps = {}
    for ref, c in sorted(comps.items()):
        if not c["fp"]:
            continue
        lib, name = c["fp"].split(":", 1)
        if lib != LIB:
            raise RuntimeError("%s uses %s; all footprints must come from %s" % (ref, c["fp"], LIB))
        fp = p.FootprintLoad(str(HW / (LIB + ".pretty")), name)
        if fp is None:
            raise RuntimeError("footprint %s not found" % name)
        fp.SetFPID(p.LIB_ID(LIB, name))
        fp.SetReference(ref)
        fp.SetValue(c["value"])
        path = p.KIID_PATH()
        path.push_back(p.KIID(c["uuid"]))
        fp.SetPath(path)
        b.Add(fp)
        for pad in fp.Pads():
            num = pad.GetNumber()
            if not num:
                continue
            net = c["pins"].get(num)
            if net:
                pad.SetNet(nets[net])
            if ref == "J1":
                pad.SetLocalClearance(p.FromMM(0.3))
        fp.Reference().SetTextSize(p.VECTOR2I(p.FromMM(1.0), p.FromMM(1.0)))
        fp.Reference().SetTextThickness(p.FromMM(0.15))
        fp.Value().SetVisible(False)
        fps[ref] = fp

    # Edge connector: footprint origin = A1 contact centre.
    fps["J1"].SetPosition(V(CONTACT_A1_X, CONTACT_Y))
    for ref, (x, y, rot) in PLACE.items():
        fps[ref].SetPosition(V(x, y))
        fps[ref].SetOrientationDegrees(rot)
    for cap, (ic, padnum) in DECOUPLING.items():
        f = fps[ic]
        pad = [pd for pd in f.Pads() if pd.GetNumber() == padnum][0]
        pc, fc = pad.GetPosition(), f.GetPosition()
        dy = p.ToMM(pc.y - fc.y)
        # Above or below the IC, in line with the power pad (rotated SOICs have VCC in the top row).
        half_h = p.ToMM(f.GetCourtyard(p.F_CrtYd).BBox().GetHeight()) / 2
        cx = p.ToMM(pc.x) - OX
        cy = p.ToMM(fc.y) - OY + math.copysign(half_h + 1.3, dy)
        fps[cap].SetPosition(V(cx, cy))
        fps[cap].SetOrientationDegrees(0)

    missing = [r for r in fps if r not in PLACE and r not in DECOUPLING and r != "J1"]
    if missing:
        raise RuntimeError("no position for %s" % missing)

    add_outline(b)
    add_tab_keepout(b)
    add_contact_stubs(b, fps["J1"])
    BUILD.mkdir(exist_ok=True)
    out = BUILD / "placed.kicad_pcb"
    b.SetFileName(str(out))
    p.SaveBoard(str(out), b)
    p.ExportSpecctraDSN(b, str(BUILD / "placed.dsn"))
    print("placed %d footprints, %d nets -> %s" % (len(fps), len(nets), out))


def seg(b, a, z):
    s = p.PCB_SHAPE(b)
    s.SetShape(p.SHAPE_T_SEGMENT)
    s.SetStart(V(*a))
    s.SetEnd(V(*z))
    s.SetLayer(p.Edge_Cuts)
    s.SetWidth(p.FromMM(0.05))
    b.Add(s)


def arc(b, start, mid, end):
    s = p.PCB_SHAPE(b)
    s.SetShape(p.SHAPE_T_ARC)
    s.SetArcGeometry(V(*start), V(*mid), V(*end))
    s.SetLayer(p.Edge_Cuts)
    s.SetWidth(p.FromMM(0.05))
    b.Add(s)


def corner(b, cx, cy, r, a0, a1):
    """Arc of radius r around (cx, cy) from angle a0 to a1 (degrees, y down)."""
    pt = lambda a: (cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
    arc(b, pt(a0), pt((a0 + a1) / 2), pt(a1))


def add_outline(b):
    r, rt = 2.54, 0.635
    # Top edge and top corners.
    seg(b, (r, 0), (W - r, 0))
    corner(b, W - r, r, r, 270, 360)
    # Bracket edge.
    seg(b, (W, r), (W, BODY_BOTTOM - r))
    corner(b, W - r, BODY_BOTTOM - r, r, 0, 90)
    # Body bottom between the bracket and the contact tab.
    seg(b, (W - r, BODY_BOTTOM), (STEP_X, BODY_BOTTOM))
    # Step down to the tab, tab bottom, far edge.
    seg(b, (STEP_X, BODY_BOTTOM), (STEP_X, H - rt))
    corner(b, STEP_X - rt, H - rt, rt, 0, 90)
    seg(b, (TAB_R, H), (TAB_L, H))
    corner(b, rt, H - rt, rt, 90, 180)
    seg(b, (0, H - rt), (0, r))
    corner(b, r, r, r, 180, 270)


def add_contact_stubs(b, j1):
    """Locked straight stubs from every used contact up into the card body, so the router never has to
    enter the contact tab (which is a keepout for tracks, vias and pours)."""
    for pad in j1.Pads():
        if not pad.GetNetname() or pad.GetNetname().startswith("unconnected-"):
            continue
        pos = pad.GetPosition()
        x = p.ToMM(pos.x) - OX
        top = p.ToMM(pos.y - pad.GetSize().y // 2) - OY
        t = p.PCB_TRACK(b)
        t.SetStart(V(x, top + 0.3))
        t.SetEnd(V(x, BODY_BOTTOM - 1.5))
        t.SetLayer(p.B_Cu if pad.IsOnLayer(p.B_Cu) and not pad.IsOnLayer(p.F_Cu) else p.F_Cu)
        t.SetWidth(p.FromMM(0.4 if pad.GetNetname() in POWER_NETS else 0.25))
        t.SetNet(pad.GetNet())
        t.SetLocked(True)
        b.Add(t)


def rule_area(b, name, pts, tracks):
    z = p.ZONE(b)
    z.SetIsRuleArea(True)
    z.SetDoNotAllowTracks(tracks)
    z.SetDoNotAllowVias(True)
    z.SetDoNotAllowPads(False)
    z.SetDoNotAllowFootprints(False)
    if hasattr(z, "SetDoNotAllowZoneFills"):
        z.SetDoNotAllowZoneFills(True)
    else:
        z.SetDoNotAllowCopperPour(True)
    ls = p.LSET()
    ls.AddLayer(p.F_Cu)
    ls.AddLayer(p.B_Cu)
    z.SetLayerSet(ls)
    z.SetZoneName(name)
    o = z.Outline()
    o.NewOutline()
    for x, y in pts:
        o.Append(V(x, y))
    b.Add(z)


def add_tab_keepout(b):
    """Contact tab: no vias and no pours; the bevel band below the contacts: no copper at all.
    Tracks cannot pass between contacts because the contacts carry a 0.3 mm local clearance."""
    rule_area(b, "CONTACT_TAB", ((-1, BODY_BOTTOM + 0.25), (STEP_X + 1, BODY_BOTTOM + 0.25),
                                 (STEP_X + 1, H + 1), (-1, H + 1)), tracks=False)
    rule_area(b, "BEVEL", ((-1, H - 0.9), (STEP_X + 1, H - 0.9), (STEP_X + 1, H + 1), (-1, H + 1)), tracks=True)


if __name__ == "__main__":
    main()
