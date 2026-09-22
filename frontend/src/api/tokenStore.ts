/**
 * Browser-side storage for the TVBFundRadar bearer token.
 *
 * The token is deliberately kept in `sessionStorage` (not `localStorage`): it
 * lives only for the browser tab/session and disappears when the tab closes,
 * so a token is never persisted for an attacker to recover later. The API
 * client reads from this single source of truth on every request, so there is
 * no duplicated token state to keep in sync.
 */
const TOKEN_KEY = "tvbfundradar_session_token";

export function getSessionToken(): string | null {
  try {
    return window.sessionStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setSessionToken(token: string | null): void {
  try {
    if (token === null) {
      window.sessionStorage.removeItem(TOKEN_KEY);
    } else {
      window.sessionStorage.setItem(TOKEN_KEY, token);
    }
  } catch {
    // Storage unavailable (private mode / blocked): the session simply cannot
    // be restored; the user signs in again.
  }
}