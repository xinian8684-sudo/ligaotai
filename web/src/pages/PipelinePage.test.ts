import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import PipelinePage from './PipelinePage.vue'
import * as api from '@/api/endpoints'
import type { BookMeta, StepName, StepState } from '@/api/types'

const routerLinkStub = { template: '<a><slot /></a>', props: ['to'] }
const stubs = { RouterLink: routerLinkStub }

function 造书(steps: Partial<Record<StepName, Partial<StepState>>> = {}): BookMeta {
  const 全部: StepName[] = ['import', 'split', 'dedup', 'cards', 'entities', 'threads', 'archive']
  const s = {} as Record<StepName, StepState>
  for (const k of 全部) s[k] = { status: 'todo', updated: null, summary: {}, ...steps[k] }
  return { name: 'guixu', schema: 1, title: '归墟', created: '', settings: {}, steps: s, roots: {} }
}

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.restoreAllMocks())

describe('PipelinePage', () => {
  it('七步都列出来', async () => {
    vi.spyOn(api, 'getBook').mockResolvedValue(造书())
    const w = mount(PipelinePage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    for (const 名 of ['导入', '切场景', '查重', '场景卡', '实体合并', '归线排序', '档案+矛盾+地图']) {
      expect(w.text()).toContain(名)
    }
  })

  it('一个费用数字都不显示', async () => {
    vi.spyOn(api, 'getBook').mockResolvedValue(造书({
      cards: { status: 'done', summary: { cost_usd: 1.2345, calls: 468, written: 133 } },
    }))
    const w = mount(PipelinePage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    const t = w.text()
    expect(t).not.toContain('1.2345')
    expect(t).not.toContain('$')
    expect(t).not.toContain('费用')
    expect(t).not.toContain('cost')
  })

  it('调用次数也不显示', async () => {
    vi.spyOn(api, 'getBook').mockResolvedValue(造书({
      cards: { status: 'done', summary: { cost_usd: 1.2, calls: 468, written: 133 } },
    }))
    const w = mount(PipelinePage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.text()).not.toContain('468')
  })

  it('上游没做完时下游的「跑」按钮禁用', async () => {
    vi.spyOn(api, 'getBook').mockResolvedValue(造书({ import: { status: 'todo' } }))
    const w = mount(PipelinePage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    const 按钮 = w.find('[data-test="跑-cards"]')
    expect(按钮.attributes('disabled')).toBeDefined()
  })

  it('步骤失败时把 summary.error 显示出来', async () => {
    vi.spyOn(api, 'getBook').mockResolvedValue(造书({
      cards: { status: 'failed', summary: { error: '已暂停：做完 12 张，还剩 88 张' } },
    }))
    const w = mount(PipelinePage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.text()).toContain('已暂停：做完 12 张，还剩 88 张')
  })

  it('过期的步骤要标出来', async () => {
    vi.spyOn(api, 'getBook').mockResolvedValue(造书({ cards: { status: 'outdated', summary: {} } }))
    const w = mount(PipelinePage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.text()).toContain('过期')
  })

  it('有任务在跑时所有「跑」按钮都禁用', async () => {
    vi.spyOn(api, 'getBook').mockResolvedValue(造书({
      import: { status: 'done' }, split: { status: 'done' }, dedup: { status: 'done' },
    }))
    vi.spyOn(api, 'currentJob').mockResolvedValue({
      id: 'j1', name: 'cards', book: 'guixu', status: 'running',
      done: 3, total: 10, message: '', error: '', result: null,
      started: '', finished: '', cancel_requested: false,
    })
    const { useJobStore } = await import('@/stores/job')
    await useJobStore().refresh()
    const w = mount(PipelinePage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    for (const s of ['split', 'dedup', 'cards']) {
      const b = w.find(`[data-test="跑-${s}"]`)
      if (b.exists()) expect(b.attributes('disabled')).toBeDefined()
    }
  })

  it('任务跑完后自动重新拉书的状态', async () => {
    const spy = vi.spyOn(api, 'getBook').mockResolvedValue(造书())
    vi.spyOn(api, 'currentJob').mockResolvedValue({
      id: 'j1', name: 'cards', book: 'guixu', status: 'running',
      done: 3, total: 10, message: '', error: '', result: null,
      started: '', finished: '', cancel_requested: false,
    })
    const { useJobStore } = await import('@/stores/job')
    const s = useJobStore()
    mount(PipelinePage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    const 次数 = spy.mock.calls.length

    await s.refresh()
    vi.spyOn(api, 'currentJob').mockResolvedValue({
      id: 'j1', name: 'cards', book: 'guixu', status: 'done',
      done: 10, total: 10, message: '', error: '', result: null,
      started: '', finished: '', cancel_requested: false,
    })
    await s.refresh()
    await flushPromises()
    expect(spy.mock.calls.length).toBeGreaterThan(次数)
  })
})
