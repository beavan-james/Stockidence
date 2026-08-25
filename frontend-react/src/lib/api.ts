/** Thin typed fetch wrapper over the FastAPI layer. */

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string, options?: ErrorOptions) {
    super(message, options);
    this.status = status;
  }
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, { signal: init?.signal, ...init });
  } catch (cause) {
    throw new ApiError(0, "API unreachable", { cause });
  }
  if (!response.ok) {
    const detail = await response
      .json()
      .then((body) => body?.detail)
      .catch(() => null);
    throw new ApiError(response.status, detail ?? `HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

export const client = {
  rating: (ticker: string, signal?: AbortSignal) =>
    api<import("@/types/api").Rating>(`/api/rating/${encodeURIComponent(ticker)}`, { signal }),

  search: (q: string, limit = 8) =>
    api<import("@/types/api").Suggestion[]>(
      `/api/search?q=${encodeURIComponent(q)}&limit=${limit}`,
    ),

  quote: (ticker: string) =>
    api<import("@/types/api").Quote | null>(`/api/quote/${encodeURIComponent(ticker)}`),

  movers: () => api<import("@/types/api").Movers>("/api/movers"),

  news: (params: { ticker?: string; page?: number; pageSize?: number }) => {
    const qs = new URLSearchParams();
    if (params.ticker) qs.set("ticker", params.ticker);
    if (params.page) qs.set("page", String(params.page));
    if (params.pageSize) qs.set("page_size", String(params.pageSize));
    return api<import("@/types/api").NewsEnvelope>(`/api/news?${qs.toString()}`);
  },

  modelWeights: () => api<import("@/types/api").ModelWeight[]>("/api/model-weights"),

  componentSpec: () =>
    api<import("@/types/api").ComponentSpec>("/api/component-spec"),

  macro: () => api<import("@/types/api").MacroMetric[]>("/api/macro"),

  commodities: () => api<import("@/types/api").Commodity[]>("/api/commodities"),

  ipos: (limit = 10) => api<import("@/types/api").IpoListing[]>(`/api/calendar/ipos?limit=${limit}`),

  earnings: (limit = 10) =>
    api<import("@/types/api").EarningsRelease[]>(`/api/calendar/earnings?limit=${limit}`),
};
