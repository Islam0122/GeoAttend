import { useMutation, useQuery, useQueryClient, type UseQueryOptions } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, type RequestOptions } from "./client";

type Params = RequestOptions["params"];

/** GET helper keyed by path + params. */
export function useGet<T>(path: string | null, params?: Params, options?: Partial<UseQueryOptions<T>>) {
  return useQuery<T>({ queryKey: [path, params ?? {}], queryFn: () => api<T>(path!, { params }), enabled: !!path, ...options });
}

/** Mutation helper that toasts errors and invalidates the given query prefixes on success. */
export function useSend<TBody = unknown, TOut = unknown>(method: string, path: string | ((b: TBody) => string), invalidate: string[] = [], success?: string) {
  const qc = useQueryClient();
  return useMutation<TOut, Error, TBody>({
    mutationFn: (body) => api<TOut>(typeof path === "function" ? path(body) : path, { method, body: method === "DELETE" ? undefined : body }),
    onSuccess: () => {
      invalidate.forEach((p) => qc.invalidateQueries({ predicate: (q) => String(q.queryKey[0] ?? "").startsWith(p) }));
      if (success) toast.success(success);
    },
    onError: (e) => toast.error(e.message),
  });
}
