/**
 * VerdictComposer + ConfirmVerdictModal — the judge's verdict windows
 * (Spec 5.4), mirroring the order submission pair.
 *
 * VerdictComposer (Popup M, scales icon): three fields with the same
 * per-field counters and limits from GET /orders/rules as the order
 * composer (the server stays the source of truth); under the fields
 * sits the dashed, dimmed «Изменение показателей и модификаторы»
 * block — verdict effects do not exist in v1 (INV-O13). «Отправить
 * вердикт» leads to the confirmation window. Errors bounced back
 * from the submit land at their field through a prop update — the
 * form stays mounted under the confirmation.
 *
 * ConfirmVerdictModal (Popup S over the form): the «everything
 * checked?» window — warning «изменить вердикт после отправки
 * нельзя», all entered values, «Вернуться к правке» and «Да,
 * отправить». The POST is guarded by `submitting`, so a double click
 * sends a single request. Field codes bounce back to the composer;
 * ORDER_VERDICT_EXISTS / ORDER_VERDICT_FORBIDDEN close the composer,
 * show the server's message and land on the reloaded detail window;
 * network and unknown errors stay here with a retry.
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

import { ApiError } from '../../shared/api-client';
import { errorText } from '../../shared/errorTexts';
import { useFormDraft } from '../../shared/formDraft';
import { FONTS, Popup, RADII, tokenVar } from '../../shared/ui';
import { useSession } from '../00_core/hooks/useAuth';
import { ordersApi } from './api';
import { useOrderRules } from './hooks/useOrderRules';
import { ConfirmRecap } from './ConfirmSubmitModal';
import { orderFieldForCode } from './OrderComposer';
import { ORDERS_TEXTS } from './texts';
import { OrderErrorCodes, type OrderRulesDTO } from './types';
import {
  useOrdersUi,
  verdictDraftKey,
  type ComposerServerError,
  type OrderDraft,
} from './OrdersUiProvider';

type VerdictField = 'title' | 'summary' | 'articleUrl';

/** What the live form reports up — feeds the Popup's dirty and footer. */
interface VerdictLive {
  dirty: boolean;
  canSend: boolean;
  draft: OrderDraft;
}

const EMPTY_LIVE: VerdictLive = {
  dirty: false,
  canSend: false,
  draft: { title: '', summary: '', articleUrl: '' },
};

export function VerdictComposer() {
  const {
    orderWindow,
    toVerdictConfirm,
    closeWindow,
  } = useOrdersUi();
  const [live, setLive] = useState<VerdictLive>(EMPTY_LIVE);

  const win =
    orderWindow?.view === 'verdict-composer' ||
    orderWindow?.view === 'verdict-confirm'
      ? orderWindow
      : null;
  if (win === null) {
    return null;
  }
  const serverError = win.view === 'verdict-composer' ? win.error : null;

  return (
    <Popup
      size="M"
      icon="scales"
      title={ORDERS_TEXTS.verdictComposerTitle(win.number)}
      onClose={closeWindow}
      dirty={live.dirty}
      testId="popup-verdict-composer"
      footer={
        <>
          <Button size="m" mode="secondary" onClick={closeWindow}>
            {ORDERS_TEXTS.cancel}
          </Button>
          <Button
            size="m"
            mode="primary"
            disabled={!live.canSend}
            onClick={() => toVerdictConfirm(live.draft)}
          >
            {ORDERS_TEXTS.verdictSendButton}
          </Button>
        </>
      }
    >
      <VerdictForm
        draftKey={verdictDraftKey(win.number)}
        draft={win.draft}
        serverError={serverError}
        onLive={setLive}
      />
    </Popup>
  );
}

function fieldCounter(
  rules: OrderRulesDTO | null,
  field: VerdictField,
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

function VerdictForm({
  draftKey,
  draft,
  serverError,
  onLive,
}: {
  /** formDraft key — verdict drafts are per form AND per order number. */
  draftKey: string;
  draft: OrderDraft;
  serverError: ComposerServerError | null;
  onLive: (live: VerdictLive) => void;
}) {
  const rulesState = useOrderRules();
  const rules = rulesState.status === 'ready' ? rulesState.rules : null;

  // Draft memory, keyed by this order — see OrderComposer.
  const {
    draft: storedDraft,
    setDraft: setStoredDraft,
    clearDraft,
  } = useFormDraft<OrderDraft>(draftKey);
  const initial = storedDraft ?? draft;

  const [title, setTitle] = useState(initial.title);
  const [summary, setSummary] = useState(initial.summary);
  const [articleUrl, setArticleUrl] = useState(initial.articleUrl);

  useEffect(() => {
    if (title === '' && summary === '' && articleUrl === '') {
      clearDraft();
    } else {
      setStoredDraft({ title, summary, articleUrl });
    }
  }, [title, summary, articleUrl, setStoredDraft, clearDraft]);

  const [fieldErrors, setFieldErrors] = useState<
    Partial<Record<VerdictField, string>>
  >(() => {
    const field = serverError ? orderFieldForCode(serverError.code) : null;
    return field && serverError ? { [field]: serverError.message } : {};
  });
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

  const filled =
    title.trim().length > 0 &&
    summary.trim().length > 0 &&
    articleUrl.trim().length > 0;

  useEffect(() => {
    onLive({
      dirty: title !== '' || summary !== '' || articleUrl !== '',
      canSend: filled,
      draft: { title, summary, articleUrl },
    });
  }, [title, summary, articleUrl, filled, onLive]);

  const clearFieldError = (field: VerdictField) =>
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
        <FormStatus mode="error" title={ORDERS_TEXTS.verdictSubmitErrorTitle}>
          {formError}
        </FormStatus>
      )}

      <FormItem
        top={ORDERS_TEXTS.fieldTitle}
        htmlFor="verdict-title"
        status={fieldErrors.title ? 'error' : 'default'}
        bottom={fieldErrors.title ?? fieldCounter(rules, 'title', title.length)}
        data-testid="form-item-verdict-title"
      >
        <Input
          id="verdict-title"
          value={title}
          maxLength={rules?.title_max_length}
          onChange={(e) => {
            setTitle(e.currentTarget.value);
            clearFieldError('title');
          }}
        />
      </FormItem>

      <FormItem
        top={ORDERS_TEXTS.verdictFieldSummary}
        htmlFor="verdict-summary"
        status={fieldErrors.summary ? 'error' : 'default'}
        bottom={
          fieldErrors.summary ?? fieldCounter(rules, 'summary', summary.length)
        }
        data-testid="form-item-verdict-summary"
      >
        <Textarea
          id="verdict-summary"
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
        htmlFor="verdict-url"
        status={fieldErrors.articleUrl ? 'error' : 'default'}
        bottom={
          fieldErrors.articleUrl ??
          fieldCounter(rules, 'articleUrl', articleUrl.length)
        }
        data-testid="form-item-verdict-url"
      >
        <Input
          id="verdict-url"
          value={articleUrl}
          maxLength={rules?.url_max_length}
          placeholder="https://vk.com/@..."
          onChange={(e) => {
            setArticleUrl(e.currentTarget.value);
            clearFieldError('articleUrl');
          }}
        />
      </FormItem>

      <div
        aria-disabled="true"
        data-testid="verdict-effects-block"
        style={{
          opacity: 0.55,
          pointerEvents: 'none',
          userSelect: 'none',
          border: `1px dashed ${tokenVar('ink-faint')}`,
          borderRadius: RADII['radius-md'],
          padding: '10px 12px',
        }}
      >
        <div
          style={{
            fontFamily: FONTS.heading,
            fontWeight: 500,
            fontSize: 12,
            lineHeight: '16px',
            letterSpacing: '.06em',
            textTransform: 'uppercase',
          }}
        >
          {ORDERS_TEXTS.effectsBlockTitle}
        </div>
        <div
          style={{
            color: tokenVar('ink-muted'),
            fontSize: 12,
            lineHeight: '16px',
            marginTop: 2,
          }}
        >
          {ORDERS_TEXTS.effectsBlockHint}
        </div>
      </div>
    </>
  );
}

export function ConfirmVerdictModal() {
  const { token } = useSession();
  const {
    orderWindow,
    backToVerdictComposer,
    notifyVerdictSubmitted,
    verdictRejected,
  } = useOrdersUi();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const win =
    orderWindow?.view === 'verdict-confirm' ? orderWindow : null;
  if (win === null) {
    return null;
  }
  const draft = win.draft;

  const handleConfirm = async () => {
    if (submitting) {
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const order = await ordersApi.submitVerdict(token, win.number, {
        title: draft.title,
        summary: draft.summary,
        article_url: draft.articleUrl,
      });
      notifyVerdictSubmitted(order.number);
    } catch (e) {
      if (e instanceof ApiError && orderFieldForCode(e.code) !== null) {
        // Field errors land back on the composer at their field; the
        // carried message is already the Russian `errorText`.
        backToVerdictComposer({ code: e.code, message: errorText(e) });
        return;
      }
      if (
        e instanceof ApiError &&
        (e.code === OrderErrorCodes.ORDER_VERDICT_EXISTS ||
          e.code === OrderErrorCodes.ORDER_VERDICT_FORBIDDEN)
      ) {
        // The verdict is recorded or the caller is not the judge —
        // the composer closes and the detail window reloads.
        verdictRejected(win.number, errorText(e));
        return;
      }
      setError(errorText(e));
    } finally {
      // The component stays mounted under the composer view, so the
      // flag must be released on every settled request or the next
      // «Да, отправить» freezes spinning.
      setSubmitting(false);
    }
  };

  const back = () => backToVerdictComposer(null);

  return (
    <Popup
      size="S"
      icon="scales"
      title={ORDERS_TEXTS.verdictConfirmTitle}
      onClose={back}
      testId="popup-verdict-confirm"
      footer={
        <>
          <Button
            size="m"
            mode="secondary"
            disabled={submitting}
            onClick={back}
          >
            {ORDERS_TEXTS.backToEdit}
          </Button>
          <Button
            size="m"
            mode="primary"
            loading={submitting}
            onClick={() => void handleConfirm()}
          >
            {ORDERS_TEXTS.confirmSend}
          </Button>
        </>
      }
    >
      <Text style={{ color: tokenVar('ink-muted') }}>
        {ORDERS_TEXTS.verdictConfirmWarning}
      </Text>
      <ConfirmRecap draft={draft} />
      {error !== null && (
        <FormStatus mode="error" title={ORDERS_TEXTS.verdictSubmitErrorTitle}>
          {error}
        </FormStatus>
      )}
    </Popup>
  );
}
