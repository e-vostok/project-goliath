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
  /* Шкала рейтинга (макеты 26–26в, единица 11б). */

  /** Число рейтинга со знаком — «+35», «−20», «0» (типографский
      минус U+2212): ячейка, плитка и подписи шкалы. */
  ratingNumber: (value: number) => scaleBound(value),

  /** `aria-label` шкалы: «Рейтинг +35 из диапазона −100…+100». */
  ratingAriaLabel: (value: number, min: number, max: number) =>
    `Рейтинг ${scaleBound(value)} из диапазона ${scaleBound(min)}…${scaleBound(max)}`,

  ratingTipTitle: 'Судейский рейтинг',
  /** Подсказка заголовка «Рейтинг»: «От −100 до +100. …» — границы
      берутся из `scale_min`/`scale_max` столбца (макет 26б). */
  ratingTipText: (min: number, max: number) =>
    `От ${scaleBound(min)} до ${scaleBound(max)}. Судьёй приказа назначают игрока с рейтингом не ниже порога.`,

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
