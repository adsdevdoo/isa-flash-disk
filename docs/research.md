# Исследование (этап 1)

Журнал того, что найдено, откуда и какие решения из этого следуют.

## Источники

Все документы сохранены в репозитории, SHA-256 — в [datasheets/SHA256SUMS](datasheets/SHA256SUMS)
и [references/SHA256SUMS](references/SHA256SUMS).

| Документ | Откуда взят | Файл |
|---|---|---|
| Intel 28F008SA datasheet 290429-008 (12/1998) | DigiKey: `mm.digikey.com/…/28F008SA (x8).pdf` | [datasheets/intel-28f008sa-290429-008.pdf](datasheets/intel-28f008sa-290429-008.pdf) |
| Intel AP-359 28F008SA Hardware Interfacing (09/1993) | bitsavers: `components/intel/_dataBooks/1995_Intel_Flash_Memory_Volume_1.pdf`, с. 3-551…3-561 | [datasheets/intel-ap-359-…](datasheets/intel-ap-359-28f008sa-hardware-interfacing-292094-003.pdf) |
| Intel AP-360 28F008SA Software Drivers (09/1993) | там же, с. 3-562…3-583 | [datasheets/intel-ap-360-…](datasheets/intel-ap-360-28f008sa-software-drivers-292095.pdf) |
| Intel AP-364 28F008SA Automation and Algorithms (01/1996) | архив `download.intel.com/design/archives/flash/docs/29209903.pdf` (зеркало peertje.daanberg.net) | [datasheets/intel-ap-364-…](datasheets/intel-ap-364-28f008sa-automation-algorithms-292099-003.pdf) |
| IBM 5160/5155 Technical Reference 6139821 (1986) | sharktastica.co.uk | [references/ibm-5160-…](references/ibm-5160-technical-reference-6139821-1986.pdf) |
| IBM 5170 AT Technical Reference 6183355 (03/1986) | bitsavers: `pdf/ibm/pc/at/` | [references/ibm-5170-…](references/ibm-5170-technical-reference-6183355-mar86.pdf) |
| Intel «PSOP: 44 Lead Plastic Small Outline Package Drawing» v1.0 | архив Intel `DESIGN/FLCOMP/PACKDATA/2232_1.PDF` (зеркало intel-vintage-developer.eu5.org) | [datasheets/intel-psop-44-package-2232-1.pdf](datasheets/intel-psop-44-package-2232-1.pdf) |
| TI CD74HCT688, SN74HCT138, SN74HCT273, CD74HCT175, SN74HCT32, SN74HCT04, SN74LS245 | ti.com | `datasheets/ti-*.pdf` |
| AOS AO3407A, onsemi 2N7002L | aosmd.com, onsemi.com | `datasheets/aos-ao3407a.pdf`, `datasheets/onsemi-2n7002l.pdf` |

Распиновки 74HCT688, 74HCT175 и 74LS245 сверены с рисунками даташитов и с символами KiCad 9.

Не найдены:

- **28F008SA Specification Update 297183** (errata). Номер указан в DS на с. 42, но документа в открытых архивах нет.
- **IEEE P996** (спецификация ISA с временными параметрами). Удержание данных при записи проверяем осциллографом.

## Микросхема

Полная сводка — [intel-28f008sa.md](intel-28f008sa.md). Ключевое для проекта:

- 1 Мбайт, 16 блоков по 64 Кбайт, 100 000 циклов на блок.
- PSOP-44 (`PA`), распиновка подтверждена по рисунку 3 даташита.
- VPP 11.4…12.6 В для записи, ≤ 6.5 В — запись невозможна. Ток VPP до 30 мА на микросхему.
- Входы ТТЛ, доступ 85 или 120 нс: шина ISA подключается без тактов ожидания.
- Коды ID `89h`, `A2h` читаются без VPP.

## Шина ISA

Полная сводка — [isa-interface.md](isa-interface.md). Ключевое:

- Цикл 8-битной памяти: 840 нс на XT, 750–1000 нс на AT — флеш успевает с большим запасом.
- +12 В блока питания IBM: 11.52…12.60 В — укладывается в VPPH, но без запаса сверху.
- −SMEMR/−SMEMW на AT активны только в первом мегабайте — подходит для окна.
- Слот J8 у IBM 5160 для карты не годится.
- Option ROM: C8000h…F4000h, шаг 2 Кбайт, `55AAh`, длина, контрольная сумма.

## Оригинальный модуль

Решение — снимать микросхемы и ставить на карту по 1–2 штуки. Подробнее — [original-module.md](original-module.md).

## Проект XT-CF-Lite V4 как основа

Предложен [skiselev/xt-cf-lite-v4](https://github.com/skiselev/xt-cf-lite-v4) (Сергей Киселёв).

Что это: 8-битная ISA-карта для CompactFlash. CF подключён к портам ввода-вывода, рядом — EEPROM 28C64 8 Кбайт
с XT-IDE Universal BIOS. Декодеры — 2 × 74LS688 с DIP-переключателями, плюс 74LS32 и 74LS04.

Что берём как идею:

- дешифрацию адреса парой 74xx688 с DIP-переключателями — у нас то же самое;
- предупреждения о конфликтах адресов ПЗУ (C0000h…C6000h — EGA/VGA, C8000h…CA000h — контроллер HDD XT);
- размер ПЗУ 8 Кбайт.

Что не подходит:

- CompactFlash — это устройство ATA со своим контроллером. 28F008SA — «сырая» память без контроллера,
  поэтому XT-IDE Universal BIOS с ней работать не может. Нужен собственный Option ROM.
- В репозитории XT-CF-Lite нет лицензии (GitHub API `license: null`). Владелец isa-flash-disk сообщил, что это
  его проект; после подтверждения его файлы (контур платы, планка, краевой разъём) можно использовать на этапе 5.
  Схема rev A от XT-CF-Lite не заимствует ничего, кроме подхода.

## Правила из retro535

Из проекта [adsdevdoo/retro535](https://github.com/adsdevdoo/retro535) того же владельца перенесены рабочие правила:
генераторы не затирают ручные правки KiCad, все посадочные места лежат в библиотеке проекта, площадки 0805 — под
ручную пайку, отчёты ERC/DRC относятся к последним файлам, явный статус в README, правила JLCPCB и визуальной
проверки платы. Сводка — в [AGENTS.md](../AGENTS.md).

## Решения этапа 1

1. Модуль целиком не используется, микросхемы ставятся на карту по 1–2 штуки.
2. Вариант A — окно 8 Кбайт и регистр банка ([architecture.md](architecture.md)).
3. Option ROM хранится в блоке 0 флеш U1, резидентная часть копируется в ОЗУ.
4. VPP — от +12 В шины через P-MOSFET, четыре уровня защиты, JP1 по умолчанию снята.
5. Логика 74HCT, без микроконтроллера и без обязательной прошивки GAL.
6. Имена утилит в формате 8.3: `FLINFO`, `FLREAD`, `FLWRITE`, `FLFORMAT`.

## Открытые вопросы

| Вопрос | Как закрываем | Этап |
|---|---|---|
| Корпус снятых микросхем совпадает с чертежом Intel | контроль одной микросхемы перед заказом ([testing.md](testing.md)) | 5 |
| Ограничение размера платы 100 мм (как в retro535) | уточнить у владельца | 5 |
| Удержание данных после −MEMW на реальных машинах | осциллограф на прототипе | 2 |
| +12 В на реальных машинах | мультиметр, перед первой записью | 2 |
| −MEMCS16 от VGA в блоке C0000h…DFFFFh | тест на AT/386 с 16-битной VGA | 2 |
| Загрузка с диска 80h на разных BIOS | тесты в 86Box и на железе | 4 |
