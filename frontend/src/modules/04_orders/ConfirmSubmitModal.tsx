/**
 * ConfirmSubmitModal — the «everything checked?» window (Spec 5.4):
 * a Popup S lying ON TOP of the composer, which stays mounted
 * underneath with its input intact.
 *
 * Warning «изменить приказ после подачи нельзя», all entered values
 * in a recap box and the two buttons. The POST fires only on «Да,
 * отправить», guarded by `submitting` so a double click sends a
 * single request; `client_request_id` makes a server repeat
 * idempotent anyway. Coded domain errors bounce back to the composer
 * (field codes at their field, nation/limit as a banner); network
 * and unknown errors stay here with a retry. Esc, the scrim and the
 * «×» all go back to the composer, like «Вернуться к правке».
 */

import { useState } from 'react';
import { Button, FormStatus, Link, Text } from '@vkontakte/vkui';

import { ApiError } from '../../shared/api-client';
import { Popup, RADII, tokenVar } from '../../shared/ui';
import { useSession } from '../00_core/hooks/useAuth';
import { ordersApi } from './api';
import { ORDERS_TEXTS } from './texts';
import { useOrdersUi, type OrderDraft } from './OrdersUiProvider';

/** The recap box of the confirmation windows (mockup_Confirm.html). */
export function ConfirmRecap({ draft }: { draft: OrderDraft }) {
  return (
    <div
      style={{
        background: tokenVar('surface'),
        border: `1px solid ${tokenVar('line')}`,
        borderRadius: RADII['radius-md'],
        padding: 12,
        display: 'grid',
        gridTemplateColumns: '100px minmax(0,1fr)',
        rowGap: 8,
        columnGap: 12,
      }}
    >
      <span style={{ color: tokenVar('ink-muted') }}>
        {ORDERS_TEXTS.confirmTitleLabel}
      </span>
      <span style={{ overflowWrap: 'break-word', minWidth: 0 }}>
        {draft.title}
      </span>
      <span style={{ color: tokenVar('ink-muted') }}>
        {ORDERS_TEXTS.confirmSummaryLabel}
      </span>
      <span
        style={{
          whiteSpace: 'pre-wrap',
          overflowWrap: 'break-word',
          minWidth: 0,
        }}
      >
        {draft.summary}
      </span>
      <span style={{ color: tokenVar('ink-muted') }}>
        {ORDERS_TEXTS.confirmUrlLabel}
      </span>
      <span style={{ overflowWrap: 'anywhere', minWidth: 0 }}>
        {draft.articleUrl.startsWith('https://') ? (
          <Link
            href={draft.articleUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            {draft.articleUrl}
          </Link>
        ) : (
          draft.articleUrl
        )}
      </span>
    </div>
  );
}

export function ConfirmSubmitModal() {
  const { token } = useSession();
  const { orderWindow, backToComposer, notifySubmitted } = useOrdersUi();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const win = orderWindow?.view === 'confirm' ? orderWindow : null;
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
      const order = await ordersApi.submitOrder(token, {
        title: draft.title,
        summary: draft.summary,
        article_url: draft.articleUrl,
        client_request_id: win.requestId,
      });
      notifySubmitted(order.number);
    } catch (e) {
      if (e instanceof ApiError && e.code.startsWith('ORDER_')) {
        // Coded domain errors land back on the composer — field codes
        // highlight their field, nation/limit show as a banner.
        backToComposer({ code: e.code, message: e.message });
        return;
      }
      setError(
        e instanceof ApiError ? e.message : ORDERS_TEXTS.networkError,
      );
    } finally {
      // The component stays mounted under the composer view, so the
      // flag must be released on every settled request or the next
      // «Да, отправить» freezes spinning.
      setSubmitting(false);
    }
  };

  const back = () => backToComposer(null);

  return (
    <Popup
      size="S"
      icon="document"
      title={ORDERS_TEXTS.confirmTitle}
      onClose={back}
      testId="popup-order-confirm"
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
        {ORDERS_TEXTS.confirmWarning}
      </Text>
      <ConfirmRecap draft={draft} />
      {error !== null && (
        <FormStatus mode="error" title={ORDERS_TEXTS.submitErrorTitle}>
          {error}
        </FormStatus>
      )}
    </Popup>
  );
}
