/**
 * Field set (UI Spec 6, элемент 11) — TextArea keeps `resize:
 * vertical` but can never be dragged to a sliver: `min-height` pins
 * it to its rows (`calc(rows * 20px + 16px)`) and `max-height` caps
 * the drag at 320 px (acceptance 12b).
 */

import { render, screen } from '@testing-library/react';

import { TextArea } from '../fields';

describe('TextArea', () => {
  it('resizes only vertically, never below its rows height or past 320px', () => {
    render(
      <TextArea
        id="bio"
        label="Биография"
        value=""
        rows={3}
        onChange={() => undefined}
      />,
    );
    const area = screen.getByLabelText('Биография') as HTMLTextAreaElement;
    expect(area.style.resize).toBe('vertical');
    expect(area.style.minHeight).toBe('calc(3 * 20px + 16px)');
    expect(area.style.maxHeight).toBe('320px');
  });

  it('the description size (rows=2) gets its own min-height', () => {
    render(
      <TextArea
        id="desc"
        label="Описание"
        value=""
        rows={2}
        onChange={() => undefined}
      />,
    );
    const area = screen.getByLabelText('Описание') as HTMLTextAreaElement;
    expect(area.style.minHeight).toBe('calc(2 * 20px + 16px)');
    expect(area.style.resize).toBe('vertical');
  });
});
