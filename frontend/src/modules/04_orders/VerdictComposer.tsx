/**
 * VerdictComposer + ConfirmVerdictModal — the judge's verdict windows
 * (Spec 5.4), mirroring the order submission pair.
 *
 * VerdictComposer: three fields with the same per-field counters and
 * limits from GET /orders/rules as the order composer (the server
 * stays the source of truth); under the fields sits the disabled
 * «Изменение показателей и модификаторы» block — verdict effects do
 * not exist in v1 (INV-O13). «Отправить вердикт» leads to the
 * confirmation window. Errors bounced back from the submit land at
 * their field here.
 *
 * ConfirmVerdictModal: the «everything checked?» window — warning
 * «изменить вердикт после отправки нельзя», all entered values,
 * «Открыть ссылку», «Вернуться к правке» and «Да, отправить». The
 * POST is guarded by `submitting`, so a double click sends a single
 * request. Field codes bounce back to the composer;
 * ORDER_VERDICT_EXISTS / ORDER_VERDICT_FORBIDDEN close the composer,
 * show the server's message and land on the reloaded detail window;
 * network and unknown errors stay here with a retry.
 */

import { useEffect, useState } from 'react';
import {
  Button,
  ButtonGroup,
  Div,
  FormItem,
  FormStatus,
  Input,
  Link,
  ModalCard,
  ModalPage,
  ModalPageHeader,
  Text,
  Textarea,
  type NavIdProps,
} from '@vkontakte/vkui';

import { ApiError } from '../../shared/api-client';
import { useFormDraft } from '../../shared/formDraft';
import { useSession } from '../00_core/hooks/useAuth';
import { ordersApi } from './api';
import { useOrderRules } from './hooks/useOrderRules';
import { orderFieldForCode } from './OrderComposer';
import { ORDERS_TEXTS } from './texts';
import { OrderErrorCodes, type OrderRulesDTO } from './types';
import {
  useOrdersUi,
  verdictDraftKey,
  type ComposerServerError,
  type OrderDraft,
} from './OrdersUiProvider';

/** Fits inside the 910 px window budget like every other window. */
const MODAL_SIZE = 'min(880px, calc(100vw - 64px))';

type VerdictField = 'title' | 'summary' | 'articleUrl';

export function VerdictComposer({ id, ...navIdProps }: NavIdProps) {
  const { orderWindow, toVerdictConfirm, closeWindow } = useOrdersUi();
  const win =
    orderWindow?.view === 'verdict-composer' ? orderWindow : null;

  return (
    <ModalPage
      id={id}
      {...navIdProps}
      onClose={closeWindow}
      size={MODAL_SIZE}
      header={
        <ModalPageHeader>
          {win !== null ? ORDERS_TEXTS.verdictComposerTitle(win.number) : ''}
        </ModalPageHeader>
      }
    >
      {win !== null && (
        <VerdictForm
          draftKey={verdictDraftKey(win.number)}
          draft={win.draft}
          serverError={win.error}
          onSend={toVerdictConfirm}
        />
      )}
    </ModalPage>
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
  onSend,
}: {
  /** formDraft key — verdict drafts are per form AND per order number. */
  draftKey: string;
  draft: OrderDraft;
  serverError: ComposerServerError | null;
  onSend: (draft: OrderDraft) => void;
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
  const [formError] = useState<string | null>(() =>
    serverError !== null && orderFieldForCode(serverError.code) === null
      ? serverError.message
      : null,
  );

  const filled =
    title.trim().length > 0 &&
    summary.trim().length > 0 &&
    articleUrl.trim().length > 0;

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
    <Div>
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
          marginTop: 8,
          marginBottom: 12,
          opacity: 0.55,
          pointerEvents: 'none',
          userSelect: 'none',
        }}
      >
        <Text weight="2" style={{ display: 'block' }}>
          {ORDERS_TEXTS.effectsBlockTitle}
        </Text>
        <Text style={{ display: 'block', marginTop: 4 }}>
          {ORDERS_TEXTS.effectsBlockHint}
        </Text>
      </div>

      <Button
        size="l"
        stretched
        disabled={!filled}
        onClick={() => onSend({ title, summary, articleUrl })}
      >
        {ORDERS_TEXTS.verdictSendButton}
      </Button>
    </Div>
  );
}

export function ConfirmVerdictModal({ id, ...navIdProps }: NavIdProps) {
  const { token } = useSession();
  const {
    orderWindow,
    backToVerdictComposer,
    closeWindow,
    notifyVerdictSubmitted,
    verdictRejected,
  } = useOrdersUi();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const win = orderWindow?.view === 'verdict-confirm' ? orderWindow : null;
  const draft = win?.draft ?? { title: '', summary: '', articleUrl: '' };

  const handleConfirm = async () => {
    if (submitting || win === null) {
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
        // Field errors land back on the composer at their field.
        backToVerdictComposer({ code: e.code, message: e.message });
        return;
      }
      if (
        e instanceof ApiError &&
        (e.code === OrderErrorCodes.ORDER_VERDICT_EXISTS ||
          e.code === OrderErrorCodes.ORDER_VERDICT_FORBIDDEN)
      ) {
        // The verdict is recorded or the caller is not the judge —
        // the composer closes and the detail window reloads.
        verdictRejected(win.number, e.message);
        return;
      }
      setError(
        e instanceof ApiError ? e.message : ORDERS_TEXTS.networkError,
      );
    } finally {
      // This component never unmounts (it is a permanent child of the
      // ModalRoot — only VKUI's inner card hides), so the flag must be
      // released on every settled request or the next window freezes.
      setSubmitting(false);
    }
  };

  return (
    <ModalCard
      id={id}
      {...navIdProps}
      onClose={closeWindow}
      title={ORDERS_TEXTS.verdictConfirmTitle}
      description={ORDERS_TEXTS.verdictConfirmWarning}
      actions={
        <ButtonGroup stretched mode="vertical" gap="m">
          <Button
            size="l"
            stretched
            mode="secondary"
            disabled={submitting}
            onClick={() => backToVerdictComposer(null)}
          >
            {ORDERS_TEXTS.backToEdit}
          </Button>
          <Button
            size="l"
            stretched
            mode="primary"
            loading={submitting}
            onClick={() => void handleConfirm()}
          >
            {ORDERS_TEXTS.confirmSend}
          </Button>
        </ButtonGroup>
      }
    >
      <div style={{ overflowWrap: 'break-word', minWidth: 0 }}>
        <Text weight="2">{ORDERS_TEXTS.confirmTitleLabel}</Text>
        <Text>{draft.title}</Text>
        <Text weight="2" style={{ marginTop: 8 }}>
          {ORDERS_TEXTS.confirmSummaryLabel}
        </Text>
        <Text style={{ whiteSpace: 'pre-wrap' }}>{draft.summary}</Text>
        <Text weight="2" style={{ marginTop: 8 }}>
          {ORDERS_TEXTS.confirmUrlLabel}
        </Text>
        <Text style={{ overflowWrap: 'anywhere' }}>{draft.articleUrl}</Text>
        {draft.articleUrl.startsWith('https://') && (
          <div style={{ marginTop: 4 }}>
            <Link
              href={draft.articleUrl}
              target="_blank"
              rel="noopener noreferrer"
            >
              {ORDERS_TEXTS.openLink}
            </Link>
          </div>
        )}
      </div>
      {error !== null && (
        <FormStatus mode="error" title={ORDERS_TEXTS.verdictSubmitErrorTitle}>
          {error}
        </FormStatus>
      )}
    </ModalCard>
  );
}
