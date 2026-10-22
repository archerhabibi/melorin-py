import type { paths } from './schema';

export type { paths, components, operations } from './schema';

type Method = 'get' | 'post' | 'put' | 'patch' | 'delete';

/** Paths that define `M` (the generated schema marks absent methods as `never`). */
export type PathsWith<M extends Method> = {
  [P in keyof paths]: paths[P][M] extends object ? P : never;
}[keyof paths];

type Op<P extends keyof paths, M extends Method> = paths[P][M];

type Defined<T> = Exclude<T, undefined | never>;

export type ResponseBody<P extends keyof paths, M extends Method> =
  Op<P, M> extends { responses: infer R }
    ? R extends { 200: { content: { 'application/json': infer B } } }
      ? B
      : R extends { 201: { content: { 'application/json': infer B } } }
        ? B
        : unknown
    : unknown;

export type RequestBody<P extends keyof paths, M extends Method> =
  Defined<Op<P, M>> extends { requestBody?: { content: { 'application/json': infer B } } } ? B : never;

type ParamsOf<P extends keyof paths, M extends Method> = Defined<Op<P, M>> extends { parameters: infer Q }
  ? { path?: Q extends { path?: infer X } ? Defined<X> : never; query?: Q extends { query?: infer Y } ? Defined<Y> : never }
  : never;

export interface RequestInitOf<P extends keyof paths, M extends Method> {
  params?: ParamsOf<P, M>;
  body?: [RequestBody<P, M>] extends [never] ? never : RequestBody<P, M>;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

export type ApiResult<P extends keyof paths, M extends Method> =
  | { data: ResponseBody<P, M>; error: undefined; response: Response }
  | { data: undefined; error: unknown; response: Response };

export interface ApiClientOptions {
  baseUrl?: string;
  getAccessToken?: () => string | null | undefined;
  refresh?: () => Promise<boolean>;
  fetch?: typeof fetch;
  credentials?: RequestCredentials;
}

export interface ApiClient {
  request<P extends PathsWith<M>, M extends Method>(method: M, path: P, init?: RequestInitOf<P, M>): Promise<ApiResult<P, M>>;
  get<P extends PathsWith<'get'>>(path: P, init?: RequestInitOf<P, 'get'>): Promise<ApiResult<P, 'get'>>;
  post<P extends PathsWith<'post'>>(path: P, init?: RequestInitOf<P, 'post'>): Promise<ApiResult<P, 'post'>>;
  put<P extends PathsWith<'put'>>(path: P, init?: RequestInitOf<P, 'put'>): Promise<ApiResult<P, 'put'>>;
  patch<P extends PathsWith<'patch'>>(path: P, init?: RequestInitOf<P, 'patch'>): Promise<ApiResult<P, 'patch'>>;
  delete<P extends PathsWith<'delete'>>(path: P, init?: RequestInitOf<P, 'delete'>): Promise<ApiResult<P, 'delete'>>;
}

export function buildPath(template: string, params?: Record<string, string | number>): string;
export function buildQuery(query?: Record<string, unknown>): string;
export function createApiClient(options?: ApiClientOptions): ApiClient;
