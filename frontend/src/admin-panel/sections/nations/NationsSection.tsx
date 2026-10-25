/**
 * NationsSection — «Государства» (0.11.0 units 8b/8c): the view
 * switcher over three screens — the list (screen 03,
 * NationsList.tsx), the create page (screen 03c, NationCreate.tsx)
 * and the edit page (screen 03b, NationEdit.tsx) — plus the
 * screen-03d deletion popup (NationDeletePopup.tsx) that floats over
 * the list. Shared building blocks live in shared.tsx, the edit
 * form's pure diff model in nationEdit.ts. Bumping reloadKey after a
 * successful create, edit or delete refreshes the list.
 */

import { useState } from 'react';

import type { AdminNationDTO } from '../../../shared/types';
import { useNotice } from '../../../shared/ui/Notice';
import { NationCreate } from './NationCreate';
import { NationDeletePopup } from './NationDeletePopup';
import { NationEdit } from './NationEdit';
import { NationsList } from './NationsList';

type View = 'list' | 'create' | { edit: AdminNationDTO };

export function NationsSection() {
  const notify = useNotice();
  const [view, setView] = useState<View>('list');
  const [reloadKey, setReloadKey] = useState(0);
  const [deleteTarget, setDeleteTarget] = useState<AdminNationDTO | null>(null);

  const backToList = (changed: boolean) => {
    if (changed) {
      setReloadKey((key) => key + 1);
    }
    setView('list');
  };

  const deleted = (shortName: string) => {
    setDeleteTarget(null);
    setReloadKey((key) => key + 1);
    notify(`Государство «${shortName}» удалено.`);
  };

  if (view === 'create') {
    return <NationCreate onDone={backToList} />;
  }
  if (view !== 'list') {
    return <NationEdit nation={view.edit} onDone={backToList} />;
  }
  return (
    <>
      <NationsList
        key={reloadKey}
        onCreate={() => setView('create')}
        onEdit={(nation) => setView({ edit: nation })}
        onDelete={setDeleteTarget}
      />
      {deleteTarget !== null && (
        <NationDeletePopup
          target={deleteTarget}
          onClose={() => setDeleteTarget(null)}
          onDeleted={deleted}
        />
      )}
    </>
  );
}
