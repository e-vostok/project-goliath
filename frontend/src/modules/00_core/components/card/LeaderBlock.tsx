/**
 * LeaderBlock — «Глава государства» on the nation card (UI Spec 9.1,
 * mockup «Main»): portrait 72×88 (`PortraitStub` for a legacy nation
 * without one), the leader name in `heading`, the title as a
 * `signal-ink` `label` (hidden when empty) and the biography as plain
 * text with its line breaks kept — no row captions anywhere.
 */

import type { NationDTO, NationPublicDTO } from '../../../../shared/types';
import {
  BlockTitle,
  PortraitStub,
  RADII,
  SPACING,
  TEXT_STYLES,
  tokenVar,
} from '../../../../shared/ui';
import { CardBlock } from './CardBlock';

export function LeaderBlock({
  nation,
}: {
  nation: NationDTO | NationPublicDTO;
}) {
  return (
    <CardBlock testId="nation-leader-block">
      <BlockTitle icon="person" title="Глава государства" />
      <div style={{ display: 'flex', gap: SPACING['space-4'] }}>
        {nation.portrait_url ? (
          <img
            src={nation.portrait_url}
            alt={`Портрет лидера ${nation.name}`}
            width={72}
            height={88}
            style={{
              borderRadius: RADII['radius-md'],
              objectFit: 'cover',
              flexShrink: 0,
              display: 'block',
            }}
          />
        ) : (
          <PortraitStub variant="block" />
        )}
        <div style={{ minWidth: 0 }}>
          <div
            style={{ ...TEXT_STYLES['heading'], color: tokenVar('ink') }}
          >
            {nation.leader_name || 'не указано'}
          </div>
          {nation.leader_title && (
            <div
              style={{
                ...TEXT_STYLES['label'],
                color: tokenVar('signal-ink'),
                marginTop: 4,
              }}
            >
              {nation.leader_title}
            </div>
          )}
        </div>
      </div>
      {nation.leader_bio && (
        <div
          style={{
            ...TEXT_STYLES['body'],
            color: tokenVar('ink'),
            whiteSpace: 'pre-wrap',
            marginTop: SPACING['space-3'],
          }}
        >
          {nation.leader_bio}
        </div>
      )}
    </CardBlock>
  );
}
