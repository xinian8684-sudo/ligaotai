import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import TimelinePanel from './TimelinePanel.vue'
import * as api from '@/api/endpoints'
import type { Job, TimelineFile } from '@/api/types'
import { useJobStore } from '@/stores/job'

const stubs = { RouterLink: { template: '<a :to="to"><slot /></a>', props: ['to'] } }
const job: Job = { id: 'j', name: 'timeline', book: 'x', status: 'queued', done: 0, total: 1, message: '',
  error: '', result: null, started: '', finished: '', cancel_requested: false }

function 造(over: Partial<TimelineFile> = {}): TimelineFile {
  return {
    never_run: false, stale: false,
    stats: { placed: 100, unplaced: 3, a_suspects: 4, a_capped: 0, refs_asked: 9, refs_no_candidate: 2, refs_all_before: 5 },
    conflicts: [
      { id: 'T-001', kind: 'A', who: '劉公', ref: null, scenes: ['S-0021', 'S-0046'], pos: [12, 30],
        quotes: ['劉公已死', '劉公道'], reason: '在说话[S-0046]', status: '在场', verdict: null },
      { id: 'T-002', kind: 'C', who: null, ref: '那日比箭之事', scenes: ['S-0014', 'S-0127'], pos: [3, 5],
        quotes: ['那日比箭之事', '托付刘电'], reason: '比箭在后[S-0127]', status: '', verdict: { kind: 'ignore', at: 'x' } },
    ],
    ...over,
  }
}

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.restoreAllMocks())

describe('TimelinePanel', () => {
  it('没跑过：说明 + 检查按钮', async () => {
    vi.spyOn(api, 'getTimeline').mockResolvedValue({ conflicts: [], never_run: true, stale: false })
    const run = vi.spyOn(api, 'runTimeline').mockResolvedValue(job)
    const w = mount(TimelinePanel, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="时间线空态"]').exists()).toBe(true)
    await w.find('[data-test="检查时间线"]').trigger('click')
    expect(run).toHaveBeenCalledWith('x')
  })

  it('统计行、默认只看待看、类型标签、两场位置', async () => {
    vi.spyOn(api, 'getTimeline').mockResolvedValue(造())
    const w = mount(TimelinePanel, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="时间线统计"]').text()).toContain('待看 1')
    expect(w.find('[data-test="时间线统计"]').text()).toContain('已忽略 1')
    expect(w.find('[data-test="时间线统计"]').text()).toContain('3 块没有故事位置')
    expect(w.find('[data-test="冲突-T-001"]').text()).toContain('人死了又出场')
    expect(w.find('[data-test="冲突-T-001"]').text()).toContain('第 13 位')  // pos[0] 从 0 数，显示 +1
    expect(w.find('[data-test="冲突-T-001"]').text()).toContain('第 31 位')  // W8：pos[1] 也要 +1（pos=[12,30]）
    expect(w.find('[data-test="冲突-T-002"]').exists()).toBe(false)         // 已忽略，默认不显示
    await w.find('[data-test="看全部"]').trigger('click')
    expect(w.find('[data-test="冲突-T-002"]').text()).toContain('提前知道后面的事')
  })

  it('裁决：点了调接口，撤销传 null；排错了显示去归线页的链接', async () => {
    const d = 造()
    vi.spyOn(api, 'getTimeline').mockImplementation(async () => d)
    const put = vi.spyOn(api, 'putTimelineVerdict').mockImplementation(async (_n, tid, kind) => {
      const c = d.conflicts.find((x) => x.id === tid)!
      c.verdict = kind ? { kind, at: 'y' } : null
      return c
    })
    const w = mount(TimelinePanel, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="裁决-T-001-order_error"]').trigger('click')
    await flushPromises()
    expect(put).toHaveBeenCalledWith('x', 'T-001', 'order_error')
    await w.find('[data-test="看全部"]').trigger('click')
    expect(w.find('[data-test="冲突-T-001"] [data-test="去归线页"]').exists()).toBe(true)
    await w.find('[data-test="撤销-T-001"]').trigger('click')
    await flushPromises()
    expect(put).toHaveBeenLastCalledWith('x', 'T-001', null)
  })

  it('过期提示、失败批次提示', async () => {
    vi.spyOn(api, 'getTimeline').mockResolvedValue(造({ stale: true, failed: [{ call: 'death/0', error: '坏了' }] }))
    const w = mount(TimelinePanel, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="时间线过期"]').exists()).toBe(true)
    expect(w.text()).toContain('1 批模型没给出结果')
  })

  it('过期原因：上游文件读不了时显示 stale_reason', async () => {
    vi.spyOn(api, 'getTimeline').mockResolvedValue(造({ stale: true, stale_reason: '场景文件读不了：S-0001.md（……）' }))
    const w = mount(TimelinePanel, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="时间线过期"]').text()).toContain('场景文件读不了：S-0001.md')
  })

  it('任务进行中按钮禁用', async () => {
    vi.spyOn(api, 'getTimeline').mockResolvedValue(造())
    vi.spyOn(api, 'runTimeline').mockResolvedValue(job)
    const w = mount(TimelinePanel, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="检查时间线"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-test="检查时间线"]').attributes('disabled')).toBeDefined()
    expect(w.find('[data-test="裁决-T-001-ignore"]').attributes('disabled')).toBeDefined()
  })

  it('W1：去归线页链接指向 pipeline/threads', async () => {
    const d = 造()
    vi.spyOn(api, 'getTimeline').mockImplementation(async () => d)
    vi.spyOn(api, 'putTimelineVerdict').mockImplementation(async (_n, tid, kind) => {
      const c = d.conflicts.find((x) => x.id === tid)!
      c.verdict = kind ? { kind, at: 'y' } : null
      return c
    })
    const w = mount(TimelinePanel, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="裁决-T-001-order_error"]').trigger('click')
    await flushPromises()
    await w.find('[data-test="看全部"]').trigger('click')  // 裁决后默认过滤掉了，切到看全部才能看见
    const link = w.find('[data-test="冲突-T-001"] [data-test="去归线页"]')
    expect(link.attributes('to')).toBe('/b/x/pipeline/threads')
  })

  it('W2/S7：0 条冲突时显示没有查出冲突，即使还在只看待看模式', async () => {
    vi.spyOn(api, 'getTimeline').mockResolvedValue({ conflicts: [], never_run: false, stale: false, stats: {} } as never)
    const w = mount(TimelinePanel, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="结果为空"]').text()).toBe('没有查出冲突。')
  })

  it('W2/S7：过滤后为空但总数不为0时显示没有待看的了', async () => {
    const d = 造()
    d.conflicts.forEach((c) => { c.verdict = { kind: 'ignore', at: 'x' } })  // 全部已裁决，默认过滤后为空
    vi.spyOn(api, 'getTimeline').mockResolvedValue(d)
    const w = mount(TimelinePanel, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="结果为空"]').text()).toBe('没有待看的了。')
  })

  it('W3：任务进行中时撤销按钮也禁用', async () => {
    vi.spyOn(api, 'getTimeline').mockResolvedValue(造())
    const w = mount(TimelinePanel, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="看全部"]').trigger('click')
    useJobStore().current = { ...job, status: 'running' }
    await flushPromises()
    expect(w.find('[data-test="撤销-T-002"]').attributes('disabled')).toBeDefined()
  })

  it('W4：任务结束后自动重新加载，失败时报错', async () => {
    vi.useFakeTimers()
    const get = vi.spyOn(api, 'getTimeline').mockResolvedValue({ conflicts: [], never_run: true, stale: false })
    vi.spyOn(api, 'currentJob')
      .mockResolvedValueOnce({ ...job, status: 'running' })
      .mockResolvedValueOnce({ ...job, status: 'failed', error: '模型欠费' })
    const w = mount(TimelinePanel, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    expect(get).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    expect(get).toHaveBeenCalledTimes(2)  // onFinish 触发了一次重新加载
    expect(w.text()).toContain('时间线检查失败：模型欠费')
    vi.useRealTimers()
  })

  it('W5：C 类卡片显示回指原话，不是 who', async () => {
    vi.spyOn(api, 'getTimeline').mockResolvedValue(造())
    const w = mount(TimelinePanel, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="看全部"]').trigger('click')
    const card = w.find('[data-test="冲突-T-002"]')
    expect(card.find('b').text()).toBe('「那日比箭之事」')
  })

  it('S8：统计行显示 a_capped 和 refs_no_candidate，0 不显示', async () => {
    vi.spyOn(api, 'getTimeline').mockResolvedValue(造())  // a_capped: 0, refs_no_candidate: 2
    const w = mount(TimelinePanel, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    const t = w.find('[data-test="时间线统计"]').text()
    expect(t).not.toContain('因每人只查死后')
    expect(t).toContain('2 条回指找不到候选')
  })

  it('S8：a_capped 非0时显示', async () => {
    vi.spyOn(api, 'getTimeline').mockResolvedValue(造({
      stats: { placed: 100, unplaced: 0, a_suspects: 4, a_capped: 6, refs_asked: 9, refs_no_candidate: 0, refs_all_before: 5 },
    }))
    const w = mount(TimelinePanel, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    const t = w.find('[data-test="时间线统计"]').text()
    expect(t).toContain('6 条因每人只查死后 5 场被截掉')
    expect(t).not.toContain('条回指找不到候选')
  })
})
