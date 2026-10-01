export interface RuntimeConfig {
  oidcAuthority: string;
  oidcClientId: string;
  apiBase: string;
}

declare global {
  interface Window {
    __CORTEX_CONFIG__?: Partial<RuntimeConfig>;
  }
}

export const config: RuntimeConfig = {
  oidcAuthority: window.__CORTEX_CONFIG__?.oidcAuthority ?? "http://localhost:8380/realms/cortex",
  oidcClientId: window.__CORTEX_CONFIG__?.oidcClientId ?? "cortex-web",
  apiBase: window.__CORTEX_CONFIG__?.apiBase ?? "",
};
