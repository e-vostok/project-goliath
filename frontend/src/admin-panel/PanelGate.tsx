/**
 * Panel gate screens (0.11.0 unit 5a) — approved mockup
 * docs/06_DESIGN/0.11.0 screen 09 «Ссылка устарела / Нет доступа».
 *
 * Everything the page can show before or instead of the panel frame:
 * the minimal top bar (logo, wordmark, «Пульт») plus ONE centred
 * status card — never several. The mockup shows the two cards side by
 * side only to approve both looks.
 */

import type { ReactNode } from 'react';

import {
  RADII,
  SIZES,
  TEXT_STYLES,
  tokenVar,
} from '../shared/ui/tokens';
import type { GateIconName } from './panelIcons';
import { GateIcon } from './panelIcons';
import { PanelBrand } from './PanelBrand';

export type GateCardKind =
  | 'link-stale'
  | 'no-access'
  | 'network'
  | 'session-ended'
  | 'logged-out';

interface GateCardText {
  icon: GateIconName;
  title: string;
  text: string;
  hint?: string;
}

const HINT_CLOSE_TAB = 'Закройте эту вкладку после перехода в игру.';

const GATE_CARDS: Record<GateCardKind, GateCardText> = {
  'link-stale': {
    icon: 'lock',
    title: 'Ссылка устарела',
    text:
      'Из соображений безопасности ссылка на панель живёт недолго и ' +
      'работает один раз. Вернитесь в игру и нажмите кнопку панели ' +
      'в «Штабе» ещё раз.',
    hint: HINT_CLOSE_TAB,
  },
  'no-access': {
    icon: 'shield',
    title: 'Нет доступа',
    text:
      'У вашего аккаунта нет прав администратора. Если вы считаете, ' +
      'что права должны быть, обратитесь к владельцу игры.',
  },
  network: {
    icon: 'offline',
    title: 'Нет связи с сервером',
    text:
      'Не удалось связаться с сервером. Вернитесь в игру и откройте ' +
      'панель ещё раз.',
    hint: HINT_CLOSE_TAB,
  },
  'session-ended': {
    icon: 'clock',
    title: 'Сеанс закончился',
    text:
      'Сеанс панели короткий и уже закончился. Вернитесь в игру и ' +
      'нажмите кнопку панели в «Штабе» ещё раз.',
    hint: HINT_CLOSE_TAB,
  },
  'logged-out': {
    icon: 'logout',
    title: 'Вы вышли из панели',
    text:
      'Сеанс закрыт на этом устройстве. Чтобы открыть панель снова, ' +
      'вернитесь в игру и нажмите кнопку панели в «Штабе».',
    hint: HINT_CLOSE_TAB,
  },
};

/** The gate top bar (mockup 09): logo + wordmark + «Пульт», nothing else. */
export function GateTopBar() {
  return (
    <header
      style={{
        height: SIZES['topbar-h'],
        boxSizing: 'border-box',
        background: tokenVar('surface'),
        borderBottom: `1px solid ${tokenVar('line')}`,
        display: 'flex',
        alignItems: 'center',
        padding: '0 16px',
        gap: 16,
      }}
    >
      <PanelBrand />
      <span
        aria-hidden="true"
        style={{
          width: 1,
          height: 24,
          background: tokenVar('line'),
          flexShrink: 0,
        }}
      />
      <span
        style={{
          ...TEXT_STYLES['label'],
          color: tokenVar('signal-ink'),
        }}
      >
        Пульт
      </span>
    </header>
  );
}

/** One status card in the screen-09 style; `children` adds hints. */
function GateCard({ card }: { card: GateCardKind }) {
  const { icon, title, text, hint } = GATE_CARDS[card];
  return (
    <div
      data-testid="panel-gate-card"
      role="alert"
      style={{
        width: 460,
        background: tokenVar('surface'),
        borderRadius: RADII['radius-lg'],
        padding: 16,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'flex-start',
        gap: 12,
      }}
    >
      <span
        aria-hidden="true"
        style={{
          display: 'flex',
          width: 44,
          height: 44,
          borderRadius: RADII['radius-md'],
          background: tokenVar('surface-inset'),
          alignItems: 'center',
          justifyContent: 'center',
          color: tokenVar('signal-ink'),
        }}
      >
        <GateIcon name={icon} />
      </span>
      <h2
        style={{
          margin: 0,
          ...TEXT_STYLES['heading'],
          fontSize: 20,
          lineHeight: '24px',
        }}
      >
        {title}
      </h2>
      <span style={TEXT_STYLES['body']}>{text}</span>
      {hint !== undefined && (
        <span
          style={{
            ...TEXT_STYLES['caption'],
            color: tokenVar('ink-muted'),
          }}
        >
          {hint}
        </span>
      )}
    </div>
  );
}

/**
 * The gate page: minimal top bar plus, while booting (`card` null) or
 * on a terminal state, at most one card centred like mockup 09.
 */
export function PanelGate({ card }: { card: GateCardKind | null }) {
  let body: ReactNode = null;
  if (card !== null) {
    body = (
      <div
        style={{
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'flex-start',
          gap: 24,
          padding: '96px 16px',
        }}
      >
        <GateCard card={card} />
      </div>
    );
  }
  return (
    <>
      <GateTopBar />
      {body}
    </>
  );
}
