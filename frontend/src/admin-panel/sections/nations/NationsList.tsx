/**
 * NationsList — the «Государства» table (0.11.0 units 8a/8b,
 * mockup screen 03): the search row with «Поиск по названию» and
 * «Показано N из M», the primary «Создать государство» button, one
 * table card — Государство (flag stub, short name over full
 * name), Владелец, Провинций, Столица, and the right-most actions
 * column: «Править» (unit 8b) and the red-outline «Удалить…» (unit
 * 8c) — plus «Показать ещё» while total exceeds what is shown.
 * Split out of NationsSection.tsx for unit 8b; behaviour unchanged.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { api, ApiError } from '../../../shared/api-client';
import type { AdminNationDTO } from '../../../shared/types';
import { EmptyState } from '../../../shared/ui/EmptyState';
import { ErrorState } from '../../../shared/ui/ErrorState';
import { FlagMark } from '../../../shared/ui/FlagMark';
import { LoadingState } from '../../../shared/ui/LoadingState';
import {
  SPACING,
  TEXT_STYLES,
  tokenVar,
} from '../../../shared/ui/tokens';
import { useAdminSession } from '../../PanelFrame';
import { PanelIcon } from '../../panelIcons';
import { PAGE_SIZE, PanelButton, PanelCard, inputStyle } from './shared';

const SEARCH_DEBOUNCE_MS = 350;
const SEARCH_PLACEHOLDER = 'Поиск по названию';

type ListStatus = 'loading' | 'ready' | 'error';

/** The 22×14 nation flag of a cell — the uploaded thumb or the stub. */
function FlagCell({ url }: { url: string | null }) {
  return (
    <FlagMark url={url} width={22} height={14} stubVariant="cell" />
  );
}

export function NationsList({
  onCreate,
  onEdit,
  onDelete,
}: {
  onCreate: () => void;
  /** Row action — opens screen 03b for the nation. */
  onEdit: (nation: AdminNationDTO) => void;
  /** Row action — opens the screen-03d deletion popup. */
  onDelete: (nation: AdminNationDTO) => void;
}) {
  const { token, reportUnauthorized } = useAdminSession();

  const [items, setItems] = useState<AdminNationDTO[]>([]);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState<ListStatus>('loading');
  const [loadingMore, setLoadingMore] = useState(false);
  const [search, setSearch] = useState('');
  const [appliedSearch, setAppliedSearch] = useState('');

  const loadSeq = useRef(0);

  const load = useCallback(
    async (searchText: string, offset: number, append: boolean) => {
      const seq = ++loadSeq.current;
      try {
        const page = await api.adminNations(token, {
          search: searchText,
          limit: PAGE_SIZE,
          offset,
        });
        if (seq !== loadSeq.current) {
          return;
        }
        setItems((prev) => (append ? [...prev, ...page.items] : page.items));
        setTotal(page.total);
        setStatus('ready');
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          reportUnauthorized();
          return;
        }
        if (seq !== loadSeq.current) {
          return;
        }
        if (append) {
          setLoadingMore(false);
        }
        setStatus('error');
      } finally {
        if (seq === loadSeq.current) {
          setLoadingMore(false);
        }
      }
    },
    [token, reportUnauthorized],
  );

  useEffect(() => {
    const id = setTimeout(
      () => setAppliedSearch(search.trim()),
      SEARCH_DEBOUNCE_MS,
    );
    return () => clearTimeout(id);
  }, [search]);

  useEffect(() => {
    setStatus('loading');
    void load(appliedSearch, 0, false);
  }, [appliedSearch, load]);

  const loadMore = () => {
    setLoadingMore(true);
    void load(appliedSearch, items.length, true);
  };

  const cellStyle = (last: boolean) => ({
    height: 44,
    padding: '4px 12px',
    borderBottom: last ? 'none' : `1px solid ${tokenVar('line')}`,
    verticalAlign: 'middle' as const,
    ...TEXT_STYLES['body'],
  });

  return (
    <>
      <h1
        style={{
          margin: 0,
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          ...TEXT_STYLES['title-uppercase'],
          fontSize: 24,
          lineHeight: '28px',
        }}
      >
        <PanelIcon name="flag" accent size={20} />
        Государства
      </h1>

      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: SPACING['space-3'],
        }}
      >
        <div style={{ width: 340 }}>
          <label
            htmlFor="nations-search"
            style={{
              position: 'absolute',
              left: -9999,
              ...TEXT_STYLES['caption'],
            }}
          >
            Поиск
          </label>
          <input
            id="nations-search"
            data-testid="nations-search"
            value={search}
            placeholder={SEARCH_PLACEHOLDER}
            onChange={(event) => setSearch(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault();
              }
            }}
            style={inputStyle}
          />
        </div>
        <span
          data-testid="nations-shown"
          style={{
            flexGrow: 1,
            ...TEXT_STYLES['caption'],
            color: tokenVar('ink-muted'),
          }}
        >
          {status === 'ready' && `Показано ${items.length} из ${total}`}
        </span>
        <PanelButton
          kind="primary"
          testId="nations-create-open"
          onClick={onCreate}
        >
          Создать государство
        </PanelButton>
      </div>

      <PanelCard>
        {status === 'loading' && <LoadingState height={150} />}
        {status === 'error' && (
          <ErrorState
            onRetry={() => {
              setStatus('loading');
              void load(appliedSearch, 0, false);
            }}
          />
        )}
        {status === 'ready' && items.length === 0 && (
          <EmptyState
            text={
              appliedSearch === ''
                ? 'Государств пока нет.'
                : 'Ничего не нашлось по этому запросу.'
            }
          />
        )}
        {status === 'ready' && items.length > 0 && (
          <table
            data-testid="nations-table"
            style={{ width: '100%', borderCollapse: 'collapse' }}
          >
            <thead>
              <tr>
                {['Государство', 'Владелец', 'Провинций', 'Столица', ''].map(
                  (head) => (
                    <th
                      key={head}
                      style={{
                        textAlign: 'left',
                        padding: '8px 12px',
                        borderBottom: `1px solid ${tokenVar('line')}`,
                        ...TEXT_STYLES['label'],
                        color: tokenVar('ink-muted'),
                      }}
                    >
                      {head}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {items.map((nation, index) => {
                const last = index === items.length - 1;
                return (
                  <tr key={nation.id} data-testid="nation-row">
                    <td style={cellStyle(last)}>
                      <span
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: 10,
                        }}
                      >
                        <FlagCell url={nation.flag_thumb_url} />
                        <span>
                          <span style={{ fontWeight: 500 }}>
                            {nation.short_name}
                          </span>
                          <br />
                          <span
                            style={{
                              ...TEXT_STYLES['caption'],
                              color: tokenVar('ink-muted'),
                            }}
                          >
                            {nation.name}
                          </span>
                        </span>
                      </span>
                    </td>
                    <td style={cellStyle(last)}>
                      {nation.owner_name ?? `VK ${nation.owner_vk_user_id}`}
                    </td>
                    <td
                      style={{ ...cellStyle(last), ...TEXT_STYLES['figure'] }}
                    >
                      {nation.provinces_count}
                    </td>
                    <td style={cellStyle(last)}>
                      {nation.capital_name ?? '—'}
                    </td>
                    <td
                      style={{
                        ...cellStyle(last),
                        textAlign: 'right',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      <PanelButton
                        testId={`nation-edit-${nation.id}`}
                        onClick={() => onEdit(nation)}
                      >
                        Править
                      </PanelButton>{' '}
                      <PanelButton
                        kind="danger-outline"
                        testId={`nation-delete-${nation.id}`}
                        onClick={() => onDelete(nation)}
                      >
                        Удалить…
                      </PanelButton>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </PanelCard>

      {status === 'ready' && items.length < total && (
        <div style={{ display: 'flex', justifyContent: 'center' }}>
          <PanelButton
            testId="nations-load-more"
            disabled={loadingMore}
            onClick={loadMore}
          >
            Показать ещё
          </PanelButton>
        </div>
      )}
    </>
  );
}
