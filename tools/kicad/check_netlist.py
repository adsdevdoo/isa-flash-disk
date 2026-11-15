#!/usr/bin/env python3
"""Compare a KiCad netlist with hardware/kicad/expected-nets.json.

Usage:
    kicad-cli sch export netlist --format kicadsexpr -o out.net hardware/kicad/isa-flash-disk.kicad_sch
    python tools/kicad/check_netlist.py out.net

Exit code 0 when every expected net has exactly the expected pins and no other
multi-pin net exists.
"""

import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def read_netlist(path):
    text = open(path, encoding="utf-8").read()
    nets = {}
    for chunk in text.split("(net (code ")[1:]:
        name = re.search(r'\(name "([^"]*)"\)', chunk).group(1).lstrip("/")
        nodes = re.findall(r'\(node \(ref "([^"]+)"\) \(pin "([^"]+)"\)', chunk)
        pins = {"%s.%s" % n for n in nodes if not n[0].startswith("#")}
        if pins:
            nets[name] = pins
    return nets


def main():
    got = read_netlist(sys.argv[1])
    expected_path = os.path.join(REPO, "hardware", "kicad", "expected-nets.json")
    expected = {k: set(v) for k, v in json.load(open(expected_path, encoding="utf-8")).items()}
    problems = 0
    for name, pins in sorted(expected.items()):
        have = got.get(name, set())
        if have != pins:
            problems += 1
            print("MISMATCH %s: missing %s, extra %s" % (name, sorted(pins - have), sorted(have - pins)))
    for name, pins in sorted(got.items()):
        if name not in expected and not name.startswith("unconnected-"):
            problems += 1
            print("UNEXPECTED %s: %s" % (name, sorted(pins)))
    singles = sorted(k for k, v in expected.items() if len(v) < 2)
    print("expected nets: %d, netlist nets: %d, problems: %d, single-pin nets: %s"
          % (len(expected), len(got), problems, singles or "none"))
    return 1 if problems or singles else 0


if __name__ == "__main__":
    sys.exit(main())
