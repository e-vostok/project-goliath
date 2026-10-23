/**
 * OrderDetailModal — the «Приказ №N» window (Spec 5.4): a Popup L.
 *
 * Nation colour mark and name next to the number (`headerExtra`);
 * blocks: title, «Краткая суть приказа», link «Статья приказа ↗»;
 * after a divider the «Вердикт» block (scales icon) when a verdict
 * exists; «Срок вердикта вышел» on top in `danger` with a dot when
 * overdue; «Написать вердикт» in the footer only when
 * `can_write_verdict` — it replaces this window with the verdict
 * composer. The judge is never shown (INV-O5). A 404 renders
 * «Приказ не найден».
 */

import { Button, FormStatus, Link } from '@vkontakte/vkui';

import { errorText } from '../../shared/errorTexts';
import {
  BlockIcon,
  ErrorState,
  FONTS,
  LoadingState,
  Popup,
  RADII,
  TEXT_STYLES,
  tokenVar,
} from '../../shared/ui';
import { useOrderDetail } from './hooks/useOrderDetail';
import { NationMark } from './components/NationMark';
import { ORDERS_TEXTS } from './texts';
import type { OrderDetailDTO } from './types';
import { useOrdersUi } from './OrdersUiProvider';

/** The mockup's small uppercase block label («Краткая суть приказа»). */
const BLOCK_LABEL = {
  fontFamily: FONTS.heading,
  fontWeight: 500,
  fontSize: 12,
  lineHeight: '16px',
  letterSpacing: '.06em',
  textTransform: 'uppercase',
  color: tokenVar('ink-muted'),
  marginBottom: 4,
} as const;

const ITEM_TITLE = {
  fontSize: 16,
  lineHeight: '22px',
  fontWeight: 500,
} as const;

export function OrderDetailModal() {
  const { orderWindow, closeWindow, openVerdictComposer } = useOrdersUi();
  const number = orderWindow?.view === 'detail' ? orderWindow.number : null;
  const detail = useOrderDetail(number);
  const order = detail.status === 'ready' ? detail.order : null;

  if (number === null) {
    return null;
  }

  return (
    <Popup
      size="L"
      icon="document"
      title={ORDERS_TEXTS.detailTitle(number)}
      onClose={closeWindow}
      testId="popup-order-detail"
      headerExtra={
        order !== null ? (
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              padding: '2px 8px',
              borderRadius: RADII['radius-sm'],
              background: tokenVar('surface-inset'),
              fontFamily: FONTS.body,
              fontSize: 13,
              lineHeight: '18px',
              fontWeight: 400,
              letterSpacing: 0,
              textTransform: 'none',
            }}
          >
            <NationMark nation={order.nation} />
          </span>
        ) : undefined
      }
      footer={
        <>
          <Button size="m" mode="secondary" onClick={closeWindow}>
            {ORDERS_TEXTS.closeButton}
          </Button>
          {order?.can_write_verdict && (
            <Button
              size="m"
              mode="primary"
              onClick={() => openVerdictComposer(order.number)}
            >
              {ORDERS_TEXTS.writeVerdict}
            </Button>
          )}
        </>
      }
    >
      {detail.status === 'loading' ? (
        <LoadingState height={200} />
      ) : detail.status === 'error' ? (
        detail.notFound ? (
          <FormStatus mode="error" title={ORDERS_TEXTS.notFound} />
        ) : (
          <ErrorState
            reason={errorText(detail.error)}
            onRetry={detail.reload}
          />
        )
      ) : (
        order !== null && <OrderDetailBody order={order} />
      )}
    </Popup>
  );
}

function ArticleLink({ url, label }: { url: string; label: string }) {
  // Same defense in depth as the nation history link: a stored value
  // that is not https:// renders as plain text, never as a link.
  if (!url.startsWith('https://')) {
    return <span>{url}</span>;
  }
  return (
    <Link href={url} target="_blank" rel="noopener noreferrer">
      {label}
    </Link>
  );
}

function OrderDetailBody({ order }: { order: OrderDetailDTO }) {
  return (
    <>
      {order.overdue && (
        <div
          data-testid="order-overdue-mark"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            color: tokenVar('danger'),
            fontWeight: 500,
          }}
        >
          <span
            aria-hidden="true"
            style={{
              width: 8,
              height: 8,
              borderRadius: '50%',
              background: tokenVar('danger'),
              flexShrink: 0,
            }}
          />
          {ORDERS_TEXTS.overdueMark}
        </div>
      )}

      <div style={ITEM_TITLE}>{order.title}</div>

      <div>
        <div style={BLOCK_LABEL}>{ORDERS_TEXTS.summaryBlockTitle}</div>
        <div style={{ whiteSpace: 'pre-wrap', overflowWrap: 'break-word' }}>
          {order.summary}
        </div>
        <div style={{ marginTop: 8 }}>
          <ArticleLink
            url={order.article_url}
            label={`${ORDERS_TEXTS.articleLink} ↗`}
          />
        </div>
      </div>

      {order.verdict !== null && (
        <>
          <div style={{ height: 1, background: tokenVar('line') }} />
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              ...TEXT_STYLES['heading'],
              letterSpacing: '.06em',
              textTransform: 'uppercase',
            }}
          >
            <BlockIcon name="scales" />
            {ORDERS_TEXTS.verdictBlockTitle}
          </div>
          <div style={ITEM_TITLE}>{order.verdict.title}</div>
          <div>
            <div style={BLOCK_LABEL}>
              {ORDERS_TEXTS.verdictSummaryTitle}
            </div>
            <div
              style={{ whiteSpace: 'pre-wrap', overflowWrap: 'break-word' }}
            >
              {order.verdict.summary}
            </div>
            <div style={{ marginTop: 8 }}>
              <ArticleLink
                url={order.verdict.article_url}
                label={`${ORDERS_TEXTS.verdictArticleLink} ↗`}
              />
            </div>
          </div>
        </>
      )}
    </>
  );
}
