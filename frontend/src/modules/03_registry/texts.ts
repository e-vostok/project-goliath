/**
 * UI texts of the «Реестр» window (Spec 5.5): buttons, hints,
 * placeholders and messages. Table/column titles come from the server
 * (GET /registry/tables), never from this file.
 */

/** A scale bound with its sign («−100», «+100», «0») — typographic
    minus U+2212, as the mockups write it. */
const scaleBound = (n: number) =>
  n > 0 ? `+${n}` : n < 0 ? `\u2212${-n}` : '0';

export const REGISTRY_TEXTS = {
  panelTitle: 'Реестр',

  searchPlaceholder: 'Поиск…',
  filtersButton: 'Фильтры',
  refresh: 'Обновить',
  reset: 'Сбросить',
  retry: 'Повторить',

  tablesLoadError: 'Не удалось загрузить таблицы реестра',
  rowsLoadError: 'Не удалось загрузить таблицу',
  nothingFound: 'Ничего не найдено',

  shownCounter: (shown: number, total: number) =>
    `Показано ${shown} из ${total}`,

  filterContainsLabel: 'Содержит',
  filterContainsPlaceholder: 'содержит…',
  filterFromLabel: 'от',
  filterToLabel: 'до',
  filterPresenceLabel: 'Признак',
  /** The presence control is its own grid cell right after the
      column's group, labelled «<столбец>: наличие» (unit 13b). */
  filterPresenceTitle: (columnLabel: string) => `${columnLabel}: наличие`,
  presenceAny: 'Все',
  presenceHas: 'Есть',
  presenceNone: 'Нет',
  filterSelectLabel: 'Список',
  filterSelectAll: 'Все государства',
  /** «от −100» / «до +100» — placeholders of a `number_range` whose
      column carries `scale_min`/`scale_max` (the players' «Рейтинг»). */
  filterFromWithBound: (min: number) => `от ${scaleBound(min)}`,
  filterToWithBound: (max: number) => `до ${scaleBound(max)}`,
  /** `gauge` cell title: «<число> · шкала −100…+100» (unit 13b) — the
      number keeps the cell's own look («+» for positives). */
  gaugeScaleTitle: (value: number, min: number, max: number) =>
    `${value > 0 ? `+${value}` : `${value}`} · шкала ${scaleBound(min)}…${scaleBound(max)}`,

  /* Table filter extensions (Spec 5.5) — the «Все / Да» control a
     module registers for a table («Назначены мне»). */
  extFilterAll: 'Все',
  extFilterYes: 'Да',
  extFilterLoading: 'Загрузка…',

  sortAriaLabel: (columnTitle: string) =>
    `Сортировка по «${columnTitle}»`,

  overdueMark: 'срок вышел',

  emptyValue: '—',
};
