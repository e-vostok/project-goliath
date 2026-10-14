/**
 * UI texts of the «Реестр» window (Spec 5.5): buttons, hints,
 * placeholders and messages. Table/column titles come from the server
 * (GET /registry/tables), never from this file.
 */

export const REGISTRY_TEXTS = {
  panelTitle: 'Реестр',
  back: 'Назад',

  searchPlaceholder: 'Поиск…',
  refresh: 'Обновить',
  reset: 'Сбросить',
  retry: 'Повторить',

  tablesLoadError: 'Не удалось загрузить таблицы реестра',
  rowsLoadError: 'Не удалось загрузить таблицу',
  nothingFound: 'Ничего не найдено',

  shownCounter: (shown: number, total: number) =>
    `Показано ${shown} из ${total}`,

  filterButtonAriaLabel: (columnTitle: string) =>
    `Фильтр столбца «${columnTitle}»`,
  filterContainsLabel: 'Содержит',
  filterFromLabel: 'от',
  filterToLabel: 'до',
  filterPresenceLabel: 'Признак',
  presenceAny: 'Все',
  presenceHas: 'Есть',
  presenceNone: 'Нет',

  sortAriaLabel: (columnTitle: string) =>
    `Сортировка по «${columnTitle}»`,

  emptyValue: '—',
};
