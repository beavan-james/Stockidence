/**
 * TanStack Query hooks over the API client.
 *
 * useRating replicates the Reflex poll loop: while the pipeline reports
 * pending/refreshing, refetch every 10s up to 60 attempts (~10 min, enough
 * for a cold full-history backfill), then stop and let the page offer a
 * manual re-check.
 */

import { useQuery } from "@tanstack/react-query";

import { client } from "@/lib/api";
import type {
  Commodity,
  ComponentSpec,
  EarningsRelease,
  IpoListing,
  MacroMetric,
  Movers,
  ModelWeight,
  NewsEnvelope,
  PriceBar,
  Quote,
  RankingsEnvelope,
  Rating,
  RatingSource,
  TechnicalStats,
} from "@/types/api";

export const POLL_INTERVAL_MS = 10_000;
export const POLL_MAX_ATTEMPTS = 60;

function shouldPoll(source: RatingSource | undefined, attempts: number): boolean {
  if (source !== "pending" && source !== "refreshing") return false;
  return attempts < POLL_MAX_ATTEMPTS;
}

export function useRating(ticker: string | undefined) {
  return useQuery<Rating>({
    enabled: Boolean(ticker),
    queryKey: ["rating", ticker?.toUpperCase()],
    queryFn: ({ signal }) => client.rating(ticker!.toUpperCase(), signal),
    retry: false,
    refetchInterval: (query) => {
      const rating = query.state.data as Rating | undefined;
      const attempts = query.state.dataUpdateCount;
      return shouldPoll(rating?.source, attempts) ? POLL_INTERVAL_MS : false;
    },
  });
}

export function useMovers() {
  return useQuery<Movers>({ queryKey: ["movers"], queryFn: () => client.movers() });
}

export function useModelWeights() {
  return useQuery<ModelWeight[]>({
    queryKey: ["model-weights"],
    queryFn: () => client.modelWeights(),
    staleTime: 5 * 60_000,
  });
}

export function useRankings() {
  return useQuery<RankingsEnvelope>({
    queryKey: ["rankings"],
    queryFn: () => client.rankings(),
    // Quarterly snapshot: refetch at most hourly.
    staleTime: 60 * 60_000,
  });
}

export function useNews(params: { ticker?: string; dateFrom?: string; dateTo?: string; page?: number; pageSize?: number }) {
  return useQuery<NewsEnvelope>({
    queryKey: ["news", params],
    queryFn: () => client.news(params),
    placeholderData: (previous) => previous,
    // Pages are cheap now (SQL LIMIT/OFFSET) but identical params shouldn't refetch.
    staleTime: 5 * 60_000,
  });
}

export function useQuote(ticker: string | undefined) {
  return useQuery<Quote | null>({
    enabled: Boolean(ticker),
    queryKey: ["quote", ticker],
    queryFn: () => client.quote(ticker!),
    staleTime: 30_000,
    // Quotes land mid-refresh (before the rating snapshot), so keep polling:
    // the badge and portfolio rows pick the fresh row up without a remount.
    refetchInterval: 60_000,
  });
}

export function usePriceHistory(ticker: string | undefined, months = 12) {
  return useQuery<PriceBar[]>({
    enabled: Boolean(ticker),
    queryKey: ["prices", ticker, months],
    queryFn: () => client.prices(ticker!, months),
    // Weekly bars barely move intraday.
    staleTime: 60 * 60_000,
  });
}

export function useTechnicals(ticker: string | undefined) {
  return useQuery<TechnicalStats | null>({
    enabled: Boolean(ticker),
    queryKey: ["technicals", ticker],
    queryFn: () => client.technicals(ticker!),
    // Derived once a day from landed bars.
    staleTime: 60 * 60_000,
  });
}

export function useComponentSpec() {
  return useQuery<ComponentSpec>({
    queryKey: ["component-spec"],
    queryFn: () => client.componentSpec(),
    staleTime: Infinity,
  });
}

export function useMacro() {
  return useQuery<MacroMetric[]>({ queryKey: ["macro"], queryFn: () => client.macro() });
}

export function useCommodities() {
  return useQuery<Commodity[]>({
    queryKey: ["commodities"],
    queryFn: () => client.commodities(),
  });
}

export function useIpos(limit = 50) {
  return useQuery<IpoListing[]>({
    queryKey: ["ipos", limit],
    queryFn: () => client.ipos(limit),
  });
}

export function useEarnings(limit = 50) {
  return useQuery<EarningsRelease[]>({
    queryKey: ["earnings", limit],
    queryFn: () => client.earnings(limit),
  });
}
