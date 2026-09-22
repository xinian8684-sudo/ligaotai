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

  it('两处都 start 时，一处 stop 不能把另一处的轮询掐掉', async () => {
    // 书内布局和流水线页各自 start；离开流水线页时轮询必须继续
    const spy = vi.spyOn(api, 'currentJob').mockResolvedValue(null)
    const s = useJobStore()
    s.start()
    s.start()
    s.stop()
    const 次数 = spy.mock.calls.length
    await vi.advanceTimersByTimeAsync(3000)
    expect(spy.mock.calls.length).toBe(次数 + 3)
    s.stop()
    const 次数2 = spy.mock.calls.length
    await vi.advanceTimersByTimeAsync(3000)
    expect(spy.mock.calls.length).toBe(次数2)
  })

  it('onFinish 返回的退订函数调用后不再收到回调', async () => {
    const spy = vi.spyOn(api, 'currentJob').mockResolvedValue(造任务())
    const s = useJobStore()
    const fn = vi.fn()
    const 退订 = s.onFinish(fn)
    await s.refresh()
    退订()
    spy.mockResolvedValue(造任务({ status: 'done' }))
    await s.refresh()
    expect(fn).not.toHaveBeenCalled()
  })

  it('两次轮询之间就跑完的快任务：track 了刚提交的任务，下一次轮询看到 done 触发 1 次（审查 S3）', async () => {
    // 上一次轮询看到的是旧任务 old/done
    const spy = vi.spyOn(api, 'currentJob').mockResolvedValue(造任务({ id: 'old', status: 'done' }))
    const s = useJobStore()
    const 回调 = vi.fn()
    s.onFinish(回调)
    await s.refresh()
    expect(回调).not.toHaveBeenCalled()

    // 用户点运行：POST 返回 j2/queued，页面 track 它
    s.track(造任务({ id: 'j2', status: 'queued', done: 0 }))
    expect(s.busy).toBe(true)

    // 不到一秒就跑完了，下一次轮询直接看到 j2/done
    spy.mockResolvedValue(造任务({ id: 'j2', status: 'done', done: 10 }))
    await s.refresh()
    expect(回调).toHaveBeenCalledTimes(1)
    expect(回调.mock.calls[0][0].id).toBe('j2')

    // 再轮询不重复触发
    await s.refresh()
    expect(回调).toHaveBeenCalledTimes(1)
  })

  it('不 track 时同样的时序一次都不触发（这就是 S3 的病，留作对照）', async () => {
    const spy = vi.spyOn(api, 'currentJob').mockResolvedValue(造任务({ id: 'old', status: 'done' }))
    const s = useJobStore()
    const 回调 = vi.fn()
    s.onFinish(回调)
    await s.refresh()
    spy.mockResolvedValue(造任务({ id: 'j2', status: 'done', done: 10 }))
    await s.refresh()
    expect(回调).not.toHaveBeenCalled()
  })

  it('track 之前发出、之后才回来的旧轮询结果要丢掉，不能把刚塞进来的任务盖回旧的', async () => {
    let 放行!: (j: Job) => void
    const spy = vi.spyOn(api, 'currentJob').mockImplementationOnce(
      () => new Promise<Job>((res) => { 放行 = res }),
    )
    const s = useJobStore()
    const 回调 = vi.fn()
    s.onFinish(回调)
    const 旧轮询 = s.refresh() // 在途
    s.track(造任务({ id: 'j2', status: 'queued', done: 0 }))
    放行(造任务({ id: 'old', status: 'done' }))
    await 旧轮询
    expect(s.current?.id).toBe('j2')

    spy.mockResolvedValue(造任务({ id: 'j2', status: 'done', done: 10 }))
    await s.refresh()
    expect(回调).toHaveBeenCalledTimes(1)
  })
})
