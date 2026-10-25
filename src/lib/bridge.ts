import type { Connection } from "./types";

export interface KaryakartaBridge {
  getConnection(): Promise<Connection>;
  openExternal(url: string): Promise<void>;
}

declare global {
  interface Window {
    karyakarta?: KaryakartaBridge;
  }
}

export class ConnectionError extends Error {}

/**
 * Where the local service is and the secret token to talk to it.
 * Inside the desktop app the main process supplies both. For plain browser
 * development only, they can be passed in the address (?port=8765&token=...).
 */
export async function resolveConnection(): Promise<Connection> {
  if (window.karyakarta) return window.karyakarta.getConnection();
  if (import.meta.env.DEV) {
    const params = new URLSearchParams(window.location.search);
    const token = params.get("token");
    if (token) return { baseUrl: `http://127.0.0.1:${params.get("port") ?? "8765"}`, token };
  }
  throw new ConnectionError("Open Karyakarta from the desktop app. The service address was not provided.");
}

export async function openExternal(url: string): Promise<void> {
  if (window.karyakarta) await window.karyakarta.openExternal(url);
  else window.open(url, "_blank", "noopener,noreferrer");
}
