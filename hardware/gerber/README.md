# Gerber

| Файл | Что это |
|---|---|
| `isa-flash-disk-revB-jlcpcb.zip` | **актуальная ревизия B**, архив для заказа: F/B.Cu, F/B.Mask, F/B.Silkscreen, Edge.Cuts, PTH.drl |
| `rev-B/` | те же файлы по отдельности, карты сверловки PDF и job-файл |
| `isa-flash-disk-revA-jlcpcb.zip`, `rev-A/` | ревизия A, заказана в JLCPCB 2026-11-15; файлы сохранены без изменений |

Rev B отличается от rev A только шелкографией: медь, маска, сверловка и контур те же
([CHANGELOG](../../CHANGELOG.md)). **Обе ревизии — прототипы, в железе не проверены.** Параметры заказа и
список проверок — [docs/manufacturing.md](../../docs/manufacturing.md). Gerber и сверловка rev B выгружены из
`hardware/kicad/isa-flash-disk.kicad_pcb`:

```bash
kicad-cli pcb export gerbers -l "F.Cu,B.Cu,F.Mask,B.Mask,F.SilkS,B.SilkS,Edge.Cuts" --subtract-soldermask --no-x2 --no-netlist -o hardware/gerber/rev-B/ hardware/kicad/isa-flash-disk.kicad_pcb
```

```bash
kicad-cli pcb export drill --format excellon --excellon-units mm --excellon-separate-th --generate-map --map-format pdf -o hardware/gerber/rev-B/ hardware/kicad/isa-flash-disk.kicad_pcb
```

Неметаллизированных отверстий нет, поэтому NPTH.drl пустой и в архив не входит.
