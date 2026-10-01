/**
 * useAdminProbe — one silent GET /admin/me per session token.
 *
 * Any failure (403 ADMIN_REQUIRED, 401, network) resolves to isAdmin=false
 * with no banner and no UI flash: the admin block simply never renders for
 * regular players.
 */

import { useEffect, useState } from 'react';

import { api } from '../shared/api-client';
import { useSession } from '../modules/00_core/hooks/useAuth';

export function useAdminProbe(): boolean {
  const { token } = useSession();
  const [isAdmin, setIsAdmin] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    api
      .adminMe(token, controller.signal)
      .then((response) => {
        if (!controller.signal.aborted) {
          setIsAdmin(response.is_admin === true);
        }
      })
      .catch(() => {
        // Not an admin (or unreachable) — stay silent by design.
      });
    return () => controller.abort();
  }, [token]);

  return isAdmin;
}
