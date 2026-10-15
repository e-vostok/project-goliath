/**
 * OrderComposer — the «Подать приказ» window (Spec 5.4).
 *
 * Three fields (title, multi-line summary, VK article link) with a
 * per-field length counter and the «Неразрешённых приказов: N из M»
 * line — all limits come from GET /orders/rules, the server stays the
 * source of truth (a failed rules request keeps the form usable, it
 * just shows no counters). «Отправить приказ» leads to the
 * confirmation window; it is disabled at the author limit and shows
 * the Spec explanation. Errors bounced back from the submit land
 * here: field codes at their field, the rest as a banner.
 */

import { useState } from 'react';
import {
  Button,
  Div,
  FormItem,
  FormStatus,
  Input,
  ModalPage,
  ModalPageHeader,
  Text,
  Textarea,
  type NavIdProps,
} from '@vkontakte/vkui';

import { useOrderRules } from './hooks/useOrderRules';
import { ORDERS_TEXTS } from './texts';
import {
  OrderErrorCodes,
  type OrderRulesDTO,
} from './types';
import {
  useOrdersUi,
  type ComposerServerError,
  type OrderDraft,
} from './OrdersUiProvider';

/** Fits inside the 910 px window budget like every other window. */
const MODAL_SIZE = 'min(880px, calc(100vw - 64px))';

type OrderField = 'title' | 'summary' | 'articleUrl';

/** ErrorResponse.code → the composer's field; null = banner error. */
export function orderFieldForCode(code: string): OrderField | null {
  switch (code) {
    case OrderErrorCodes.ORDER_TITLE_INVALID:
      return 'title';
    case OrderErrorCodes.ORDER_SUMMARY_INVALID:
      return 'summary';
    case OrderErrorCodes.ORDER_URL_INVALID:
      return 'articleUrl';
    default:
      return null;
  }
}

export function OrderComposer({ id, ...navIdProps }: NavIdProps) {
  const { orderWindow, toConfirm, closeWindow } = useOrdersUi();
  const win = orderWindow?.view === 'composer' ? orderWindow : null;

  return (
    <ModalPage
      id={id}
      {...navIdProps}
      onClose={closeWindow}
      size={MODAL_SIZE}
      header={
        <ModalPageHeader>{ORDERS_TEXTS.composerTitle}</ModalPageHeader>
      }
    >
      {win !== null && (
        <ComposerForm
          draft={win.draft}
          serverError={win.error}
          onSend={toConfirm}
        />
      )}
    </ModalPage>
  );
}

function fieldCounter(
  rules: OrderRulesDTO | null,
  field: OrderField,
  length: number,
): string | undefined {
  if (!rules) {
    return undefined;
  }
  const max =
    field === 'title'
      ? rules.title_max_length
      : field === 'summary'
        ? rules.summary_max_length
        : rules.url_max_length;
  return ORDERS_TEXTS.lengthCounter(length, max);
}

function ComposerForm({
  draft,
  serverError,
  onSend,
}: {
  draft: OrderDraft;
  serverError: ComposerServerError | null;
  onSend: (draft: OrderDraft) => void;
}) {
  const rulesState = useOrderRules();
  const rules = rulesState.status === 'ready' ? rulesState.rules : null;

  const [title, setTitle] = useState(draft.title);
  const [summary, setSummary] = useState(draft.summary);
  const [articleUrl, setArticleUrl] = useState(draft.articleUrl);
  const [fieldErrors, setFieldErrors] = useState<
    Partial<Record<OrderField, string>>
  >(() => {
    const field = serverError ? orderFieldForCode(serverError.code) : null;
    return field && serverError ? { [field]: serverError.message } : {};
  });
  // A banner error bounced from the submit (no field owns it) — fixed
  // for this mount; editing fields does not clear it, closing does.
  const [formError] = useState<string | null>(() =>
    serverError !== null && orderFieldForCode(serverError.code) === null
      ? serverError.message
      : null,
  );

  const limitReached =
    rules !== null && rules.unresolved_orders >= rules.max_unresolved_orders;
  const filled =
    title.trim().length > 0 &&
    summary.trim().length > 0 &&
    articleUrl.trim().length > 0;
  const canSend = filled && !limitReached;

  const clearFieldError = (field: OrderField) =>
    setFieldErrors((prev) => {
      if (!(field in prev)) {
        return prev;
      }
      const next = { ...prev };
      delete next[field];
      return next;
    });

  return (
    <Div>
      {rules !== null && (
        <Text data-testid="order-unresolved-counter">
          {ORDERS_TEXTS.unresolvedCounter(
            rules.unresolved_orders,
            rules.max_unresolved_orders,
          )}
        </Text>
      )}
      {rulesState.status === 'error' && (
        <>
          <FormStatus mode="error" title={ORDERS_TEXTS.rulesLoadError}>
            {rulesState.error.message}
          </FormStatus>
          <Button size="s" onClick={rulesState.reload}>
            {ORDERS_TEXTS.retry}
          </Button>
        </>
      )}

      {formError !== null && (
        <FormStatus mode="error" title={ORDERS_TEXTS.submitErrorTitle}>
          {formError}
        </FormStatus>
      )}

      <FormItem
        top={ORDERS_TEXTS.fieldTitle}
        htmlFor="order-title"
        status={fieldErrors.title ? 'error' : 'default'}
        bottom={fieldErrors.title ?? fieldCounter(rules, 'title', title.length)}
        data-testid="form-item-order-title"
      >
        <Input
          id="order-title"
          value={title}
          maxLength={rules?.title_max_length}
          onChange={(e) => {
            setTitle(e.currentTarget.value);
            clearFieldError('title');
          }}
        />
      </FormItem>

      <FormItem
        top={ORDERS_TEXTS.fieldSummary}
        htmlFor="order-summary"
        status={fieldErrors.summary ? 'error' : 'default'}
        bottom={
          fieldErrors.summary ?? fieldCounter(rules, 'summary', summary.length)
        }
        data-testid="form-item-order-summary"
      >
        <Textarea
          id="order-summary"
          value={summary}
          maxLength={rules?.summary_max_length}
          onChange={(e) => {
            setSummary(e.currentTarget.value);
            clearFieldError('summary');
          }}
        />
      </FormItem>

      <FormItem
        top={ORDERS_TEXTS.fieldUrl}
        htmlFor="order-url"
        status={fieldErrors.articleUrl ? 'error' : 'default'}
        bottom={
          fieldErrors.articleUrl ??
          fieldCounter(rules, 'articleUrl', articleUrl.length)
        }
        data-testid="form-item-order-url"
      >
        <Input
          id="order-url"
          value={articleUrl}
          maxLength={rules?.url_max_length}
          placeholder="https://vk.com/@..."
          onChange={(e) => {
            setArticleUrl(e.currentTarget.value);
            clearFieldError('articleUrl');
          }}
        />
      </FormItem>

      {limitReached && (
        <Text
          data-testid="order-limit-reached"
          style={{ color: 'var(--vkui--color_text_negative)' }}
        >
          {ORDERS_TEXTS.limitReached}
        </Text>
      )}

      <Button
        size="l"
        stretched
        disabled={!canSend}
        onClick={() => onSend({ title, summary, articleUrl })}
      >
        {ORDERS_TEXTS.sendButton}
      </Button>
    </Div>
  );
}
