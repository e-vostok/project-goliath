/**
 * DescriptionBlock — «Описание» on the nation card (UI Spec 9.1,
 * mockup «Main»): the description text and, when `history_url` is
 * set, the small «История государства ↗» link at the end. The link
 * becomes a real <a target="_blank" rel="noopener noreferrer"> only
 * for an https:// value — anything else is plain text (defense in
 * depth; the server remains the validator). The whole block hides
 * when the description is empty and no history link exists.
 */

import { Link } from '@vkontakte/vkui';

import type { NationDTO } from '../../../../shared/types';
import {
  BlockTitle,
  SPACING,
  TEXT_STYLES,
  tokenVar,
} from '../../../../shared/ui';
import { CardBlock } from './CardBlock';

export function DescriptionBlock({ nation }: { nation: NationDTO }) {
  const description = nation.description;
  const historyUrl = nation.history_url;
  if (!description && !historyUrl) {
    return null;
  }

  return (
    <CardBlock testId="nation-description-block">
      <BlockTitle icon="text" title="Описание" />
      {description && (
        <div
          style={{
            ...TEXT_STYLES['body'],
            color: tokenVar('ink'),
            whiteSpace: 'pre-wrap',
          }}
        >
          {description}
        </div>
      )}
      {historyUrl && (
        <div
          style={{
            marginTop: description ? SPACING['space-3'] : 0,
            ...TEXT_STYLES['caption'],
          }}
        >
          {historyUrl.startsWith('https://') ? (
            <Link
              href={historyUrl}
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: tokenVar('link') }}
            >
              История государства ↗
            </Link>
          ) : (
            <span style={{ color: tokenVar('ink-muted') }}>{historyUrl}</span>
          )}
        </div>
      )}
    </CardBlock>
  );
}
