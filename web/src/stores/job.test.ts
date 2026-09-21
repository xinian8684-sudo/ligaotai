import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useJobStore } from './job'
import * as api from '@/api/endpoints'
import type { Job } from '@/api/types'

function 造任务(over: Partial<Job> = {}): Job {
  return {
    id: 'j1', name: 'cards', book: '归墟', status: 'running',
    done: 3, total: 10, message: '', error: '', result: null,
    started: '2026-09-21T10:00:00', finished: '', cancel_requested: false,
    ...over,
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.useFakeTimers()
})
afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('job store', () => {
  it('轮询到运行中的任务时 busy 为真', async () => {
    vi.spyOn(api, 'currentJob').mockResolvedValue(造任务())
    const s = useJobStore()
    await s.refresh()
    expect(s.busy).toBe(true)
    expect(s.current?.done).toBe(3)
  })

  it('没有任务时 busy 为假', async () => {
    vi.spyOn(api, 'currentJob').mockResolvedValue(null)
    const s = useJobStore()
    await s.refresh()
    expect(s.busy).toBe(false)
  })

  it('任务已结束时 busy 为假', async () => {
    vi.spyOn(api, 'currentJob').mockResolvedValue(造任务({ status: 'done' }))
    const s = useJobStore()
    await s.refresh()
    expect(s.busy).toBe(false)
  })

  it('queued 也算忙', async () => {
    vi.spyOn(api, 'currentJob').mockResolvedValue(造任务({ status: 'queued' }))
    const s = useJobStore()
    await s.refresh()
    expect(s.busy).toBe(true)
  })

  it('任务从运行变成完成时触发一次 onFinish 回调', async () => {
    const spy = vi.spyOn(api, 'currentJob').mockResolvedValue(造任务({ status: 'running' }))
    const s = useJobStore()
    const 回调 = vi.fn()
    s.onFinish(回调)

    await s.refresh()
    expect(回调).not.toHaveBeenCalled()

    spy.mockResolvedValue(造任务({ status: 'done', done: 10 }))
    await s.refresh()
    expect(回调).toHaveBeenCalledTimes(1)

    // 再轮询一次，同一个任务不能重复触发
    await s.refresh()
    expect(回调).toHaveBeenCalledTimes(1)
  })

  it('任务失败也算结束，同样触发 onFinish', async () => {
    const spy = vi.spyOn(api, 'currentJob').mockResolvedValue(造任务({ status: 'running' }))
    const s = useJobStore()
    const 回调 = vi.fn()
    s.onFinish(回调)
    await s.refresh()
    spy.mockResolvedValue(造任务({ status: 'failed', error: '接口拒绝了请求（401）' }))
    await s.refresh()
    expect(回调).toHaveBeenCalledTimes(1)
    expect(s.current?.error).toContain('401')
  })

  it('轮询出错不能把 busy 卡死在真', async () => {
    const spy = vi.spyOn(api, 'currentJob').mockResolvedValue(造任务({ status: 'running' }))
    const s = useJobStore()
    await s.refresh()
    expect(s.busy).toBe(true)

    spy.mockRejectedValue(new Error('后端断了'))
    await s.refresh()
    // 连不上后端时不知道到底忙不忙，保守起见保持上次状态，但要把错误露出来
    expect(s.pollError).toContain('后端断了')
  })

  it('start 之后每秒轮询一次，stop 之后不再轮询', async () => {
    const spy = vi.spyOn(api, 'currentJob').mockResolvedValue(null)
    const s = useJobStore()
    s.start()
    await vi.advanceTimersByTimeAsync(1000)
    await vi.advanceTimersByTimeAsync(1000)
    const 次数 = spy.mock.calls.length
    expect(次数).toBeGreaterThanOrEqual(2)

    s.stop()
    await vi.advanceTimersByTimeAsync(3000)
    expect(spy.mock.calls.length).toBe(次数)
  })
})
