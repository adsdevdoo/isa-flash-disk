# Gerber

| Файл | Что это |
|---|---|
| `isa-flash-disk-revA-jlcpcb.zip` | архив для заказа: F/B.Cu, F/B.Mask, F/B.Silkscreen, Edge.Cuts, PTH.drl |
| `rev-A/` | те же файлы по отдельности, карты сверловки PDF и job-файл |

**Rev A — прототип, в железе не проверен.** Параметры заказа и список проверок —
[docs/manufacturing.md](../../docs/manufacturing.md). Gerber и сверловка выгружены из
`hardware/kicad/isa-flash-disk.kicad_pcb`:

```bash
kicad-cli pcb export gerbers -l "F.Cu,B.Cu,F.Mask,B.Mask,F.SilkS,B.SilkS,Edge.Cuts" --subtract-soldermask --no-x2 --no-netlist -o hardware/gerber/rev-A/ hardware/kicad/isa-flash-disk.kicad_pcb
```

```bash
kicad-cli pcb export drill --format excellon --excellon-units mm --excellon-separate-th --generate-map --map-format pdf -o hardware/gerber/rev-A/ hardware/kicad/isa-flash-disk.kicad_pcb
```

Неметаллизированных отверстий нет, поэтому NPTH.drl пустой и в архив не входит.
