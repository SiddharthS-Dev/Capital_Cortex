import { UserManager, WebStorageStateStore, type User } from "oidc-client-ts";
import { config } from "./config";

/** OIDC authorization code + PKCE against Keycloak. Tokens live in sessionStorage (cleared with the tab). */
export const userManager = new UserManager({
  authority: config.oidcAuthority,
  client_id: config.oidcClientId,
  redirect_uri: `${window.location.origin}/auth/callback`,
  post_logout_redirect_uri: `${window.location.origin}/`,
  response_type: "code",
  scope: "openid profile email",
  automaticSilentRenew: true, // uses the rotating refresh token (15-min access tokens, §10)
  userStore: new WebStorageStateStore({ store: window.sessionStorage }),
});

export async function currentUser(): Promise<User | null> {
  const u = await userManager.getUser();
  return u && !u.expired ? u : null;
}

export function login(returnTo = window.location.pathname + window.location.search) {
  return userManager.signinRedirect({ state: { returnTo } });
}

/** Step-up for approvals: force a fresh login (password + OTP), so auth_time is recent (§10). */
export function stepUp(returnTo = window.location.pathname + window.location.search) {
  return userManager.signinRedirect({ state: { returnTo }, max_age: 0, prompt: "login" });
}

export function logout() {
  return userManager.signoutRedirect();
}
