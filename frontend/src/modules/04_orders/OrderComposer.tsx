/**
 * OrderComposer — the «Подать приказ» window (Spec 5.4): a Popup M.
 *
 * Three fields (title, multi-line summary, VK article link) with a
 * per-field length counter and the «Неразрешённых приказов: N из M»
 * line — all limits come from GET /orders/rules, the server stays the
 * source of truth (a failed rules request keeps the form usable, it
 * just shows no counters). «Отправить приказ» leads to the
 * confirmation window; it is disabled at the author limit and shows
 * the Spec explanation. Errors bounced back from the submit land
 * here through a prop update (the form stays mounted under the
 * confirmation): field codes at their field, the rest as a banner.
 * Enter in a single-line field does nothing; Enter in the textarea
 * inserts a line break — no <form>, no implicit submit.
 */

import { useEffect, useState } from 'react';
import {
  Button,
  FormItem,
  FormStatus,
  Input,
  Text,
  Textarea,
} from '@vkontakte/vkui';

import { errorText } from '../../shared/errorTexts';
import { Popup } from '../../shared/ui';
import { useFormDraft } from '../../shared/formDraft';
import { useOrderRules } from './hooks/useOrderRules';
import { ORDERS_TEXTS } from './texts';
import { OrderErrorCodes, type OrderRulesDTO } from './types';
import {
  ORDER_DRAFT_KEY,
  useOrdersUi,
  type ComposerServerError,
  type OrderDraft,
} from './OrdersUiProvider';

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

/** What the live form reports up — feeds the Popup's dirty and footer. */
interface ComposerLive {
  dirty: boolean;
  canSend: boolean;
  draft: OrderDraft;
}

const EMPTY_LIVE: ComposerLive = {
  dirty: false,
  canSend: false,
  draft: { title: '', summary: '', articleUrl: '' },
};

export function OrderComposer() {
  const { orderWindow, toConfirm, closeWindow } = useOrdersUi();
  const [live, setLive] = useState<ComposerLive>(EMPTY_LIVE);

  // The composer stays rendered (and keeps its input) while the S
  // confirmation lies over it — both views carry the same draft.
  const win =
    orderWindow?.view === 'composer' || orderWindow?.view === 'confirm'
      ? orderWindow
      : null;
  if (win === null) {
    return null;
  }
  const serverError = win.view === 'composer' ? win.error : null;

  return (
    <Popup
      size="M"
      icon="document"
      title={ORDERS_TEXTS.composerTitle}
      onClose={closeWindow}
      dirty={live.dirty}
      testId="popup-order-composer"
      footer={
        <>
          <Button size="m" mode="secondary" onClick={closeWindow}>
            {ORDERS_TEXTS.cancel}
          </Button>
          <Button
            size="m"
            mode="primary"
            disabled={!live.canSend}
            onClick={() => toConfirm(live.draft)}
          >
            {ORDERS_TEXTS.sendButton}
          </Button>
        </>
      }
    >
      <ComposerForm
        draft={win.draft}
        serverError={serverError}
        onLive={setLive}
      />
    </Popup>
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
  onLive,
}: {
  draft: OrderDraft;
  serverError: ComposerServerError | null;
  onLive: (live: ComposerLive) => void;
}) {
  const rulesState = useOrderRules();
  const rules = rulesState.status === 'ready' ? rulesState.rules : null;

  // Draft memory: a session-stored draft wins over the window's empty
  // one on reopen; a bounce back from the confirmation carries the
  // same values, so either source agrees.
  const {
    draft: storedDraft,
    setDraft: setStoredDraft,
    clearDraft,
  } = useFormDraft<OrderDraft>(ORDER_DRAFT_KEY);
  const initial = storedDraft ?? draft;

  const [title, setTitle] = useState(initial.title);
  const [summary, setSummary] = useState(initial.summary);
  const [articleUrl, setArticleUrl] = useState(initial.articleUrl);

  // Mirror the fields into the session draft; a fully emptied form
  // drops it (the provider deletes it on a successful send).
  useEffect(() => {
    if (title === '' && summary === '' && articleUrl === '') {
      clearDraft();
    } else {
      setStoredDraft({ title, summary, articleUrl });
    }
  }, [title, summary, articleUrl, setStoredDraft, clearDraft]);

  const [fieldErrors, setFieldErrors] = useState<
    Partial<Record<OrderField, string>>
  >(() => {
    const field = serverError ? orderFieldForCode(serverError.code) : null;
    return field && serverError ? { [field]: serverError.message } : {};
  });
  // A banner error bounced from the submit (no field owns it).
  const [formError, setFormError] = useState<string | null>(() =>
    serverError !== null && orderFieldForCode(serverError.code) === null
      ? serverError.message
      : null,
  );

  // The composer stays mounted under the confirmation — a coded error
  // bounced back arrives as a prop update, not a fresh mount.
  useEffect(() => {
    if (serverError === null) {
      return;
    }
    const field = orderFieldForCode(serverError.code);
    if (field !== null) {
      setFieldErrors((prev) => ({ ...prev, [field]: serverError.message }));
    } else {
      setFormError(serverError.message);
    }
  }, [serverError]);

  const limitReached =
    rules !== null && rules.unresolved_orders >= rules.max_unresolved_orders;
  const filled =
    title.trim().length > 0 &&
    summary.trim().length > 0 &&
    articleUrl.trim().length > 0;
  const canSend = filled && !limitReached;

  // Report dirty/canSend/the live draft up for the Popup and footer.
  useEffect(() => {
    onLive({
      dirty: title !== '' || summary !== '' || articleUrl !== '',
      canSend,
      draft: { title, summary, articleUrl },
    });
  }, [title, summary, articleUrl, canSend, onLive]);

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
    <>
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
            {errorText(rulesState.error)}
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
    </>
  );
}
