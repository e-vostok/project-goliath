/**
 * Pure helpers for the E1 probe panel: error normalisation, URL redaction,
 * whitelist picking and the browser-metrics snapshot. No React, no VK
 * Bridge — every browser global is passed in as an argument so unit tests
 * can substitute plain stub objects.
 */

export interface ErrorInfo {
  name: string;
  message: string;
  /** VK Bridge rejects with {error_type, error_data} — kept verbatim. */
  error_type?: string;
  error_data?: unknown;
}

export function toErrorInfo(e: unknown): ErrorInfo {
  if (e instanceof Error) {
    return { name: e.name, message: e.message };
  }
  if (e !== null && typeof e === 'object') {
    const record = e as Record<string, unknown>;
    if ('error_type' in record || 'error_data' in record) {
      const errorType =
        typeof record.error_type === 'string'
          ? record.error_type
          : 'VK_ERROR';
      return {
        name: errorType,
        message:
          typeof record.error_data === 'string'
            ? record.error_data
            : JSON.stringify(record.error_data ?? null),
        ...(typeof record.error_type === 'string'
          ? { error_type: record.error_type }
          : {}),
        ...(record.error_data !== undefined
          ? { error_data: record.error_data }
          : {}),
      };
    }
    return { name: 'UnknownError', message: JSON.stringify(record) };
  }
  return { name: 'UnknownError', message: String(e) };
}

/** Returns only the whitelisted keys of `obj`; absent keys become null. */
export function pickWhitelisted(
  obj: unknown,
  keys: readonly string[],
): Record<string, unknown> {
  const source =
    obj !== null && typeof obj === 'object'
      ? (obj as Record<string, unknown>)
      : {};
  const out: Record<string, unknown> = {};
  for (const key of keys) {
    out[key] = key in source ? source[key] : null;
  }
  return out;
}

export interface RedactedUrl {
  /** origin + pathname — query values and the hash never leave this function. */
  url: string;
  /** Names of query parameters only; values are dropped. */
  queryParams: string[];
}

export function redactUrl(rawUrl: string): RedactedUrl {
  try {
    const url = new URL(rawUrl);
    return {
      url: `${url.origin}${url.pathname}`,
      queryParams: [...new Set(url.searchParams.keys())],
    };
  } catch {
    return { url: '<unparseable>', queryParams: [] };
  }
}

/** §3.1 browser-side metrics — no VK Bridge data in here. */
export interface MetricsSnapshot {
  innerWidth: number | null;
  innerHeight: number | null;
  outerWidth: number | null;
  outerHeight: number | null;
  devicePixelRatio: number | null;
  screen: {
    width: number | null;
    height: number | null;
    availWidth: number | null;
    availHeight: number | null;
  };
  fullscreenEnabled: boolean | null;
  webkitFullscreenEnabled: boolean | null;
  /** window.top !== window — null if the access threw. */
  isFramed: boolean | null;
  /** document.referrer reduced to its origin; null when empty/foreign. */
  referrerOrigin: string | null;
  userAgent: string | null;
  featurePolicyFullscreen: boolean | null;
  permissionsPolicyFullscreen: boolean | null;
  clipboardAvailable: boolean;
  location: RedactedUrl;
}

function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

interface PolicyLike {
  allowsFeature?: (feature: string) => boolean;
}

function policyAllowsFullscreen(
  doc: Document,
  policyKey: 'featurePolicy' | 'permissionsPolicy',
): boolean | null {
  const policy = (doc as unknown as Record<string, unknown>)[
    policyKey
  ] as PolicyLike | null | undefined;
  if (!policy || typeof policy.allowsFeature !== 'function') {
    return null;
  }
  try {
    return policy.allowsFeature('fullscreen');
  } catch {
    return null;
  }
}

export function collectMetrics(win: Window, doc: Document): MetricsSnapshot {
  const screenLike = (win.screen ?? {}) as Partial<Screen>;
  const nav = win.navigator;

  let isFramed: boolean | null = null;
  try {
    isFramed = win.top !== win;
  } catch {
    isFramed = null;
  }

  let referrerOrigin: string | null = null;
  try {
    referrerOrigin = doc.referrer ? new URL(doc.referrer).origin : null;
  } catch {
    referrerOrigin = null;
  }

  const docAny = doc as Document & {
    webkitFullscreenEnabled?: boolean;
  };

  return {
    innerWidth: num(win.innerWidth),
    innerHeight: num(win.innerHeight),
    outerWidth: num(win.outerWidth),
    outerHeight: num(win.outerHeight),
    devicePixelRatio: num(win.devicePixelRatio),
    screen: {
      width: num(screenLike.width),
      height: num(screenLike.height),
      availWidth: num(screenLike.availWidth),
      availHeight: num(screenLike.availHeight),
    },
    fullscreenEnabled:
      typeof doc.fullscreenEnabled === 'boolean'
        ? doc.fullscreenEnabled
        : null,
    webkitFullscreenEnabled:
      typeof docAny.webkitFullscreenEnabled === 'boolean'
        ? docAny.webkitFullscreenEnabled
        : null,
    isFramed,
    referrerOrigin,
    userAgent: typeof nav?.userAgent === 'string' ? nav.userAgent : null,
    featurePolicyFullscreen: policyAllowsFullscreen(doc, 'featurePolicy'),
    permissionsPolicyFullscreen: policyAllowsFullscreen(
      doc,
      'permissionsPolicy',
    ),
    clipboardAvailable:
      typeof nav === 'object' && nav !== null && 'clipboard' in nav,
    location: redactUrl(win.location.href),
  };
}

export function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
