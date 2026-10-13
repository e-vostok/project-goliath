# tools/map_pipeline

Оффлайн-инструмент подготовки данных карты (developer tool, трек `map_pipeline`).
Детерминированно превращает `data/map/source/map.svg` + `boundary.yaml` +
`overrides.yaml` в узлы суши, морские зоны, граф соседства и `ids.lock.json`.
Входные файлы не изменяются; БД и код backend не затрагиваются.

## Установка

```bash
pip install -r tools/map_pipeline/requirements.txt
```

## Запуск (из корня репозитория)

```bash
# шаги 1–4: узлы суши, out/land_nodes.json, out/report.md, ids.lock.json
python -m tools.map_pipeline nodes

# шаги 1–6: то же + морские зоны и граф
python -m tools.map_pipeline graph

# проверка без записи: код выхода 1, если ids.lock.json изменился бы
python -m tools.map_pipeline graph --check

# без PNG-превью
python -m tools.map_pipeline graph --no-preview
```

Свои каталоги: `--data-dir` (по умолчанию `data/map`), `--out-dir`
(по умолчанию `tools/map_pipeline/out`, в `.gitignore`).

## Выходы `graph` (в `--out-dir`)

- `land_nodes.json`, `report.md` — как у `nodes`.
- `graph.json` — `{nodes, edges}`: узлы `LAND`/`SEA` с id, ключом, именем и
  площадью; рёбра `{a, b, type, len}` (типы `land`, `coast`, `sea`, `strait`;
  у проливов `name`/`multiplier`, у ручных рёбер `len: null`).
- `sea_labels.npy` (`int16`) — индекс морской зоны на пиксель, 0 = нет;
  `sea_kinds.npy` (`uint8`) — 0 суша, 1 вода зоны, 2 неизвестное море,
  3 озеро. `sea_raster.json` — рамка растра и конвенция пикселей.
- `graph_report.md` — счётчики, таблица зон, привязанные семена, озёра,
  `water_outside`, несвязанные куски полосы, аномалии, острова.
- `graph_preview.png` — цветной предпросмотр (копия коммитится в
  `data/map/preview/` для ревью).

`ids.lock.json` общий для обеих команд: ключи суши и ключи `sea_*` из
`overrides.sea_zones`; новые id выдаются сначала сушей (по возрастанию ключа),
потом морями. `nodes` и `graph` пишут одинаковый замок.

## Геометрические патчи и ремонт швов

`overrides.yaml:geometry_patches` применяется после разбора SVG и чистки,
до фильтрации по boundary:

- `transfer_part`: кластер частей `from`, содержащий `cluster_point`
  (части связаны через зазоры < 0.5 ед.), вырезается из `from` и
  объединяется в `to`. Касающийся кластер обязан слиться с `to` в один
  полигон; отделённый требует `allow_detached: true`. Новых id нет;
  рёбра и якоря пересчитываются.
- `detach`: кластеры, выбранные `cluster_points`, уходят из `from` и
  образуют один новый узел `new_key`/`new_name` со следующим свободным
  id (замок только пополняется).
- Любое нарушение правил патча — `PATCH_INVALID`.

`overrides.yaml:seam_repair` — шаг ремонта «швов» у перечисленных узлов:
кольца одного узла, чьи границы совпадают или идут параллельно ближе
~0.03 ед. на длине от 0.05 ед., сливаются в одно внешнее кольцо (union,
иначе наименьшее морфологическое замыкание). Применяется к финальной
(канонической) геометрии узла; ремонт выводится строкой в build_report.

## Тесты

```bash
pytest tools/map_pipeline/tests
```

Тесты пишут настоящие SVG/YAML/JSON во временные каталоги (без моков).
Маркер `real_data` — прогон на реальной карте: `pytest -m real_data`.

## Конфигурация

Все настраиваемые параметры — только в `pipeline_config.yaml`; схема с
жёсткими диапазонами — `pipeline_config_schema.py` (неизвестные ключи
запрещены). Секция `simplify` объявлена заранее, её логика появится в MP-3.

## Коды ошибок

| Код | Причина |
| --- | --- |
| `CONFIG_INVALID` | `pipeline_config.yaml` не читается или нарушает схему |
| `DATA_INVALID` | входные данные не проходят схему или ссылочные проверки |
| `UNSUPPORTED_TRANSFORM` | у пути провинции или его предка есть `transform` |
| `DUPLICATE_ID` | два контура провинций с одним `id` |
| `BOUNDARY_UNKNOWN_ID` | имя из `boundary.yaml:include` отсутствует в SVG |
| `KEY_INVALID` | `source_name.lower()` не соответствует `^[a-z0-9_]+$` |
| `KEY_COLLISION` | два имени дают одинаковый ключ |
| `DROP_PART_NOT_FOUND` | точка `drop_parts` не попадает ни в один кусок провинции |
| `DROP_PART_EMPTIES_PROVINCE` | `drop_parts` убирает все куски провинции |
| `ISOLATED_PART` | обособленный кусок игровой провинции, у которого в окружении только исключённые провинции; требует `drop_parts` или `keep_parts` |
| `KEY_REMOVED` | ключ `ids.lock.json` исчез из входа (молчаливое удаление запрещено, INV-M1) |
| `IDS_LOCK_INVALID` | `ids.lock.json` не проходит схему (дубликат id, id < 1001, плохой ключ) |
| `SEED_OUTSIDE_WATER` | семя морской зоны не находит рабочей воды в радиусе `sea.seed_snap_radius` |
| `ZONE_EMPTY` | зоне не досталось ни одного пикселя |
| `UNSEEDED_WATER` | крупный водоём в полосе без семени и без `water_outside`, либо недостигнутый кусок полосы в засеянном водоёме |
| `WATER_OUTSIDE_INVALID` | точка `water_outside` не в крупном незасеянном водоёме |
| `EDGE_UNKNOWN_NODE` | конец ребра в `edges_add`/`edges_remove`/`straits` — неизвестный узел |
| `EDGE_TYPE_MISMATCH` | тип ребра не соответствует видам концов (INV-M2) |
| `EDGE_REMOVE_NOT_FOUND` | `edges_remove` для пары без ребра |
| `STRAIT_ALREADY_CONNECTED` | пролив между уже соединёнными узлами |
| `GRAPH_DISCONNECTED` | нарушение INV-M3; перечисляются все компоненты кроме крупнейшей |
| `GRAPH_INVARIANT` | внутреннее нарушение INV-M2 (петля, дубль пары, плохие концы) |
