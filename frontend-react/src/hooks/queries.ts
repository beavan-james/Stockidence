/** TanStack Query hooks over the API client. */

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { ApiError, client } from "@/lib/api";
import type {
  Commodity,
  EarningsRelease,
  IpoListing,
  MacroMetric,
  ModelOverview,
  Movers,
  NewsEnvelope,
  Quote,
  RankingDetail,
  RankingsEnvelope,
} from "@/types/api";

export function useMovers() {
  return useQuery<Movers>({ queryKey: ["movers"], queryFn: () => client.movers() });
}

export function useRankings() {
  return useQuery<RankingsEnvelope>({
    queryKey: ["rankings"],
    queryFn: () => client.rankings(),
    // Quarterly snapshot: refetch at most hourly.
    staleTime: 60 * 60_000,
  });
}

/** Whether a ticker is in the latest ranking (only those have a stock page). */
export function useIsRanked(): (ticker: string | null | undefined) => boolean {
  const rankings = useRankings();
  const set = useMemo(
    () => new Set((rankings.data?.items ?? []).map((r) => r.ticker)),
    [rankings.data],
  );
  return (ticker) => Boolean(ticker && set.has(ticker.toUpperCase()));
}

export function useRankingDetail(ticker: string | undefined) {
  return useQuery<RankingDetail>({
    enabled: Boolean(ticker),
    queryKey: ["ranking-detail", ticker],
    queryFn: () => client.rankingDetail(ticker!),
    staleTime: 60 * 60_000,
    // 404 = not in this quarter's ranking: a real answer, not a blip.
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 2,
  });
}

export function useModelOverview() {
  return useQuery<ModelOverview>({
    queryKey: ["model-overview"],
    queryFn: () => client.modelOverview(),
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
    // Quotes refresh through the day; keep the badge current.
    refetchInterval: 60_000,
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
