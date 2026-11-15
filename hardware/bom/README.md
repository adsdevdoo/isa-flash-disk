# BOM

[isa-flash-disk-bom.csv](isa-flash-disk-bom.csv) — перечень элементов схемы rev A, выгружен из KiCad:

```bash
kicad-cli sch export bom --fields 'Reference,Value,Footprint,MPN,${QUANTITY},Datasheet' --labels 'Reference,Value,Footprint,MPN,Qty,Datasheet' --group-by 'Value,Footprint,MPN' --sort-field Reference --exclude-dnp -o hardware/bom/isa-flash-disk-bom.csv hardware/kicad/isa-flash-disk.kicad_sch
```

Микросхемы 28F008SA снимаются с исходного модуля ([docs/original-module.md](../../docs/original-module.md)).
Артикулы LCSC/JLCPCB и цены — на этапе 5. Плата рассчитана на ручную пайку.
