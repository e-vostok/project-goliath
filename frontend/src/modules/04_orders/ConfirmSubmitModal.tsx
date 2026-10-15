/**
 * ConfirmSubmitModal — the «everything checked?» window (Spec 5.4).
 *
 * Warning «изменить приказ после подачи нельзя», all entered values in
 * full, a plain «Открыть ссылку» link and the two buttons. The POST
 * fires only on «Да, отправить», guarded by `submitting` so a double
 * click sends a single request; `client_request_id` makes a server
 * repeat idempotent anyway. Coded domain errors bounce back to the
 * composer (field codes at their field, nation/limit as a banner);
 * network and unknown errors stay here with a retry.
 */

import { useState } from 'react';
import {
  Button,
  ButtonGroup,
  FormStatus,
  Link,
  ModalCard,
  Text,
  type NavIdProps,
} from '@vkontakte/vkui';

import { ApiError } from '../../shared/api-client';
import { useSession } from '../00_core/hooks/useAuth';
import { ordersApi } from './api';
import { ORDERS_TEXTS } from './texts';
import { useOrdersUi } from './OrdersUiProvider';

export function ConfirmSubmitModal({ id, ...navIdProps }: NavIdProps) {
  const { token } = useSession();
  const { orderWindow, backToComposer, closeWindow, notifySubmitted } =
    useOrdersUi();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const win = orderWindow?.view === 'confirm' ? orderWindow : null;
  const draft = win?.draft ?? { title: '', summary: '', articleUrl: '' };

  const handleConfirm = async () => {
    if (submitting || win === null) {
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
        // highlight their field, nation/limit show as a banner (the
        // remounted composer refetches the counter, Spec 5.4).
        backToComposer({ code: e.code, message: e.message });
        return;
      }
      setError(
        e instanceof ApiError ? e.message : ORDERS_TEXTS.networkError,
      );
      setSubmitting(false);
    }
  };

  return (
    <ModalCard
      id={id}
      {...navIdProps}
      onClose={closeWindow}
      title={ORDERS_TEXTS.confirmTitle}
      description={ORDERS_TEXTS.confirmWarning}
      actions={
        <ButtonGroup stretched mode="vertical" gap="m">
          <Button
            size="l"
            stretched
            mode="secondary"
            disabled={submitting}
            onClick={() => backToComposer(null)}
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
        <FormStatus mode="error" title={ORDERS_TEXTS.submitErrorTitle}>
          {error}
        </FormStatus>
      )}
    </ModalCard>
  );
}
