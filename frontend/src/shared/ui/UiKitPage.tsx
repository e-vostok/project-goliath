/**
 * UiKitPage — hidden catalogue of the shared UI library, rendered on
 * `#ui-kit` without auth or the router (unit 5). One place where the
 * Project Owner approves tokens, fonts, brand assets, the theme toggle
 * and every custom element of the UI Spec in both themes.
 */

import { useEffect, useRef, useState } from 'react';

import { BlockTitle } from './BlockTitle';
import { BrandMark } from './BrandMark';
import { ColorSwatch } from './ColorSwatch';
import { EmptyState } from './EmptyState';
import { ErrorState, NETWORK_ERROR_TEXT } from './ErrorState';
import { FlagStub } from './FlagStub';
import { BlockIcon } from './icons';
import type { BlockIconName } from './icons';
import { LoadingState } from './LoadingState';
import { Popup, PopupHost } from './Popup';
import type { PopupSize } from './Popup';
import { PortraitStub } from './PortraitStub';
import { ProvinceChip } from './ProvinceChip';
import { StatTile } from './StatTile';
import { ThemeToggle, useTheme } from './theme';
import {
  FONTS,
  RADII,
  SIZES,
  SPACING,
  TEXT_STYLES,
  THEME_COLORS,
  THEME_SHADOWS,
  tokenVar,
} from './tokens';
import { TurnBadge } from './TurnBadge';
import type { ColorToken, TextStyleName } from './tokens';

const ICON_NAMES: BlockIconName[] = [
  'person',
  'map',
  'lines',
  'document',
  'list',
  'scales',
];

const TEXT_STYLE_NAMES = Object.keys(TEXT_STYLES) as TextStyleName[];

function Section({ children }: { children: React.ReactNode }) {
  return (
    <section
      style={{
        background: tokenVar('surface'),
        borderRadius: RADII['radius-lg'],
        padding: SPACING['space-4'],
      }}
    >
      {children}
    </section>
  );
}

export function UiKitPage() {
  const { resolved, vkScheme } = useTheme();
  const [retries, setRetries] = useState(0);
  // The catalogue's own popup root — the demo popups portal into it.
  const kitRef = useRef<HTMLDivElement>(null);

  // The catalogue owns its page chrome — the provider's wrapper covers
  // the viewport; body margin/background follow the resolved theme.
  useEffect(() => {
    const body = document.body;
    const prevMargin = body.style.margin;
    const prevBackground = body.style.background;
    body.style.margin = '0';
    body.style.background = THEME_COLORS[resolved]['ground'];
    return () => {
      body.style.margin = prevMargin;
      body.style.background = prevBackground;
    };
  }, [resolved]);

  return (
    <div
      ref={kitRef}
      style={{
        position: 'relative',
        width: SIZES['win-screen'],
        minHeight: '100vh',
        boxSizing: 'border-box',
        background: tokenVar('ground'),
        color: tokenVar('ink'),
        ...TEXT_STYLES['body'],
      }}
    >
      <PopupHost container={kitRef}>
      <header
        style={{
          height: SIZES['topbar-h'],
          boxSizing: 'border-box',
          background: tokenVar('surface'),
          borderBottom: `1px solid ${tokenVar('line')}`,
          display: 'flex',
          alignItems: 'center',
          padding: '0 16px',
          gap: 24,
        }}
      >
        <BrandMark />
        <div style={{ flexGrow: 1 }} />
        <TurnBadge>ХОД 1 · ЯНВАРЬ 2040</TurnBadge>
        <ThemeToggle />
      </header>

      <main
        style={{
          padding: SPACING['space-4'],
          display: 'flex',
          flexDirection: 'column',
          gap: SPACING['space-3'],
        }}
      >
        <Section>
          <div style={{ ...TEXT_STYLES['body'], color: tokenVar('ink-muted') }}>
            ВК сообщает тему:{' '}
            <span style={{ ...TEXT_STYLES['figure'], color: tokenVar('ink') }}>
              {vkScheme ?? 'не сообщает'}
            </span>
          </div>
        </Section>

        <Section>
          <BlockTitle icon="lines" title="Цвета" />
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(4,minmax(0,1fr))',
              gap: SPACING['space-2'],
            }}
          >
            {(Object.keys(THEME_COLORS[resolved]) as ColorToken[]).map(
              (name) => (
                <div
                  key={name}
                  style={{ display: 'flex', alignItems: 'center', gap: 8 }}
                >
                  <span
                    style={{
                      width: 24,
                      height: 24,
                      flexShrink: 0,
                      borderRadius: RADII['radius-sm'],
                      background: tokenVar(name),
                      border: `1px solid ${tokenVar('line')}`,
                      boxSizing: 'border-box',
                    }}
                  />
                  <span style={{ minWidth: 0 }}>
                    <div
                      style={{
                        ...TEXT_STYLES['label'],
                        color: tokenVar('ink-muted'),
                      }}
                    >
                      {name}
                    </div>
                    <div
                      style={{
                        fontFamily: FONTS.mono,
                        fontSize: 11,
                        lineHeight: '14px',
                        color: tokenVar('ink'),
                      }}
                    >
                      {THEME_COLORS[resolved][name]}
                    </div>
                  </span>
                </div>
              ),
            )}
          </div>
        </Section>

        <Section>
          <BlockTitle icon="lines" title="Размеры и формы" />
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(3,minmax(0,1fr))',
              gap: SPACING['space-2'],
              ...TEXT_STYLES['caption'],
              color: tokenVar('ink-muted'),
            }}
          >
            <div>
              <div style={{ ...TEXT_STYLES['label'] }}>Отступы</div>
              {Object.entries(SPACING).map(([k, v]) => (
                <div key={k}>
                  {k} — {v} px
                </div>
              ))}
            </div>
            <div>
              <div style={{ ...TEXT_STYLES['label'] }}>Скругления</div>
              {Object.entries(RADII).map(([k, v]) => (
                <div key={k}>
                  {k} — {v} px
                </div>
              ))}
            </div>
            <div>
              <div style={{ ...TEXT_STYLES['label'] }}>Размеры и тени</div>
              {Object.entries(SIZES).map(([k, v]) => (
                <div key={k}>
                  {k} — {v} px
                </div>
              ))}
              {Object.keys(THEME_SHADOWS[resolved]).map((k) => (
                <div key={k}>{k}</div>
              ))}
            </div>
          </div>
        </Section>

        <Section>
          <BlockTitle icon="lines" title="Стили текста" />
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: SPACING['space-2'],
            }}
          >
            {TEXT_STYLE_NAMES.map((name) => (
              <div
                key={name}
                style={{ display: 'flex', alignItems: 'baseline', gap: 16 }}
              >
                <span
                  style={{
                    ...TEXT_STYLES['figure'],
                    fontSize: 11,
                    color: tokenVar('ink-muted'),
                    width: 140,
                    flexShrink: 0,
                  }}
                >
                  {name}
                </span>
                <span style={{ ...TEXT_STYLES[name], color: tokenVar('ink') }}>
                  Северный Синдикат · Ход 1 · Январь 2040
                </span>
              </div>
            ))}
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 16 }}>
              <span
                style={{
                  ...TEXT_STYLES['figure'],
                  fontSize: 11,
                  color: tokenVar('ink-muted'),
                  width: 140,
                  flexShrink: 0,
                }}
              >
                wordmark
              </span>
              <span
                style={{
                  fontFamily: FONTS.wordmark,
                  fontWeight: 800,
                  fontSize: 24,
                  lineHeight: '28px',
                  letterSpacing: '.1em',
                  color: tokenVar('ink'),
                }}
              >
                PAX ATOMICA
              </span>
            </div>
          </div>
        </Section>

        <Section>
          <BlockTitle icon="list" title="Значки блоков" />
          <div style={{ display: 'flex', gap: SPACING['space-5'] }}>
            {ICON_NAMES.map((name) => (
              <span
                key={name}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  ...TEXT_STYLES['caption'],
                  color: tokenVar('ink-muted'),
                }}
              >
                <BlockIcon name={name} />
                {name}
              </span>
            ))}
          </div>
        </Section>

        <Section>
          <BlockTitle icon="person" title="Заголовок блока" />
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(4,minmax(0,1fr))',
              gap: SPACING['space-3'],
            }}
          >
            <StatTile label="Провинции" value={5} />
            <StatTile label="Уровень" value={1} />
            <StatTile label="Судейский рейтинг" value={0} accent />
            <StatTile
              label="Неразрешённые приказы"
              value={
                <>
                  0{' '}
                  <span
                    style={{
                      fontSize: 14,
                      color: tokenVar('ink-muted'),
                    }}
                  >
                    из 5
                  </span>
                </>
              }
            />
          </div>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 12,
              marginTop: SPACING['space-3'],
              flexWrap: 'wrap',
            }}
          >
            <TurnBadge>ХОД 1 · ЯНВАРЬ 2040</TurnBadge>
            <ColorSwatch hex="#2b2db0" />
            <FlagStub variant="card" />
            <FlagStub variant="row" />
            <PortraitStub variant="block" />
            <PortraitStub variant="row" />
          </div>
        </Section>

        <Section>
          <BlockTitle icon="map" title="Чипы провинций" />
          <div
            style={{
              display: 'flex',
              flexWrap: 'wrap',
              gap: 6,
            }}
          >
            <ProvinceChip name="Стокгольм" capital />
            <ProvinceChip
              name="Свейская равнина"
              capital
              capitalName="Королевский Вестерос"
            />
            <ProvinceChip name="Вестерос" />
            <ProvinceChip name="Евле" />
          </div>
        </Section>

        <Section>
          <BlockTitle icon="document" title="Состояния" />
          <LoadingState height={48} />
          <ErrorState
            reason={NETWORK_ERROR_TEXT}
            onRetry={() => setRetries((n) => n + 1)}
          />
          <ErrorState reason="Сервер не ответил вовремя." />
          <EmptyState text="Приказов на рассмотрении нет" />
          <EmptyState
            text="Государств по запросу не найдено"
            action={
              <span
                style={{ ...TEXT_STYLES['caption'], color: tokenVar('link') }}
              >
                Сбросить фильтры
              </span>
            }
          />
          <div
            style={{
              ...TEXT_STYLES['caption'],
              color: tokenVar('ink-muted'),
              textAlign: 'center',
            }}
          >
            Нажатий «Повторить»: {retries}
          </div>
        </Section>

        <PopupDemo />
      </main>
      </PopupHost>
    </div>
  );
}

function DemoButton({
  onClick,
  children,
}: {
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        height: SIZES['button-h'],
        boxSizing: 'border-box',
        padding: '0 16px',
        border: 'none',
        borderRadius: RADII['radius-md'],
        background: tokenVar('surface-inset'),
        color: tokenVar('ink'),
        ...TEXT_STYLES['body'],
        cursor: 'pointer',
      }}
    >
      {children}
    </button>
  );
}

const DEMO_TITLES: Record<PopupSize, string> = {
  S: 'Малое окно',
  M: 'Окно формы',
  L: 'Большое окно',
};

function PopupDemo() {
  const [size, setSize] = useState<PopupSize | null>(null);
  const [confirm, setConfirm] = useState(false);
  const [typed, setTyped] = useState('');

  return (
    <Section>
      <BlockTitle icon="document" title="Всплывающие окна" />
      <div style={{ display: 'flex', gap: SPACING['space-2'] }}>
        <DemoButton onClick={() => setSize('S')}>
          Открыть S — 480
        </DemoButton>
        <DemoButton onClick={() => setSize('M')}>
          Открыть M — 640
        </DemoButton>
        <DemoButton onClick={() => setSize('L')}>
          Открыть L — 880
        </DemoButton>
      </div>
      {size !== null && (
        <Popup
          size={size}
          icon="document"
          title={`${DEMO_TITLES[size]} (${SIZES[`win-popup-${size.toLowerCase()}` as keyof typeof SIZES]} px)`}
          onClose={() => {
            setSize(null);
            setTyped('');
          }}
          dirty={typed !== ''}
          footer={
            <>
              <DemoButton
                onClick={() => {
                  setSize(null);
                  setTyped('');
                }}
              >
                Отмена
              </DemoButton>
              <button
                type="button"
                onClick={() => {
                  setSize(null);
                  setTyped('');
                }}
                style={{
                  height: SIZES['button-h'],
                  boxSizing: 'border-box',
                  padding: '0 16px',
                  border: 'none',
                  borderRadius: RADII['radius-md'],
                  background: tokenVar('action'),
                  color: tokenVar('ink'),
                  ...TEXT_STYLES['body'],
                  cursor: 'pointer',
                }}
              >
                Отправить
              </button>
            </>
          }
        >
          <div style={{ color: tokenVar('ink-muted') }}>
            Окно прижато к верху контейнера (64 px). Esc и клик по
            затемнению закрывают его, пока поле пустое — введите текст,
            и они перестанут работать (dirty), крестик и «Отмена»
            остаются.
          </div>
          <input
            value={typed}
            onChange={(e) => setTyped(e.currentTarget.value)}
            placeholder="Поле для пробы dirty"
            style={{
              height: 36,
              boxSizing: 'border-box',
              background: tokenVar('surface-inset'),
              color: tokenVar('ink'),
              border: `1px solid ${tokenVar('ink-faint')}`,
              borderRadius: RADII['radius-md'],
              padding: '0 12px',
              ...TEXT_STYLES['body'],
            }}
          />
          {size === 'M' && (
            <div>
              <DemoButton onClick={() => setConfirm(true)}>
                Открыть подтверждение S поверх
              </DemoButton>
            </div>
          )}
        </Popup>
      )}
      {confirm && (
        <Popup
          size="S"
          icon="document"
          title="Отправить приказ?"
          onClose={() => setConfirm(false)}
          footer={
            <>
              <DemoButton onClick={() => setConfirm(false)}>
                Вернуться к правке
              </DemoButton>
              <button
                type="button"
                onClick={() => {
                  setConfirm(false);
                  setSize(null);
                  setTyped('');
                }}
                style={{
                  height: SIZES['button-h'],
                  boxSizing: 'border-box',
                  padding: '0 16px',
                  border: 'none',
                  borderRadius: RADII['radius-md'],
                  background: tokenVar('action'),
                  color: tokenVar('ink'),
                  ...TEXT_STYLES['body'],
                  cursor: 'pointer',
                }}
              >
                Да, отправить
              </button>
            </>
          }
        >
          <div style={{ color: tokenVar('ink-muted') }}>
            Малое подтверждение лежит поверх формы: затемнение второго
            уровня темнее, Esc и клик по затемнению закрывают только
            его.
          </div>
        </Popup>
      )}
    </Section>
  );
}
