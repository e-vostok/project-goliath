/**
 * ActionTextCell — `action_text` column: a button-looking link; a click
 * runs the cell's `action` ("<handler>:<arg>") through the cell action
 * registry (Spec 5.6). No handler registered — the click does nothing.
 */

import { isActionTextCell, type RegistryCell } from '../../types';
import { runCellAction } from '../../lib/cellActions';
import { REGISTRY_TEXTS } from '../../texts';

export function ActionTextCell({ value }: { value: RegistryCell }) {
  const cell = isActionTextCell(value) ? value : null;

  if (!cell) {
    return <span>{REGISTRY_TEXTS.emptyValue}</span>;
  }

  return (
    <button
      type="button"
      title={cell.text}
      onClick={() => runCellAction(cell.action)}
      style={{
        display: 'block',
        width: '100%',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
        border: 0,
        background: 'transparent',
        padding: 0,
        font: 'inherit',
        textAlign: 'left',
        cursor: 'pointer',
        color: 'var(--vkui--color_text_accent)',
      }}
    >
      {cell.text}
    </button>
  );
}
