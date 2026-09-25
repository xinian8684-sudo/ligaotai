import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import BoardPage from './BoardPage.vue'
import * as api from '@/api/endpoints'
import type { BoardView, ImpactView, Job } from '@/api/types'

const stubs = { RouterLink: { template: '<a><slot /></a>', props: ['to'] } }

function 造看板(over: Partial<BoardView> = {}): BoardView {
  const stat = (name: string, is_main = false) => ({ name, world: 'W-01', words: 12000, scenes: 8, state: '待定',
    gaps: 2, is_main, order_failed: false })
  return {
    cards: {
      'L-001': { col: 'keep', merge_into: null, note: '', orphan: false, merge_invalid: false },
      'L-002': { col: 'undecided', merge_into: null, note: '', orphan: false, merge_invalid: false },
    },
    stats: { 'L-001': stat('岑秀入仕', true), 'L-002': stat('小梅身世') },
    advice: null,
    ...over,
  }
}

const 影响: ImpactView = {
  program: { thread: 'L-002', crossings: [{ other: 'L-001', scene: 'S-0087', main_scene: 'S-0001', reason: '同赴山东' }],
    only_characters: [{ name: '小梅', scenes: ['S-0086'] }], maybe_refs: [] },
  model: null,
}

const job: Job = { id: 'j', name: 'triage_impact', book: 'x', status: 'queued', done: 0, total: 1, message: '',
  error: '', result: null, started: '', finished: '', cancel_requested: false }

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.restoreAllMocks())

describe('BoardPage', () => {
  it('四列按看板分好，卡片显示统计，主线有星号，没有费用数字', async () => {
    vi.spyOn(api, 'getBoard').mockResolvedValue(造看板())
    const w = mount(BoardPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="列-keep"]').text()).toContain('岑秀入仕')
    expect(w.find('[data-test="列-undecided"]').text()).toContain('小梅身世')
    expect(w.find('[data-test="卡-L-001"]').text()).toContain('★')
    expect(w.find('[data-test="卡-L-001"]').text()).toContain('8 块')
    expect(w.text()).not.toContain('$')
  })

  it('「移到」砍掉：写看板，并拉影响检查', async () => {
    vi.spyOn(api, 'getBoard').mockResolvedValue(造看板())
    const put = vi.spyOn(api, 'putCard').mockResolvedValue({ cards: 造看板().cards })
    const imp = vi.spyOn(api, 'getImpact').mockResolvedValue(影响)
    const w = mount(BoardPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="移到-L-002"]').setValue('cut')
    await flushPromises()
    expect(put).toHaveBeenCalledWith('x', 'L-002', { col: 'cut' })
    expect(imp).toHaveBeenCalledWith('x', 'L-002')
  })

  it('移到合并：先选并入哪条线才提交', async () => {
    vi.spyOn(api, 'getBoard').mockResolvedValue(造看板())
    const put = vi.spyOn(api, 'putCard').mockResolvedValue({ cards: 造看板().cards })
    vi.spyOn(api, 'getImpact').mockResolvedValue(影响)
    const w = mount(BoardPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="移到-L-002"]').setValue('merge')
    expect(put).not.toHaveBeenCalled()
    await w.find('[data-test="并入-L-002"]').setValue('L-001')
    await flushPromises()
    expect(put).toHaveBeenCalledWith('x', 'L-002', { col: 'merge', merge_into: 'L-001' })
  })

  it('砍掉列的卡显示程序化影响，模型部分没有时给按钮', async () => {
    const view = 造看板()
    view.cards['L-002'].col = 'cut'
    vi.spyOn(api, 'getBoard').mockResolvedValue(view)
    vi.spyOn(api, 'getImpact').mockResolvedValue(影响)
    const run = vi.spyOn(api, 'runImpact').mockResolvedValue(job)
    const w = mount(BoardPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    const box = w.find('[data-test="影响-L-002"]')
    expect(box.text()).toContain('S-0087')
    expect(box.text()).toContain('小梅')
    await w.find('[data-test="检查伏笔-L-002"]').trigger('click')
    expect(run).toHaveBeenCalledWith('x', 'L-002')
  })

  it('AI 建议显示在卡上，过期要提示', async () => {
    vi.spyOn(api, 'getBoard').mockResolvedValue(造看板({ advice: { generated: 'x', sig: 's', stale: true,
      items: [{ thread: 'L-002', advice: 'cut', merge_into: null, reason: '篇幅短 [S-0086]' }] } }))
    const w = mount(BoardPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="卡-L-002"]').text()).toContain('建议砍掉')
    expect(w.find('[data-test="卡-L-002"]').text()).toContain('篇幅短 [S-0086]')
    expect(w.text()).toContain('建议可能过时')
  })

  it('让 AI 给建议：触发任务并交给 job store', async () => {
    vi.spyOn(api, 'getBoard').mockResolvedValue(造看板())
    const run = vi.spyOn(api, 'runAdvice').mockResolvedValue({ ...job, name: 'triage_advice' })
    const w = mount(BoardPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="AI建议"]').trigger('click')
    expect(run).toHaveBeenCalledWith('x')
  })

  it('孤儿卡可以删，合并目标失效要提示', async () => {
    const view = 造看板()
    view.cards['L-009'] = { col: 'cut', merge_into: null, note: '', orphan: true, merge_invalid: false }
    view.cards['L-002'] = { col: 'merge', merge_into: 'L-001', note: '', orphan: false, merge_invalid: true }
    vi.spyOn(api, 'getBoard').mockResolvedValue(view)
    vi.spyOn(api, 'getImpact').mockResolvedValue(影响)
    const del = vi.spyOn(api, 'deleteCard').mockResolvedValue({ cards: {} })
    const w = mount(BoardPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="卡-L-002"]').text()).toContain('合并目标失效')
    await w.find('[data-test="删卡-L-009"]').trigger('click')
    expect(del).toHaveBeenCalledWith('x', 'L-009')
  })

  it('拖放：dragstart 后 drop 到某列会走 putCard', async () => {
    vi.spyOn(api, 'getBoard').mockResolvedValue(造看板())
    const put = vi.spyOn(api, 'putCard').mockResolvedValue({ cards: 造看板().cards })
    const w = mount(BoardPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="卡-L-001"]').trigger('dragstart')
    await w.find('[data-test="列-cut"]').trigger('drop')
    await flushPromises()
    expect(put).toHaveBeenCalledWith('x', 'L-001', { col: 'cut' })
  })

  it('建议1：dragend 清空拖着状态，之后 drop 不再动作', async () => {
    vi.spyOn(api, 'getBoard').mockResolvedValue(造看板())
    const put = vi.spyOn(api, 'putCard').mockResolvedValue({ cards: 造看板().cards })
    const w = mount(BoardPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    const card = w.find('[data-test="卡-L-001"]')
    await card.trigger('dragstart')
    await card.trigger('dragend')
    await w.find('[data-test="列-cut"]').trigger('drop')
    await flushPromises()
    expect(put).not.toHaveBeenCalled()
  })

  it('拖放绕过「移到」直接调 putCard 会被拦：拖到合并列要先选目标，不直接调 putCard', async () => {
    vi.spyOn(api, 'getBoard').mockResolvedValue(造看板())
    const put = vi.spyOn(api, 'putCard').mockResolvedValue({ cards: 造看板().cards })
    const w = mount(BoardPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="卡-L-002"]').trigger('dragstart')
    await w.find('[data-test="列-merge"]').trigger('drop')
    await flushPromises()
    expect(put).not.toHaveBeenCalled()
    expect(w.find('[data-test="并入-L-002"]').exists()).toBe(true)
  })

  it('建议2：并入候选排除已经砍掉的线和在合并列的线', async () => {
    const view = 造看板()
    view.cards['L-003'] = { col: 'cut', merge_into: null, note: '', orphan: false, merge_invalid: false }
    view.cards['L-004'] = { col: 'merge', merge_into: 'L-001', note: '', orphan: false, merge_invalid: false }
    view.stats['L-003'] = { name: '被砍的线', world: 'W-01', words: 100, scenes: 1, state: '待定', gaps: 0, is_main: false, order_failed: false }
    view.stats['L-004'] = { name: '已并入的线', world: 'W-01', words: 100, scenes: 1, state: '待定', gaps: 0, is_main: false, order_failed: false }
    vi.spyOn(api, 'getBoard').mockResolvedValue(view)
    const w = mount(BoardPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="移到-L-002"]').setValue('merge')
    const options = w.find('[data-test="并入-L-002"]').findAll('option').map((o) => o.text())
    expect(options.some((t) => t.includes('被砍的线'))).toBe(false)
    expect(options.some((t) => t.includes('已并入的线'))).toBe(false)
    expect(options.some((t) => t.includes('岑秀入仕'))).toBe(true)
  })

  it('建议3：col 已经是 merge 时并入下拉常驻显示，能直接改目标', async () => {
    const view = 造看板()
    view.cards['L-002'] = { col: 'merge', merge_into: 'L-001', note: '', orphan: false, merge_invalid: false }
    vi.spyOn(api, 'getBoard').mockResolvedValue(view)
    const put = vi.spyOn(api, 'putCard').mockResolvedValue({ cards: view.cards })
    const w = mount(BoardPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    // 不用先从主下拉重新选一次「合并」，下拉本来就在
    const select = w.find('[data-test="并入-L-002"]')
    expect(select.exists()).toBe(true)
    await select.setValue('L-001')
    await flushPromises()
    expect(put).toHaveBeenCalledWith('x', 'L-002', { col: 'merge', merge_into: 'L-001' })
  })

  it('建议4：模型影响过期时伏笔配对标已过期，按钮文案改成中性表述，旧建议不显示', async () => {
    const view = 造看板()
    view.cards['L-002'].col = 'cut'
    vi.spyOn(api, 'getBoard').mockResolvedValue(view)
    vi.spyOn(api, 'getImpact').mockResolvedValue({
      program: 影响.program,
      model: { sig: 's', generated: 'x', stale: true, remedy: '旧建议',
        pairs: [{ planted: 'S-0001', resolved: 'S-0002', hook: '钩子' }] },
    })
    const w = mount(BoardPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    const box = w.find('[data-test="影响-L-002"]')
    expect(box.text()).toContain('已过期')
    expect(box.text()).toContain('输入变了，可能过时')
    expect(box.text()).not.toContain('看板变了')
    expect(box.text()).not.toContain('旧建议')
  })

  it('M4：AI 建议任务失败时提示，不再只是默默刷新', async () => {
    vi.useFakeTimers()
    vi.spyOn(api, 'getBoard').mockResolvedValue(造看板())
    vi.spyOn(api, 'currentJob')
      .mockResolvedValueOnce({ ...job, name: 'triage_advice', status: 'queued' })
      .mockResolvedValueOnce({ ...job, name: 'triage_advice', status: 'failed', error: '模型欠费' })
    const w = mount(BoardPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    expect(w.text()).toContain('模型欠费')
    vi.useRealTimers()
  })

  it('M4：影响检查任务 result.ok===false 时提示', async () => {
    vi.useFakeTimers()
    vi.spyOn(api, 'getBoard').mockResolvedValue(造看板())
    vi.spyOn(api, 'currentJob')
      .mockResolvedValueOnce({ ...job, status: 'queued' })
      .mockResolvedValueOnce({ ...job, status: 'done', result: { ok: false, failed: [] } })
    const w = mount(BoardPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    expect(w.text()).toContain('没有成功')
    vi.useRealTimers()
  })

  it('补测：任务进行中时「移到」下拉和 AI 建议按钮禁用', async () => {
    vi.spyOn(api, 'getBoard').mockResolvedValue(造看板())
    vi.spyOn(api, 'runAdvice').mockResolvedValue({ ...job, name: 'triage_advice' })
    const w = mount(BoardPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="AI建议"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-test="AI建议"]').attributes('disabled')).toBeDefined()
    expect(w.find('[data-test="移到-L-001"]').attributes('disabled')).toBeDefined()
  })
})
