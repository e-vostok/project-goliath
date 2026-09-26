/**
 * ModalConfirmDeleteNation — destructive-action guard for DELETE /nations/me.
 *
 * Explicit "cannot be undone" copy; the DELETE with `{ confirm: true }` fires
 * ONLY when the confirm button is clicked — never on open or on dismiss.
 */

import { useState } from 'react';
import bridge from '@vkontakte/vk-bridge';
import {
  Button,
  ButtonGroup,
  FormStatus,
  ModalCard,
  type NavIdProps,
} from '@vkontakte/vkui';

import { api, ApiError } from '../../../shared/api-client';
import { useSession } from '../hooks/useAuth';

export interface ModalConfirmDeleteNationProps extends NavIdProps {
  nationName: string;
  onClose: () => void;
  onDeleted: () => void;
}

export function ModalConfirmDeleteNation({
  nationName,
  onClose,
  onDeleted,
  ...navIdProps
}: ModalConfirmDeleteNationProps) {
  const { token } = useSession();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleConfirm = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await api.deleteNation(token);
      void bridge
        .send('VKWebAppTapticImpactOccurred', { style: 'heavy' })
        .catch(() => {});
      onDeleted();
    } catch (e) {
      setError(
        e instanceof ApiError
          ? e.message
          : 'Network error — please try again.',
      );
      setSubmitting(false);
    }
  };

  return (
    <ModalCard
      {...navIdProps}
      onClose={onClose}
      title="Delete nation?"
      description={
        <>
          This cannot be undone. {nationName} will be permanently deleted; its
          name and color become available again, and all its provinces return
          to the free pool.
        </>
      }
      actions={
        <ButtonGroup stretched mode="vertical" gap="m">
          <Button
            size="l"
            stretched
            mode="primary"
            appearance="negative"
            loading={submitting}
            onClick={() => void handleConfirm()}
          >
            Delete permanently
          </Button>
          <Button
            size="l"
            stretched
            mode="secondary"
            disabled={submitting}
            onClick={onClose}
          >
            Cancel
          </Button>
        </ButtonGroup>
      }
    >
      {error && (
        <FormStatus mode="error" title="Could not delete nation">
          {error}
        </FormStatus>
      )}
    </ModalCard>
  );
}
