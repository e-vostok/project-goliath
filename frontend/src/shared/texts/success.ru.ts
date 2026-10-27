/**
 * success.ru.ts — the Russian texts of the shared success message
 * (UI Spec 7, version 0.9.0 unit 9): every «done» of a write action
 * ends with one of these, shown through `Notice`. Sibling of
 * `errors.ru.ts` — a second language is a new file later.
 */
export const SUCCESS_RU = {
  nationCreated: 'Государство создано',
  nationSaved: 'Изменения сохранены',
  flagUploaded: 'Флаг загружен',
  portraitUploaded: 'Портрет загружен',
  orderSubmitted: (orderNumber: number): string =>
    `Приказ №${orderNumber} подан`,
  verdictSubmitted: (orderNumber: number): string =>
    `Вердикт по приказу №${orderNumber} записан`,
} as const;
