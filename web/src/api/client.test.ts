import { describe, it, expect, vi, afterEach } from 'vitest'
import { request, ApiError } from './client'

function 假响应(status: number, body: unknown, contentType = 'application/json') {
  return new Response(typeof body === 'string' ? body : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': contentType },
  })
}

afterEach(() => { vi.unstubAllGlobals() })

describe('request', () => {
  it('成功时返回解析后的 JSON', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(假响应(200, { ok: true })))
    await expect(request('/health')).resolves.toEqual({ ok: true })
  })

  it('路径自动拼上 /api 前缀', async () => {
    const f = vi.fn().mockResolvedValue(假响应(200, {}))
    vi.stubGlobal('fetch', f)
    await request('/books')
    expect(f.mock.calls[0][0]).toBe('/api/books')
  })

  it('出错时把后端的 detail 原样带出来', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      假响应(500, { detail: '场景文件读不了：场景/S-0012.json' })
    ))
    await expect(request('/books/x/scenes')).rejects.toThrow('场景文件读不了：场景/S-0012.json')
  })

  it('detail 不是字符串时也不能丢信息', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      假响应(422, { detail: [{ loc: ['body', 'title'], msg: '不能为空' }] })
    ))
    const e = (await request('/books').catch((x) => x)) as ApiError
    expect(e).toBeInstanceOf(ApiError)
    expect(e.detail).toContain('不能为空')
  })

  it('返回的不是 JSON 时（比如 SPA 兜底发回了 HTML）也要报出来', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      假响应(404, '<!doctype html><title>理稿台</title>', 'text/html')
    ))
    const e = (await request('/没有这个接口').catch((x) => x)) as ApiError
    expect(e).toBeInstanceOf(ApiError)
    expect(e.status).toBe(404)
  })

  it('ApiError 带得上 status，界面才能区分 409 忙碌和别的错', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      假响应(409, { detail: '已有任务在跑：cards（归墟）' })
    ))
    const e = (await request('/books/x/steps/cards/run', { method: 'POST' }).catch((x) => x)) as ApiError
    expect(e.status).toBe(409)
    expect(e.detail).toContain('已有任务在跑')
  })
})
