/**
 * NationsSection — «Государства» (0.11.0 unit 8b): the view
 * switcher over three screens — the list (screen 03,
 * NationsList.tsx), the create page (screen 03c, NationCreate.tsx)
 * and the edit page (screen 03b, NationEdit.tsx). Shared building
 * blocks live in shared.tsx, the edit form's pure diff model in
 * nationEdit.ts. Bumping reloadKey after a successful create or
 * edit refreshes the list.
 */

import { useState } from 'react';

import type { AdminNationDTO } from '../../../shared/types';
import { NationCreate } from './NationCreate';
import { NationEdit } from './NationEdit';
import { NationsList } from './NationsList';

type View = 'list' | 'create' | { edit: AdminNationDTO };

export function NationsSection() {
  const [view, setView] = useState<View>('list');
  const [reloadKey, setReloadKey] = useState(0);

  const backToList = (changed: boolean) => {
    if (changed) {
      setReloadKey((key) => key + 1);
    }
    setView('list');
  };

  if (view === 'create') {
    return <NationCreate onDone={backToList} />;
  }
  if (view !== 'list') {
    return <NationEdit nation={view.edit} onDone={backToList} />;
  }
  return (
    <NationsList
      key={reloadKey}
      onCreate={() => setView('create')}
      onEdit={(nation) => setView({ edit: nation })}
    />
  );
}
