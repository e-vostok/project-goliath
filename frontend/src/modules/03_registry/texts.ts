/**
 * UI texts of the «Реестр» window (Spec 5.5): buttons, hints,
 * placeholders and messages. Table/column titles come from the server
 * (GET /registry/tables), never from this file.
 */

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
  presenceAny: 'Все',
  presenceHas: 'Есть',
  presenceNone: 'Нет',
  filterSelectLabel: 'Список',
  filterSelectAll: 'Все',

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
