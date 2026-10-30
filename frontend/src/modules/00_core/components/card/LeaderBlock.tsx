/**
 * LeaderBlock — «Глава государства» on the nation card (UI Spec 9.1,
 * mockup «Main», 0.12.0 board 14): portrait 72×96 (`PortraitStub`
 * when the nation has no uploaded one), the leader name in `heading`, the title as a
 * `signal-ink` `label` (hidden when empty) and the biography as plain
 * text with its line breaks kept — no row captions anywhere.
 */

import type { NationDTO, NationPublicDTO } from '../../../../shared/types';
import {
  BlockTitle,
  ImageSlot,
  SPACING,
  TEXT_STYLES,
  tokenVar,
} from '../../../../shared/ui';
import {
  imageSlotHint,
  type NationImageEditor,
} from '../imageEditor';
import { CardBlock } from './CardBlock';

export function LeaderBlock({
  nation,
  imageEditor,
}: {
  nation: NationDTO | NationPublicDTO;
  /**
   * Present on the own «Штаб» card only: the portrait becomes an
   * upload control. Absent (Registry subscreen) — read-only.
   */
  imageEditor?: NationImageEditor;
}) {
  return (
    <CardBlock testId="nation-leader-block">
      <BlockTitle icon="person" title="Глава государства" />
      <div style={{ display: 'flex', gap: SPACING['space-4'] }}>
        <ImageSlot
          kind="portrait"
          size="shtab"
          src={nation.portrait_url}
          alt={`Портрет лидера ${nation.name}`}
          interactive={imageEditor !== undefined}
          hintLines={
            imageEditor !== undefined
              ? imageSlotHint(
                  'portrait',
                  nation.portrait_url !== null,
                  imageEditor.rules,
                )
              : undefined
          }
          onPick={
            imageEditor !== undefined
              ? (file) => imageEditor.onUpload('portrait', file)
              : undefined
          }
        />
        <div style={{ minWidth: 0 }}>
          {/* PNG 08 — leader name 20/24, title small caps in signal-ink,
              bio right under the title inside the same column. */}
          <div
            style={{
              ...TEXT_STYLES['heading'],
              fontSize: 20,
              lineHeight: '24px',
              color: tokenVar('ink'),
            }}
          >
            {nation.leader_name || 'не указано'}
          </div>
          {nation.leader_title && (
            <div
              style={{
                ...TEXT_STYLES['label'],
                fontSize: 12,
                lineHeight: '16px',
                letterSpacing: '.08em',
                color: tokenVar('signal-ink'),
                margin: '2px 0 6px',
              }}
            >
              {nation.leader_title}
            </div>
          )}
          {nation.leader_bio && (
            <p
              style={{
                margin: 0,
                ...TEXT_STYLES['body'],
                color: tokenVar('ink'),
                whiteSpace: 'pre-wrap',
              }}
            >
              {nation.leader_bio}
            </p>
          )}
        </div>
      </div>
    </CardBlock>
  );
}
