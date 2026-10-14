"use client";

import useSWR, { type SWRConfiguration } from "swr";
import { fetcher } from "@/lib/api";
import type { StatusResponse } from "@/lib/types";

/** Bot + auth + store status. One shared SWR key, so the shell and the Bot tab share a single poll. */
export function useStatus(refreshMs = 2000) {
  return useSWR<StatusResponse>("/status", fetcher, {
    refreshInterval: refreshMs,
    keepPreviousData: true,
    errorRetryInterval: 3000,
    dedupingInterval: 1000,
  });
}

export function useApi<T>(path: string | null, config?: SWRConfiguration<T>) {
  return useSWR<T>(path, fetcher, { keepPreviousData: true, revalidateOnFocus: false, ...config });
}
