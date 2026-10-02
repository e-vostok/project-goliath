/**
 * NodeCard — the selected node's card (Spec Part 5): display name, kind,
 * owner with a colour swatch (LAND only), the neighbour list from
 * manifest edges, and an empty `data-slot="satellites"` container that
 * later modules fill. Closes by × (Esc is handled by the parent).
 */

import { Icon24Dismiss } from '@vkontakte/icons';
import {
  Div,
  Group,
  Header,
  IconButton,
  SimpleCell,
  Text,
  Title,
} from '@vkontakte/vkui';

import { NODECARD_WIDTH_PX } from '../constants';
import {
  EDGE_TYPE_LABELS,
  straitMultiplierLabel,
  type NeighbourRef,
} from '../lib/adjacency';
import { displayName } from '../lib/search';
import type { MapNationDTO, MapNodeDTO } from '../types';

export interface NodeCardProps {
  node: MapNodeDTO;
  owner: MapNationDTO | null;
  neighbours: { node: MapNodeDTO; edge: NeighbourRef['edge'] }[];
  onNeighbourClick: (id: number) => void;
  onClose: () => void;
}

const KIND_LABELS: Record<MapNodeDTO['kind'], string> = {
  LAND: 'Провинция',
  SEA: 'Морская зона',
};

export function NodeCard({
  node,
  owner,
  neighbours,
  onNeighbourClick,
  onClose,
}: NodeCardProps) {
  return (
    <div
      data-testid="node-card"
      style={{
        position: 'absolute',
        top: 12,
        right: 12,
        width: NODECARD_WIDTH_PX,
        maxHeight: 'calc(100% - 24px)',
        overflowY: 'auto',
        zIndex: 2,
      }}
    >
      <Group
        header={
          <Header
            size="m"
            after={
              <IconButton aria-label="Закрыть" onClick={onClose}>
                <Icon24Dismiss />
              </IconButton>
            }
          >
            {displayName(node)}
          </Header>
        }
        style={{ background: 'var(--vkui--color_background_content)' }}
      >
        <SimpleCell disabled subtitle="Вид">
          {KIND_LABELS[node.kind]}
        </SimpleCell>
        {node.kind === 'LAND' && (
          <SimpleCell
            disabled
            subtitle="Владелец"
            before={
              owner ? (
                <div
                  aria-label={`Цвет ${owner.color_hex}`}
                  style={{
                    width: 20,
                    height: 20,
                    borderRadius: 5,
                    background: owner.color_hex,
                    border: '1px solid rgba(0,0,0,0.15)',
                  }}
                />
              ) : undefined
            }
          >
            {owner ? owner.name : 'Свободна'}
          </SimpleCell>
        )}

        <Div>
          <Title level="3">Соседи</Title>
          {neighbours.length === 0 && (
            <Text style={{ opacity: 0.6 }}>Нет связанных узлов</Text>
          )}
          {neighbours.map(({ node: neighbour, edge }) => {
            const mult = straitMultiplierLabel(edge);
            return (
              <SimpleCell
                key={neighbour.id}
                data-neighbour-id={neighbour.id}
                onClick={() => onNeighbourClick(neighbour.id)}
                subtitle={
                  EDGE_TYPE_LABELS[edge.type] +
                  (edge.name ? ` (${edge.name})` : '') +
                  (mult ? `, ${mult}` : '')
                }
              >
                {displayName(neighbour)}
              </SimpleCell>
            );
          })}
        </Div>

        {/* Reserved for satellite modules (armies, economy, …). */}
        <div data-slot="satellites" />
      </Group>
    </div>
  );
}
