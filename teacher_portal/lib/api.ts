let token: string | null = null;
let refresh: Promise<boolean> | null = null;
let signingOut = false;
let logout: Promise<void> | null = null;
let generation = 0;
export function setToken(value: string | null) {
  generation++;
  token = value;
}
export class APIError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}
export async function restoreSession(): Promise<boolean> {
  if (signingOut) return false;
  if (!refresh)
    refresh = (async () => {
      const startedGeneration = generation;
      try {
        const response = await fetch('/api/backend/auth/refresh', {
          method: 'POST',
          credentials: 'same-origin',
        });
        if (generation !== startedGeneration) return false;
        if (!response.ok) {
          token = null;
          return false;
        }
        const data = (await response.json()) as { access_token?: unknown };
        if (generation !== startedGeneration) return false;
        if (typeof data.access_token !== 'string') {
          token = null;
          return false;
        }
        token = data.access_token;
        return true;
      } catch {
        return false;
      } finally {
        refresh = null;
      }
    })();
  return refresh;
}

export function logoutSession(): Promise<void> {
  if (logout) return logout;
  signingOut = true;
  logout = (async () => {
    // The rotated HttpOnly cookie must arrive before logout revokes it. Merely
    // ignoring a late JS token would still let that cookie restore the session.
    if (refresh) await refresh;
    await api('/auth/logout', { method: 'POST' }, false);
    setToken(null);
  })().finally(() => {
    signingOut = false;
    logout = null;
  });
  return logout;
}
export async function api<T>(
  path: string,
  init: RequestInit = {},
  retry = true,
): Promise<T> {
  const headers = new Headers(init.headers);
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (typeof init.body === 'string')
    headers.set('Content-Type', 'application/json');
  let response: Response;
  try {
    response = await fetch(`/api/backend${path}`, {
      ...init,
      headers,
      credentials: 'same-origin',
      cache: 'no-store',
    });
  } catch {
    throw new APIError(
      0,
      'Ekki náðist samband. Athugaðu tenginguna og reyndu aftur.',
    );
  }
  if (response.status === 401 && retry && !path.startsWith('/auth/')) {
    if (await restoreSession()) return api<T>(path, init, false);
    if (typeof window !== 'undefined' && !signingOut)
      window.dispatchEvent(new Event('ratatoskur:session-expired'));
  }
  if (!response.ok) {
    const data = (await response.json().catch(() => ({}))) as {
      detail?: unknown;
    };
    const message =
      response.status === 403
        ? 'Þessi aðgangur hefur ekki kennaraheimild fyrir þessi gögn.'
        : response.status === 401
          ? 'Innskráning mistókst eða rann út. Skráðu þig inn aftur.'
          : response.status >= 500
            ? 'Ekki tókst að ljúka aðgerðinni. Reyndu aftur eftir augnablik.'
            : typeof data.detail === 'string'
              ? data.detail
              : 'Athugaðu innsláttinn og reyndu aftur.';
    throw new APIError(response.status, message);
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
