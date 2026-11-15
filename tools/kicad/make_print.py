"""Printable 1:1 assembly sheet of the board (A4 landscape, the page size of the board file): pad outlines with pin numbers, component outlines,
silkscreen, board outline and a 100 mm scale bar. Used to check salvaged PSOP-44 chips against the land pattern
and as a placement map while soldering.

Run with KiCad's Python:
  "C:/Program Files/KiCad/9.0/bin/python.exe" tools/kicad/make_print.py <tmp dir>
then the script calls kicad-cli and writes hardware/print/isa-flash-disk-revA-top-1to1.pdf.
"""

import os
import subprocess
import sys

import pcbnew

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "hardware", "kicad", "isa-flash-disk.kicad_pcb")
OUT = os.path.join(ROOT, "hardware", "print", "isa-flash-disk-revA-top-1to1.pdf")
CLI = os.path.join(os.path.dirname(sys.executable), "kicad-cli.exe")
MM = pcbnew.FromMM


def text(board, s, x, y, size=2.5, bold=False):
    t = pcbnew.PCB_TEXT(board)
    t.SetText(s)
    t.SetLayer(pcbnew.F_Fab)
    t.SetTextSize(pcbnew.VECTOR2I(MM(size), MM(size)))
    t.SetTextThickness(MM(size * (0.2 if bold else 0.12)))
    t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_LEFT)
    t.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y)))
    board.Add(t)


def line(board, x1, y1, x2, y2, w=0.25):
    s = pcbnew.PCB_SHAPE(board)
    s.SetShape(pcbnew.SHAPE_T_SEGMENT)
    s.SetStart(pcbnew.VECTOR2I(MM(x1), MM(y1)))
    s.SetEnd(pcbnew.VECTOR2I(MM(x2), MM(y2)))
    s.SetLayer(pcbnew.F_Fab)
    s.SetWidth(MM(w))
    board.Add(s)


def main():
    tmp = sys.argv[1]
    board = pcbnew.LoadBoard(SRC)
    bbox = board.GetBoardEdgesBoundingBox()
    w, h = pcbnew.ToMM(bbox.GetWidth()), pcbnew.ToMM(bbox.GetHeight())
    x0, y0 = (297 - w) / 2, 62.0                # A4 landscape, board in the middle
    off = pcbnew.VECTOR2I(MM(x0) - bbox.GetX(), MM(y0) - bbox.GetY())
    for item in list(board.GetFootprints()) + list(board.GetTracks()) + list(board.GetDrawings()) + list(board.Zones()):
        item.Move(off)

    text(board, "ISA Flash Disk rev A - top side, scale 1:1", 20, 16, 4.0, True)
    text(board, "Print at 100 % (no 'fit to page'). Check: the board outline is 104.14 x 100.00 mm,", 20, 26)
    text(board, "the scale bar below is 100.0 mm. Pads are drawn as outlines with pin numbers.", 20, 32)
    text(board, "PSOP-44 check: lay a salvaged chip on U1 - every lead must sit on its pad.", 20, 38)
    text(board, "Pin 1 of U1/U2: the marked corner. Pitch 1.27 mm, pad centres 7.5 mm either side of the chip centre.", 20, 44)
    yb = y0 + h + 20
    line(board, x0, yb, x0 + 100, yb)
    for i in range(11):
        tick = 3 if i % 5 == 0 else 1.5
        line(board, x0 + 10 * i, yb, x0 + 10 * i, yb - tick)
    text(board, "0", x0 - 1, yb + 5, 2.5)
    text(board, "50 mm", x0 + 46, yb + 5, 2.5)
    text(board, "100 mm", x0 + 95, yb + 5, 2.5)

    tmp_pcb = os.path.join(tmp, "print.kicad_pcb")
    board.Save(tmp_pcb)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    subprocess.run([CLI, "pcb", "export", "pdf", "--layers", "F.Fab,F.Silkscreen,Edge.Cuts", "--mode-single",
                    "--sketch-pads-on-fab-layers", "--black-and-white", "-o", OUT, tmp_pcb], check=True)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
