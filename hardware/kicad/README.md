# KiCad

Проект для **KiCad 9.0.2 или новее**: открыть `isa-flash-disk.kicad_pro`.

| Файл | Что это |
|---|---|
| `isa-flash-disk.kicad_sch` | схема rev A, один лист A2 |
| `isa_flash_disk.kicad_sym` | символ Intel 28F008SA (выводы PSOP-44 по DS, рис. 3) |
| `isa_flash_disk.pretty/` | все посадочные места проекта: PSOP-44 по чертежу Intel, ISA 8 бит, копии стандартных KiCad 9 |
| `expected-nets.json` | таблица соединений, из которой построена схема |
| `reports/erc.rpt` | последний отчёт ERC |
| `reports/netlist-check.txt` | сверка нетлиста с `expected-nets.json` |

Статус: **схема rev A, ERC без нарушений, нетлист совпадает с таблицей соединений. Платы нет, в железе не
проверялось.** PDF схемы — [docs/schematic.pdf](../../docs/schematic.pdf).

## Как схема получена

Rev A сгенерирована скриптами:

```bash
python tools/kicad/gen_footprints.py
```

```bash
python tools/kicad/gen_schematic.py
```

Генератор соединяет выводы короткими проводниками с метками цепей, поэтому схема читается как таблица
соединений. Дальше её можно править в KiCad. Генератор не перезапишет схему, изменённую вручную
(сверяет SHA-256 с `.generated.sha256`); `--force` отбрасывает ручные правки.

## Проверка после изменений

```bash
kicad-cli sch erc --format report --severity-all -o hardware/kicad/reports/erc.rpt hardware/kicad/isa-flash-disk.kicad_sch
```

```bash
kicad-cli sch export netlist --format kicadsexpr -o netlist.net hardware/kicad/isa-flash-disk.kicad_sch
```

```bash
python tools/kicad/check_netlist.py netlist.net
```

Нетлист содержит абсолютные локальные пути, в репозиторий его не класть.
