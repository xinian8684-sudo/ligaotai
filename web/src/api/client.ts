export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
  ) {
    super(detail)
    this.name = 'ApiError'
  }
}

/** 把后端的错误信息挖出来。detail 可能是字符串、也可能是 FastAPI 的校验错误数组。 */
async function 挖错误(r: Response): Promise<string> {
  const text = await r.text()
  try {
    const body = JSON.parse(text)
    const d = body?.detail
    if (typeof d === 'string') return d
    if (d !== undefined) return JSON.stringify(d)
    return text || `HTTP ${r.status}`
  } catch {
    // 不是 JSON：可能是 SPA 兜底发回的 HTML，别把整页塞进错误信息
    return r.status === 404 ? `没有这个接口（HTTP 404）` : `HTTP ${r.status}`
  }
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!r.ok) throw new ApiError(r.status, await 挖错误(r))
  if (r.status === 204) return undefined as T
  return (await r.json()) as T
}

export function get<T>(path: string): Promise<T> {
  return request<T>(path)
}

export function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })
}

export function put<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: 'PUT', body: JSON.stringify(body) })
}
