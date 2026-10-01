# tools/map_pipeline

Оффлайн-инструмент подготовки данных карты (developer tool, трек `map_pipeline`).
Детерминированно превращает `data/map/source/map.svg` + `boundary.yaml` +
`overrides.yaml` в узлы суши и `ids.lock.json`. Входные файлы не изменяются;
БД и код backend не затрагиваются.

## Установка

```bash
pip install -r tools/map_pipeline/requirements.txt
```

## Запуск (из корня репозитория)

```bash
# шаги 1–4: узлы суши, out/land_nodes.json, out/report.md, ids.lock.json
python -m tools.map_pipeline nodes

# проверка без записи: код выхода 1, если ids.lock.json изменился бы
python -m tools.map_pipeline nodes --check
```

Свои каталоги: `--data-dir` (по умолчанию `data/map`), `--out-dir`
(по умолчанию `tools/map_pipeline/out`, в `.gitignore`).

## Тесты

```bash
pytest tools/map_pipeline/tests
```

Тесты пишут настоящие SVG/YAML/JSON во временные каталоги (без моков).
Маркер `real_data` — прогон на реальной карте: `pytest -m real_data`.

## Конфигурация

Все настраиваемые параметры — только в `pipeline_config.yaml`; схема с
жёсткими диапазонами — `pipeline_config_schema.py` (неизвестные ключи
запрещены). Секции `geometry`, `raster`, `simplify` объявлены заранее,
их логика появится в MP-2 / MP-3.

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
