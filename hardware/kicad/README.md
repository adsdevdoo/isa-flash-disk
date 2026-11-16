# KiCad

Проект для **KiCad 9.0.2 или новее**: открыть `isa-flash-disk.kicad_pro`.

| Файл | Что это |
|---|---|
| `isa-flash-disk.kicad_sch` | схема rev A, один лист A2 |
| `isa_flash_disk.kicad_sym` | символ Intel 28F008SA (выводы PSOP-44 по DS, рис. 3) |
| `isa_flash_disk.pretty/` | все посадочные места проекта: PSOP-44 по чертежу Intel, ISA 8 бит, копии стандартных KiCad 9 |
| `expected-nets.json` | таблица соединений, из которой построена схема |
| `isa-flash-disk.kicad_pcb` | плата rev B: 104.14 × 100 мм, 2 слоя, разведена, земля залита с двух сторон. Медь как у rev A, изменена шелкография ([CHANGELOG](../../CHANGELOG.md)) |
| `3d/` | 3D-модели всех деталей (копии из KiCad 9.0.2, [docs/models.md](../../docs/models.md)) |
| `reports/erc.rpt` | последний отчёт ERC |
| `reports/netlist-check.txt` | сверка нетлиста с `expected-nets.json` |
| `reports/drc.rpt` | последний DRC платы с проверкой соответствия схеме |

Статус: **схема rev A, плата rev B: ERC 0, DRC 0, соответствие схеме и плате без расхождений. В железе не
проверялось.** PDF схемы — [docs/schematic.pdf](../../docs/schematic.pdf), заказ — [docs/manufacturing.md](../../docs/manufacturing.md).

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

## Как получена плата

Плата строится в три шага, как в retro535 (размещение скриптом, трассировка FreeRouting, доводка скриптом):

```bash
"C:/Program Files/KiCad/9.0/bin/python.exe" tools/kicad/make_board.py
```

```bash
java -jar freerouting-2.5.0.jar -de hardware/kicad/build/placed.dsn -do hardware/kicad/build/placed.ses -mp 100 --gui.enabled=false
```

```bash
"C:/Program Files/KiCad/9.0/bin/python.exe" tools/kicad/route_board.py
```

- `make_board.py` берёт нетлист из схемы, ставит контур (геометрия под планку Keystone 9202), ламели,
  отверстия под планку, детали, запретную зону на ламелях и зафиксированные отводы от ламелей в тело платы;
  результат — `build/placed.kicad_pcb` и `build/placed.dsn` (папка `build/` не коммитится).
- FreeRouting 2.5.0 — внешний автотрассировщик (github.com/freerouting/freerouting), в репозиторий не входит.
- `route_board.py` импортирует трассировку, заливает землю с двух сторон, добавляет шелкографию и сохраняет
  `isa-flash-disk.kicad_pcb`, переносит правила в `isa-flash-disk.kicad_pro`. Плату, изменённую в KiCad,
  без `--force` не перезаписывает (`.generated-pcb.sha256`).
- Шелкография задана только в `silk_board.py`. `route_board.py` вызывает его до сшивки земли, чтобы
  переходные не попадали под надписи. Отдельно он перерисовывает шелкографию готовой платы, медь не меняет;
  повторный запуск даёт тот же файл:

```bash
"C:/Program Files/KiCad/9.0/bin/python.exe" tools/kicad/silk_board.py
```

  Скрипт ставит обозначения, тип микросхем, транзисторов и резисторных сборок, функциональные подписи,
  нижний информационный блок и таблицы переключателей. Надпись без свободного места или ближе 0.2 мм к
  площадке, 0.15 мм к другой шелкографии — ошибка, а не наложение.

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
