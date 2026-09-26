/**
 * PanelNationHome — the player's existing nation.
 *
 * Group with a Header showing turn number + game date (GET /game-clock),
 * SimpleCell rows for name / color swatch / province IDs, plus edit
 * (PATCH /nations/me) and destructive delete buttons.
 */

import { useEffect, useState } from 'react';
import {
  Button,
  ButtonGroup,
  Div,
  FormItem,
  FormStatus,
  Group,
  Header,
  Input,
  PanelHeader,
  SimpleCell,
} from '@vkontakte/vkui';
import { Icon24Write, Icon24Delete } from '@vkontakte/icons';

import { api, ApiError } from '../../../shared/api-client';
import type { GameClockDTO, NationDTO } from '../../../shared/types';
import { useSession } from '../hooks/useAuth';
import { mapErrorCodeToField } from './PanelCreateNation';

export interface PanelNationHomeProps {
  nation: NationDTO;
  onChanged: () => void;
  onDeleteRequest: () => void;
}

export function PanelNationHome({
  nation,
  onChanged,
  onDeleteRequest,
}: PanelNationHomeProps) {
  const { token } = useSession();

  const [clock, setClock] = useState<GameClockDTO | null>(null);
  const [editing, setEditing] = useState(false);
  const [editName, setEditName] = useState(nation.name);
  const [editColor, setEditColor] = useState(nation.color_hex);
  const [submitting, setSubmitting] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<
    Partial<Record<'name' | 'color', string>>
  >({});
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    api
      .getGameClock(token, controller.signal)
      .then(setClock)
      .catch(() => {});
    return () => controller.abort();
  }, [token]);

  const handleSave = async () => {
    setSubmitting(true);
    setFieldErrors({});
    setFormError(null);
    try {
      await api.updateNation(token, {
        name: editName.trim(),
        color_hex: editColor,
      });
      setEditing(false);
      onChanged();
    } catch (error) {
      if (error instanceof ApiError) {
        const field = mapErrorCodeToField(error.code);
        if (field === 'name' || field === 'color') {
          setFieldErrors({ [field]: error.message });
        } else {
          setFormError(error.message);
        }
      } else {
        setFormError('Network error — please try again.');
      }
    } finally {
      setSubmitting(false);
    }
  };

  const headerText = clock
    ? `Turn ${clock.current_turn} · ${clock.game_date}`
    : 'Your nation';

  return (
    <>
      <PanelHeader>{nation.name}</PanelHeader>
      <Group header={<Header size="l">{headerText}</Header>}>
        <SimpleCell disabled subtitle="Name">
          {nation.name}
        </SimpleCell>
        <SimpleCell
          disabled
          subtitle="Color"
          before={
            <div
              aria-label={`Color ${nation.color_hex}`}
              style={{
                width: 24,
                height: 24,
                borderRadius: 6,
                background: nation.color_hex,
                border: '1px solid rgba(0,0,0,0.15)',
              }}
            />
          }
        >
          {nation.color_hex}
        </SimpleCell>
        <SimpleCell disabled subtitle="Provinces">
          {nation.province_ids.length > 0
            ? nation.province_ids.join(', ')
            : 'None'}
        </SimpleCell>

        {formError && (
          <FormStatus mode="error" title="Could not update nation">
            {formError}
          </FormStatus>
        )}

        {editing ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void handleSave();
            }}
          >
            <FormItem
              top="Nation name"
              htmlFor="edit-nation-name"
              status={fieldErrors.name ? 'error' : 'default'}
              bottom={fieldErrors.name}
            >
              <Input
                id="edit-nation-name"
                value={editName}
                onChange={(e) => setEditName(e.currentTarget.value)}
              />
            </FormItem>
            <FormItem
              top="Nation color"
              htmlFor="edit-nation-color"
              status={fieldErrors.color ? 'error' : 'default'}
              bottom={fieldErrors.color}
            >
              <input
                id="edit-nation-color"
                type="color"
                value={editColor}
                onChange={(e) => setEditColor(e.currentTarget.value)}
                style={{
                  width: '100%',
                  height: 36,
                  padding: 0,
                  border: 'none',
                  background: 'none',
                  cursor: 'pointer',
                }}
              />
            </FormItem>
            <Div>
              <ButtonGroup stretched>
                <Button
                  type="submit"
                  size="l"
                  stretched
                  loading={submitting}
                  disabled={editName.trim().length < 3}
                >
                  Save
                </Button>
                <Button
                  type="button"
                  size="l"
                  stretched
                  mode="secondary"
                  disabled={submitting}
                  onClick={() => {
                    setEditing(false);
                    setEditName(nation.name);
                    setEditColor(nation.color_hex);
                    setFieldErrors({});
                    setFormError(null);
                  }}
                >
                  Cancel
                </Button>
              </ButtonGroup>
            </Div>
          </form>
        ) : (
          <Div>
            <ButtonGroup stretched>
              <Button
                size="l"
                stretched
                mode="secondary"
                before={<Icon24Write />}
                onClick={() => setEditing(true)}
              >
                Edit
              </Button>
              <Button
                size="l"
                stretched
                mode="primary"
                appearance="negative"
                before={<Icon24Delete />}
                onClick={onDeleteRequest}
              >
                Delete
              </Button>
            </ButtonGroup>
          </Div>
        )}
      </Group>
    </>
  );
}
