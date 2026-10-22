/**
 * All user-visible strings of module 04_orders (Spec 5.4). Field
 * limits and counters are NOT here — they arrive in GET /orders/rules
 * (the server is the source of truth).
 */
export const ORDERS_TEXTS = {
  blockTitle: 'Приказы',
  submitButton: 'Подать приказ',
  cancel: 'Отмена',
  closeButton: 'Закрыть',

  /* «Ожидают вердикт» list */
  assignedTitle: 'Ожидают вердикт',
  assignedEmpty: 'Приказов на рассмотрении нет',
  assignedLoadError: 'Не удалось загрузить',
  assignedDeadline: (deadlineText: string) => `до ${deadlineText}`,
  assignedOverdue: (deadlineText: string) => `срок вышел ${deadlineText}`,
  refreshButton: 'Обновить',

  /* OrderComposer */
  composerTitle: 'Подать приказ',
  fieldTitle: 'Название',
  fieldSummary: 'Краткая суть приказа',
  fieldUrl: 'Ссылка на статью ВК',
  sendButton: 'Отправить приказ',
  unresolvedCounter: (unresolved: number, max: number) =>
    `Неразрешённых приказов: ${unresolved} из ${max}`,
  lengthCounter: (length: number, max: number) => `${length} из ${max}`,
  limitReached:
    'Достигнут предел: дождитесь вердикта по одному из ваших приказов',
  rulesLoadError: 'Не удалось загрузить правила',
  retry: 'Повторить',
  submitErrorTitle: 'Не удалось подать приказ',

  /* ConfirmSubmitModal */
  confirmTitle: 'Отправить приказ?',
  confirmWarning:
    'Уверены ли вы, всё ли проверили: изменить приказ после подачи нельзя',
  confirmTitleLabel: 'Название',
  confirmSummaryLabel: 'Краткая суть',
  confirmUrlLabel: 'Статья',
  openLink: 'Открыть ссылку',
  backToEdit: 'Вернуться к правке',
  confirmSend: 'Да, отправить',

  /* VerdictComposer + ConfirmVerdictModal */
  verdictComposerTitle: (number: number) => `Вердикт по приказу №${number}`,
  verdictFieldSummary: 'Краткая суть вердикта',
  verdictSendButton: 'Отправить вердикт',
  verdictConfirmTitle: 'Отправить вердикт?',
  verdictConfirmWarning:
    'Уверены ли вы, всё ли проверили: изменить вердикт после отправки нельзя',
  verdictSubmitErrorTitle: 'Не удалось записать вердикт',
  effectsBlockTitle: 'Изменение показателей и модификаторы',
  effectsBlockHint: 'Раздел станет доступен позже',

  /* OrderDetailModal */
  detailTitle: (number: number) => `Приказ №${number}`,
  notFound: 'Приказ не найден',
  summaryBlockTitle: 'Краткая суть приказа',
  articleLink: 'Статья приказа',
  verdictBlockTitle: 'Вердикт',
  verdictSummaryTitle: 'Краткая суть вердикта',
  verdictArticleLink: 'Статья вердикта',
  overdueMark: 'Срок вердикта вышел',
  writeVerdict: 'Написать вердикт',
} as const;
