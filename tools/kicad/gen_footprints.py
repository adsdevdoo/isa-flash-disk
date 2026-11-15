#!/usr/bin/env python3
"""Generate project footprints for the ISA Flash Disk card (KiCad 9 format).

Outputs into hardware/kicad/isa_flash_disk.pretty/:

* Intel_PSOP-44_P1.27mm   - land pattern from Intel "44 Lead PSOP Specifications" v1.0
                             (docs/datasheets/intel-psop-44-package-2232-1.pdf, page 2).
* ISA_8bit_Edge           - pads 1..62 of the stock KiCad BUS_AT footprint
                             (1..31 = B1..B31 on B.Cu, 32..62 = A1..A31 on F.Cu),
                             matching the pin numbers of the Connector:Bus_ISA_8bit symbol.

Usage: python tools/kicad/gen_footprints.py
Environment: KICAD9_FOOTPRINT_DIR overrides the KiCad footprint library location.
"""

import os
import re
import uuid

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(REPO, "hardware", "kicad", "isa_flash_disk.pretty")
KICAD_FP = os.environ.get("KICAD9_FOOTPRINT_DIR", r"C:/Program Files/KiCad/9.0/share/kicad/footprints")
NS = uuid.UUID("6f1c2a3e-9b7d-4e21-8a55-3c0d7e9f1a42")


def uid(key):
    return str(uuid.uuid5(NS, key))


def text_prop(name, value, x, y, layer, key, hide=False):
    hide_s = "\n\t\t(hide yes)" if hide else ""
    return (
        '\t(property "%s" "%s"\n\t\t(at %s %s 0)\n\t\t(layer "%s")%s\n\t\t(uuid "%s")\n'
        "\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1 1)\n\t\t\t\t(thickness 0.15)\n\t\t\t)\n\t\t)\n\t)\n"
        % (name, value, fmt(x), fmt(y), layer, hide_s, uid(key + name))
    )


def fmt(v):
    s = ("%.4f" % v).rstrip("0").rstrip(".")
    if s == "-0":
        s = "0"
    return s


def line(x1, y1, x2, y2, layer, width, key):
    return (
        "\t(fp_line\n\t\t(start %s %s)\n\t\t(end %s %s)\n\t\t(stroke\n\t\t\t(width %s)\n\t\t\t(type solid)\n\t\t)\n"
        '\t\t(layer "%s")\n\t\t(uuid "%s")\n\t)\n'
        % (fmt(x1), fmt(y1), fmt(x2), fmt(y2), fmt(width), layer, uid(key))
    )


def rect(x1, y1, x2, y2, layer, width, key):
    return (
        "\t(fp_rect\n\t\t(start %s %s)\n\t\t(end %s %s)\n\t\t(stroke\n\t\t\t(width %s)\n\t\t\t(type solid)\n\t\t)\n"
        '\t\t(fill no)\n\t\t(layer "%s")\n\t\t(uuid "%s")\n\t)\n'
        % (fmt(x1), fmt(y1), fmt(x2), fmt(y2), fmt(width), layer, uid(key))
    )


def psop44():
    name = "Intel_PSOP-44_P1.27mm"
    # Intel land pattern: outer span 16.9 mm, pad 1.90 x 0.50 mm, pitch 1.27 mm.
    pad_len, pad_w, pitch, outer = 1.90, 0.50, 1.27, 16.9
    pad_x = outer / 2 - pad_len / 2  # 7.50 mm
    first_y = -10.5 * pitch  # 22 pads per side
    # Package (Intel 2232_1, nominal): body E = 13.30, D1 = 28.20, tip-to-tip D = 16.00.
    body_x, body_y = 13.30 / 2, 28.20 / 2
    out = []
    out.append('(footprint "%s"\n\t(version 20241229)\n\t(generator "isa-flash-disk")\n\t(generator_version "1.0")\n'
               '\t(layer "F.Cu")\n' % name)
    out.append('\t(descr "Intel 44-lead PSOP (PA28F008SA). Land pattern from Intel 44 Lead PSOP Specifications v1.0: '
               'pads 1.90x0.50 mm, outer span 16.9 mm, pitch 1.27 mm. Body 13.3x28.2 mm, tip-to-tip 16.0 mm.")\n')
    out.append('\t(tags "PSOP 44 Intel 28F008SA FlashFile")\n')
    out.append(text_prop("Reference", "REF**", 0, -body_y - 1.5, "F.SilkS", name))
    out.append(text_prop("Value", name, 0, body_y + 1.5, "F.Fab", name))
    out.append(text_prop("Datasheet", "", 0, 0, "F.Fab", name, hide=True))
    out.append(text_prop("Description", "", 0, 0, "F.Fab", name, hide=True))
    out.append("\t(attr smd)\n")
    # Fabrication outline with pin-1 chamfer.
    ch = 1.0
    out.append(line(-body_x + ch, -body_y, body_x, -body_y, "F.Fab", 0.1, name + "fab1"))
    out.append(line(body_x, -body_y, body_x, body_y, "F.Fab", 0.1, name + "fab2"))
    out.append(line(body_x, body_y, -body_x, body_y, "F.Fab", 0.1, name + "fab3"))
    out.append(line(-body_x, body_y, -body_x, -body_y + ch, "F.Fab", 0.1, name + "fab4"))
    out.append(line(-body_x, -body_y + ch, -body_x + ch, -body_y, "F.Fab", 0.1, name + "fab5"))
    # Silkscreen: top and bottom body edges, pin-1 tick on the top edge.
    sy = body_y + 0.11
    out.append(line(-body_x, -sy, body_x, -sy, "F.SilkS", 0.12, name + "silk1"))
    out.append(line(-body_x, sy, body_x, sy, "F.SilkS", 0.12, name + "silk2"))
    out.append(line(-body_x, -sy, -(pad_x + pad_len / 2), -sy, "F.SilkS", 0.12, name + "silk3"))
    # Courtyard: pads and body plus 0.25 mm.
    cx = pad_x + pad_len / 2 + 0.25
    cy = body_y + 0.25
    out.append(rect(-cx, -cy, cx, cy, "F.CrtYd", 0.05, name + "crt"))
    for i in range(44):
        n = i + 1
        if n <= 22:
            x, y = -pad_x, first_y + i * pitch
        else:
            x, y = pad_x, -first_y - (n - 23) * pitch
        out.append('\t(pad "%d" smd roundrect\n\t\t(at %s %s)\n\t\t(size %s %s)\n'
                   '\t\t(layers "F.Cu" "F.Mask" "F.Paste")\n\t\t(roundrect_rratio 0.25)\n\t\t(uuid "%s")\n\t)\n'
                   % (n, fmt(x), fmt(y), fmt(pad_len), fmt(pad_w), uid(name + "pad%d" % n)))
    out.append("\t(embedded_fonts no)\n)\n")
    return name, "".join(out)


def pad_blocks(text):
    blocks = {}
    for m in re.finditer(r'\n\t\(pad "(\d+)"', text):
        depth = 0
        start = m.start() + 1
        for j in range(start, len(text)):
            if text[j] == "(":
                depth += 1
            elif text[j] == ")":
                depth -= 1
                if depth == 0:
                    blocks[int(m.group(1))] = text[start:j + 1]
                    break
    return blocks


def isa_edge():
    name = "ISA_8bit_Edge"
    src = open(os.path.join(KICAD_FP, "Connector_PCBEdge.pretty", "BUS_AT.kicad_mod"), encoding="utf-8").read()
    pads = pad_blocks(src)
    out = []
    out.append('(footprint "%s"\n\t(version 20241229)\n\t(generator "isa-flash-disk")\n\t(generator_version "1.0")\n'
               '\t(layer "F.Cu")\n' % name)
    out.append('\t(descr "8-bit ISA (PC/XT) edge connector, 62 contacts, 2.54 mm pitch. Pads 1..62 of KiCad BUS_AT: '
               '1..31 = B1..B31 (B.Cu, solder side), 32..62 = A1..A31 (F.Cu, component side). '
               'Card edge, bevel and bracket position are defined on the PCB, not here.")\n')
    out.append('\t(tags "ISA XT edge connector")\n')
    out.append(text_prop("Reference", "REF**", -38.1, -6.5, "F.SilkS", name))
    out.append(text_prop("Value", name, -38.1, 6.0, "F.Fab", name))
    out.append(text_prop("Datasheet", "", 0, 0, "F.Fab", name, hide=True))
    out.append(text_prop("Description", "", 0, 0, "F.Fab", name, hide=True))
    out.append("\t(attr exclude_from_pos_files exclude_from_bom)\n")
    out.append(line(2.6, 3.85, 2.6, -5.1, "F.SilkS", 0.12, name + "s1"))
    out.append(line(2.6, -5.1, 3.0, -5.1, "F.SilkS", 0.12, name + "s2"))
    out.append(line(-78.8, 3.85, -78.8, -5.1, "F.SilkS", 0.12, name + "s3"))
    out.append(line(-78.8, -5.1, -79.2, -5.1, "F.SilkS", 0.12, name + "s4"))
    out.append(rect(-79.45, -5.33, 3.25, 4.06, "F.CrtYd", 0.05, name + "crt"))
    for n in range(1, 63):
        out.append("\t" + pads[n].lstrip("\t") + "\n")
    out.append("\t(embedded_fonts no)\n)\n")
    return name, "".join(out)


# Stock KiCad 9 footprints copied verbatim, so the project does not depend on the installed library version.
STOCK = [
    "Package_SO:SOIC-20W_7.5x12.8mm_P1.27mm",
    "Package_SO:SOIC-16_3.9x9.9mm_P1.27mm",
    "Package_SO:SOIC-14_3.9x8.7mm_P1.27mm",
    "Package_TO_SOT_SMD:SOT-23",
    "Resistor_SMD:R_0805_2012Metric_Pad1.20x1.40mm_HandSolder",
    "Capacitor_SMD:C_0805_2012Metric_Pad1.18x1.45mm_HandSolder",
    "LED_SMD:LED_0805_2012Metric_Pad1.15x1.40mm_HandSolder",
    "TestPoint:TestPoint_THTPad_D2.0mm_Drill1.0mm",
    "Resistor_THT:R_Array_SIP7",
    "Button_Switch_THT:SW_DIP_SPSTx05_Slide_9.78x14.88mm_W7.62mm_P2.54mm",
    "Button_Switch_THT:SW_DIP_SPSTx06_Slide_9.78x17.42mm_W7.62mm_P2.54mm",
    "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
]


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for item in STOCK:
        lib, name = item.split(":", 1)
        with open(os.path.join(KICAD_FP, lib + ".pretty", name + ".kicad_mod"), encoding="utf-8") as f:
            text = f.read()
        path = os.path.join(OUT_DIR, name + ".kicad_mod")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print("copied", item)
    for name, text in (psop44(), isa_edge()):
        path = os.path.join(OUT_DIR, name + ".kicad_mod")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print("wrote", path)


if __name__ == "__main__":
    main()
