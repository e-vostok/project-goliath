/**
 * UiKitPage — hidden catalogue of the shared UI library, rendered on
 * `#ui-kit` without auth or the router (unit 5). One place where the
 * Project Owner approves tokens, fonts, brand assets, the theme toggle
 * and every custom element of the UI Spec in both themes.
 */

import { useEffect, useMemo, useRef, useState } from 'react';

import type { NationRulesDTO } from '../types';
import { ImageUploadPreview } from '../../modules/00_core/components/ImageUploadPreview';
import type { ImageUploadMode } from '../../modules/00_core/components/ImageUploadPreview';
import { BlockTitle } from './BlockTitle';
import { BrandMark } from './BrandMark';
import { ColorSwatch } from './ColorSwatch';
import { EmptyState } from './EmptyState';
import { ErrorState, NETWORK_ERROR_TEXT } from './ErrorState';
import { FlagStub } from './FlagStub';
import { BlockIcon } from './icons';
import type { BlockIconName } from './icons';
import { ImageSlot } from './ImageSlot';
import type { ImageSlotKind } from './ImageSlot';
import { LoadingState } from './LoadingState';
import { AuthErrorScreen, LoadingScreen } from './LoadingScreen';
import { NationLabel } from './NationLabel';
import { Popup, PopupHost } from './Popup';
import type { PopupSize } from './Popup';
import { PortraitStub } from './PortraitStub';
import { ProvinceChip } from './ProvinceChip';
import { StatTile } from './StatTile';
import { Subscreen } from './Subscreen';
import { ThemeToggle, useTheme } from './theme';
import { Tooltip, TooltipRow } from './Tooltip';
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
      data-testid="app-root"
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
                    / 5
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
            <FlagStub variant="card" color="#2b2db0" />
            <FlagStub variant="row" />
            <PortraitStub variant="block" />
            <PortraitStub variant="row" />
          </div>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 24,
              marginTop: SPACING['space-3'],
              flexWrap: 'wrap',
            }}
          >
            <NationLabel
              name="НВГ"
              color="#2b2db0"
              size="cell"
            />
            <NationLabel name="Рязань" color="#2980B9" size="cell" />
            <NationLabel name="Безвестная вотчина" size="cell" />
            <NationLabel
              name="Новгородская республика"
              color="#2b2db0"
              size="tip"
            />
          </div>
        </Section>

        <Section>
          <BlockTitle icon="map" title="Чипы провинций" />
          <div
            style={{
              display: 'flex',
              flexWrap: 'wrap',
              gap: '6px 6px',
              alignItems: 'center',
            }}
          >
            <ProvinceChip name="Стокгольм" capital />
            <ProvinceChip
              name="Свейская равнина"
              capital
              capitalName="Королевский Вестерос"
            />
            <ProvinceChip
              name="Нижние Предгорья"
              capital
              capitalName="Старосветская Столица-Прибрежная"
            />
            <ProvinceChip name="Вестерос" />
            <ProvinceChip name="Евле" />
          </div>
        </Section>

        <Section>
          <BlockTitle icon="list" title="Полоса возврата подэкрана" />
          <div
            style={{
              marginLeft: -SPACING['space-4'],
              marginRight: -SPACING['space-4'],
            }}
          >
            <Subscreen
              parentLabel="Реестр"
              trail={['Игроки', 'Новгородская республика']}
              onBack={() => {}}
            >
              <div
                style={{
                  ...TEXT_STYLES['body'],
                  color: tokenVar('ink-muted'),
                }}
              >
                Содержимое подэкрана — родительский экран под полосой
                остаётся смонтированным, и «← Реестр» возвращает его
                как он был.
              </div>
            </Subscreen>
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

        <Section>
          <BlockTitle icon="document" title="Входной экран" />
          <div
            style={{
              border: `1px solid ${tokenVar('line')}`,
              borderRadius: RADII['radius-md'],
              overflow: 'hidden',
            }}
          >
            <LoadingScreen minHeight={280} />
          </div>
          <div
            style={{
              border: `1px solid ${tokenVar('line')}`,
              borderRadius: RADII['radius-md'],
              overflow: 'hidden',
              marginTop: SPACING['space-3'],
            }}
          >
            <AuthErrorScreen
              reason={NETWORK_ERROR_TEXT}
              onRetry={() => setRetries((n) => n + 1)}
              minHeight={280}
            />
          </div>
        </Section>

        <Section>
          <BlockTitle icon="list" title="Подсказка" />
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: SPACING['space-4'],
            }}
          >
            <Tooltip
              content={
                <div
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: SPACING['space-2'],
                  }}
                >
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: SPACING['space-2'],
                    }}
                  >
                    <span
                      aria-hidden
                      style={{
                        width: 10,
                        height: 10,
                        borderRadius: '50%',
                        flexShrink: 0,
                        background: tokenVar('action'),
                      }}
                    />
                    <span
                      style={{
                        ...TEXT_STYLES['heading'],
                        color: tokenVar('ink'),
                      }}
                    >
                      Новгородская республика
                    </span>
                  </div>
                  <TooltipRow label="Лидер" value="Борис Первый" />
                  <TooltipRow label="Провинций" value={5} />
                  <TooltipRow label="Столица" value="Новгород-град" />
                </div>
              }
            >
              <DemoButton onClick={() => {}}>
                Наведите и держите
              </DemoButton>
            </Tooltip>
            <span
              style={{
                ...TEXT_STYLES['caption'],
                color: tokenVar('ink-muted'),
              }}
            >
              Открывается через 0,5 с у курсора и следует за ним;
              закрывается уходом курсора, щелчком, прокруткой или Esc.
            </span>
          </div>
        </Section>

        <PopupDemo />

        <ImageSlotDemo />

        <ImageUploadPreviewDemo />
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

/** Demo rules for the upload window — the real config numbers. */
const DEMO_RULES: NationRulesDTO = {
  name_min_length: 3,
  name_max_length: 50,
  short_name_min_length: 2,
  short_name_max_length: 16,
  motto_max_length: 60,
  description_max_length: 100,
  leader_name_min_length: 1,
  leader_name_max_length: 60,
  leader_title_min_length: 1,
  leader_title_max_length: 60,
  leader_bio_max_length: 500,
  capital_name_min_length: 2,
  capital_name_max_length: 40,
  history_url_max_length: 300,
  history_url_allowed_hosts: ['vk.com'],
  anthem_url_max_length: 300,
  anthem_url_allowed_hosts: ['vk.com'],
  min_provinces: 2,
  max_provinces: 5,
  palette: ['#2b2db0'],
  images: {
    flag_width: 600,
    flag_height: 400,
    portrait_width: 600,
    portrait_height: 800,
    max_upload_bytes: 5242880,
  },
  genders: ['male', 'female'],
  succession_types: ['appointment'],
};

/** Draws the mockup's demo flag/portrait into a data URL (null in jsdom). */
function makeDemoImageSrc(width: number, height: number): string | null {
  try {
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');
    if (ctx === null) {
      return null;
    }
    ctx.fillStyle = '#1f3b63';
    ctx.fillRect(0, 0, width, height);
    ctx.fillStyle = '#e8a33d';
    ctx.beginPath();
    ctx.moveTo(0, height);
    ctx.lineTo(width, 0);
    ctx.lineTo(width, height * 0.28);
    ctx.lineTo(width * 0.28, height);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = '#f2f2f2';
    ctx.beginPath();
    ctx.arc(width * 0.3, height * 0.3, Math.min(width, height) * 0.12, 0, 7);
    ctx.fill();
    return canvas.toDataURL('image/png');
  } catch {
    return null;
  }
}

/** A real decodable picture file for the preview demo. */
function makeDemoImageFile(
  width: number,
  height: number,
  name: string,
): Promise<File | null> {
  try {
    const canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext('2d');
    if (ctx === null) {
      return Promise.resolve(null);
    }
    ctx.fillStyle = '#1f3b63';
    ctx.fillRect(0, 0, width, height);
    ctx.fillStyle = '#e8a33d';
    ctx.beginPath();
    ctx.moveTo(0, height);
    ctx.lineTo(width, 0);
    ctx.lineTo(width, height * 0.28);
    ctx.lineTo(width * 0.28, height);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = '#f2f2f2';
    ctx.beginPath();
    ctx.arc(width * 0.3, height * 0.3, Math.min(width, height) * 0.12, 0, 7);
    ctx.fill();
    return new Promise((resolve) =>
      canvas.toBlob(
        (blob) =>
          resolve(
            blob === null
              ? null
              : new File([blob], name, { type: 'image/png' }),
          ),
        'image/png',
      ),
    );
  } catch {
    return Promise.resolve(null);
  }
}

function DemoLabel({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        ...TEXT_STYLES['label'],
        color: tokenVar('ink-muted'),
      }}
    >
      {children}
    </div>
  );
}

/** ImageSlot (Spec 6, элемент 13): the board-17 states. */
function ImageSlotDemo() {
  const flagSrc = useMemo(() => makeDemoImageSrc(600, 400), []);
  const portraitSrc = useMemo(() => makeDemoImageSrc(600, 800), []);
  const [log, setLog] = useState('—');

  const flagHint = {
    first: 'Нажмите, чтобы загрузить другой флаг',
    second: `Лучше ${DEMO_RULES.images.flag_width}×${DEMO_RULES.images.flag_height} · JPEG, PNG, WebP · до 5 МБ`,
  };
  const portraitHint = {
    first: 'Нажмите, чтобы загрузить портрет',
    second: `Лучше ${DEMO_RULES.images.portrait_width}×${DEMO_RULES.images.portrait_height} · JPEG, PNG, WebP · до 5 МБ`,
  };
  const cell: React.CSSProperties = {
    display: 'flex',
    flexDirection: 'column',
    gap: SPACING['space-2'],
    alignItems: 'flex-start',
  };

  return (
    <Section>
      <BlockTitle icon="flag" title="Блок картинки (ImageSlot)" />
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(4,minmax(0,1fr))',
          gap: SPACING['space-3'],
        }}
      >
        <div style={cell}>
          <DemoLabel>Флаг: заглушка (цвет)</DemoLabel>
          <ImageSlot
            kind="flag"
            size="shtab"
            src={null}
            stubColor="#2b2db0"
            alt="Флаг"
            interactive
            hintLines={{ first: 'Нажмите, чтобы загрузить флаг' }}
            onPick={(f) => setLog(`flag ← ${f.name}`)}
          />
        </div>
        <div style={cell}>
          <DemoLabel>Флаг: загружен</DemoLabel>
          <ImageSlot
            kind="flag"
            size="shtab"
            src={flagSrc}
            stubColor="#2b2db0"
            alt="Флаг"
            interactive
            hintLines={flagHint}
            onPick={(f) => setLog(`flag ← ${f.name}`)}
          />
        </div>
        <div style={cell}>
          <DemoLabel>Флаг: обработка</DemoLabel>
          <ImageSlot
            kind="flag"
            size="shtab"
            src={flagSrc}
            stubColor="#2b2db0"
            alt="Флаг"
            interactive
            busy
            hintLines={flagHint}
            onPick={(f) => setLog(`flag ← ${f.name}`)}
          />
        </div>
        <div style={cell}>
          <DemoLabel>Флаг: чужой (не кликается)</DemoLabel>
          <ImageSlot
            kind="flag"
            size="shtab"
            src={flagSrc}
            stubColor="#2b2db0"
            alt="Флаг"
            interactive={false}
          />
        </div>
        <div style={cell}>
          <DemoLabel>Портрет: заглушка</DemoLabel>
          <ImageSlot
            kind="portrait"
            size="shtab"
            src={null}
            alt="Портрет"
            interactive
            hintLines={portraitHint}
            onPick={(f) => setLog(`portrait ← ${f.name}`)}
          />
        </div>
        <div style={cell}>
          <DemoLabel>Портрет: загружен</DemoLabel>
          <ImageSlot
            kind="portrait"
            size="shtab"
            src={portraitSrc}
            alt="Портрет"
            interactive
            hintLines={{
              first: 'Нажмите, чтобы загрузить другой портрет',
              second: portraitHint.second,
            }}
            onPick={(f) => setLog(`portrait ← ${f.name}`)}
          />
        </div>
        <div style={cell}>
          <DemoLabel>Портрет: обработка</DemoLabel>
          <ImageSlot
            kind="portrait"
            size="shtab"
            src={portraitSrc}
            alt="Портрет"
            interactive
            busy
            hintLines={portraitHint}
            onPick={(f) => setLog(`portrait ← ${f.name}`)}
          />
        </div>
        <div style={cell}>
          <DemoLabel>Портрет: чужой</DemoLabel>
          <ImageSlot
            kind="portrait"
            size="shtab"
            src={portraitSrc}
            alt="Портрет"
            interactive={false}
          />
        </div>
      </div>
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: SPACING['space-4'],
          marginTop: SPACING['space-4'],
        }}
      >
        <div>
          <DemoLabel>Регистрация: флаг</DemoLabel>
          <div style={{ marginTop: SPACING['space-2'] }}>
            <ImageSlot
              kind="flag"
              size="registration"
              src={null}
              stubColor="#2b2db0"
              alt="Флаг"
              interactive
              hintLines={{ first: 'Нажмите, чтобы загрузить флаг' }}
              rules={DEMO_RULES}
              onPick={(f) => setLog(`reg flag ← ${f.name}`)}
            />
          </div>
        </div>
        <div>
          <DemoLabel>Регистрация: портрет</DemoLabel>
          <div style={{ marginTop: SPACING['space-2'] }}>
            <ImageSlot
              kind="portrait"
              size="registration"
              src={null}
              alt="Портрет"
              interactive
              hintLines={{ first: 'Нажмите, чтобы загрузить портрет' }}
              rules={DEMO_RULES}
              onPick={(f) => setLog(`reg portrait ← ${f.name}`)}
            />
          </div>
        </div>
        <div
          style={{
            ...TEXT_STYLES['caption'],
            color: tokenVar('ink-muted'),
          }}
        >
          Последний выбранный файл: {log}
        </div>
      </div>
    </Section>
  );
}

/** The upload preview window (boards 15/15б/16) in four states. */
function ImageUploadPreviewDemo() {
  const [preview, setPreview] = useState<{
    kind: ImageSlotKind;
    mode: ImageUploadMode;
    file: File;
    failNetwork: boolean;
  } | null>(null);

  const openFile = (
    kind: ImageSlotKind,
    mode: ImageUploadMode,
    file: File | null,
    failNetwork = false,
  ) => {
    if (file !== null) {
      setPreview({ kind, mode, file, failNetwork });
    }
  };

  const bigFile = new File(
    [new Uint8Array(6_400_000)],
    'ochen_bolshoy_flag.jpg',
    { type: 'image/jpeg' },
  );

  return (
    <Section>
      <BlockTitle icon="document" title="Окно загрузки картинки" />
      <div
        style={{
          display: 'flex',
          gap: SPACING['space-2'],
          flexWrap: 'wrap',
        }}
      >
        <DemoButton
          onClick={() =>
            void makeDemoImageFile(1920, 1080, 'severny_flag.jpg').then((f) =>
              openFile('flag', 'replace', f),
            )
          }
        >
          Флаг: предпросмотр
        </DemoButton>
        <DemoButton
          onClick={() =>
            void makeDemoImageFile(1200, 1200, 'kvadrat_flag.png').then((f) =>
              openFile('flag', 'replace', f),
            )
          }
        >
          Флаг: не та форма
        </DemoButton>
        <DemoButton onClick={() => openFile('flag', 'replace', bigFile)}>
          Флаг: слишком большой
        </DemoButton>
        <DemoButton
          onClick={() =>
            void makeDemoImageFile(1600, 2400, 'portret.png').then((f) =>
              openFile('portrait', 'register', f),
            )
          }
        >
          Портрет: регистрация
        </DemoButton>
        <DemoButton
          onClick={() =>
            void makeDemoImageFile(1920, 1080, 'severny_flag.jpg').then((f) =>
              openFile('flag', 'replace', f, true),
            )
          }
        >
          Сбой сети («Повторить»)
        </DemoButton>
      </div>
      {preview !== null && (
        <ImageUploadPreview
          kind={preview.kind}
          mode={preview.mode}
          file={preview.file}
          rules={DEMO_RULES}
          onConfirm={async () => {
            await new Promise((r) => setTimeout(r, 400));
            if (preview.failNetwork) {
              throw new TypeError('Failed to fetch');
            }
            setPreview(null);
          }}
          onPickAnother={() => setPreview(null)}
          onClose={() => setPreview(null)}
        />
      )}
    </Section>
  );
}
