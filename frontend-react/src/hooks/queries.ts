/**
 * TanStack Query hooks over the API client.
 *
 * useRating replicates the Reflex poll loop: while the pipeline reports
 * pending/refreshing, refetch every 10s up to 30 attempts, then stop and
 * show whatever we have.
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
  Quote,
  RankingsEnvelope,
  Rating,
  RatingSource,
} from "@/types/api";

const POLL_INTERVAL_MS = 10_000;
const POLL_MAX_ATTEMPTS = 30;

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

export function useNews(params: { ticker?: string; page?: number; pageSize?: number }) {
  return useQuery<NewsEnvelope>({
    queryKey: ["news", params],
    queryFn: () => client.news(params),
    placeholderData: (previous) => previous,
  });
}

export function useQuote(ticker: string | undefined) {
  return useQuery<Quote | null>({
    enabled: Boolean(ticker),
    queryKey: ["quote", ticker],
    queryFn: () => client.quote(ticker!),
    staleTime: 30_000,
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
