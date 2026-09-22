import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import EntitiesPage from './EntitiesPage.vue'
import * as api from '@/api/endpoints'
import { ApiError } from '@/api/client'
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

describe('EntitiesPage', () => {
  it('conflicts 从 steps.entities.summary 里读，并单独列出来', async () => {
    vi.spyOn(api, 'getBook').mockResolvedValue(造书({
      entities: {
        status: 'done',
        summary: { conflicts: [{ type: 'person', chunk: 2, names: ['觀世音', '觀音菩薩'] }] },
      },
    }))
    vi.spyOn(api, 'getEntities').mockResolvedValue({ next_id: 5, entities: [] })
    const w = mount(EntitiesPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.text()).toContain('觀世音')
    expect(w.text()).toContain('觀音菩薩')
    expect(w.find('[data-test="冲突区"]').exists()).toBe(true)
  })

  it('没有 conflicts 时不显示那一区', async () => {
    vi.spyOn(api, 'getBook').mockResolvedValue(造书({ entities: { status: 'done', summary: {} } }))
    vi.spyOn(api, 'getEntities').mockResolvedValue({ next_id: 1, entities: [] })
    const w = mount(EntitiesPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="冲突区"]').exists()).toBe(false)
  })

  it('只把 draft 状态的组当待确认', async () => {
    vi.spyOn(api, 'getBook').mockResolvedValue(造书())
    vi.spyOn(api, 'getEntities').mockResolvedValue({
      next_id: 9,
      entities: [
        { id: 'E-0001', type: 'person', canonical: '林清', names: ['林清', '清儿'], status: 'draft', reason: '同一人', scenes: ['S-1'] },
        { id: 'E-0002', type: 'person', canonical: '张三', names: ['张三'], status: 'single', reason: '', scenes: ['S-2'] },
        { id: 'E-0003', type: 'person', canonical: '李四', names: ['李四', '四郎'], status: 'confirmed', reason: '', scenes: ['S-3'] },
      ],
    })
    const w = mount(EntitiesPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.findAll('[data-test="待确认组"]')).toHaveLength(1)
  })

  it('实体文件坏了时显示后端给的 detail', async () => {
    vi.spyOn(api, 'getBook').mockResolvedValue(造书())
    vi.spyOn(api, 'getEntities').mockRejectedValue(
      new ApiError(500, '实体.json读不了：不是合法 JSON，第 3 行。这个文件多半被手动改过或来自别处。'))
    const w = mount(EntitiesPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.text()).toContain('不是合法 JSON，第 3 行')
  })

  it('点接受调 confirmEntities 并带上这个实体的 id', async () => {
    vi.spyOn(api, 'getBook').mockResolvedValue(造书())
    vi.spyOn(api, 'getEntities').mockResolvedValue({
      next_id: 2,
      entities: [
        { id: 'E-0001', type: 'person', canonical: '林清', names: ['林清', '清儿'], status: 'draft', reason: '同一人', scenes: ['S-1'] },
      ],
    })
    const confirm = vi.spyOn(api, 'confirmEntities').mockResolvedValue([])
    const w = mount(EntitiesPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="接受-E-0001"]').trigger('click')
    await flushPromises()
    expect(confirm).toHaveBeenCalledWith('guixu', ['E-0001'])
  })

  it('全部接受把所有待确认组的 id 一起带上', async () => {
    vi.spyOn(api, 'getBook').mockResolvedValue(造书())
    vi.spyOn(api, 'getEntities').mockResolvedValue({
      next_id: 3,
      entities: [
        { id: 'E-0001', type: 'person', canonical: '林清', names: ['林清'], status: 'draft', reason: '', scenes: [] },
        { id: 'E-0002', type: 'person', canonical: '王五', names: ['王五'], status: 'draft', reason: '', scenes: [] },
      ],
    })
    const confirm = vi.spyOn(api, 'confirmEntities').mockResolvedValue([])
    const w = mount(EntitiesPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="全部接受"]').trigger('click')
    await flushPromises()
    expect(confirm.mock.calls[0][1].sort()).toEqual(['E-0001', 'E-0002'])
  })

  it('拆开会把勾中的叫法传给 splitEntity', async () => {
    vi.spyOn(api, 'getBook').mockResolvedValue(造书())
    vi.spyOn(api, 'getEntities').mockResolvedValue({
      next_id: 2,
      entities: [
        { id: 'E-0001', type: 'person', canonical: '林清', names: ['林清', '清儿'], status: 'draft', reason: '同一人', scenes: [] },
      ],
    })
    const split = vi.spyOn(api, 'splitEntity').mockResolvedValue({})
    const w = mount(EntitiesPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    const checkboxes = w.findAll('input[type="checkbox"]')
    await checkboxes[0].setValue(true)
    await w.find('[data-test="拆开-E-0001"]').trigger('click')
    await flushPromises()
    expect(split).toHaveBeenCalledWith('guixu', 'E-0001', { names: ['林清'] })
  })

  it('有任务在跑时接受/拆开按钮禁用', async () => {
    vi.spyOn(api, 'getBook').mockResolvedValue(造书())
    vi.spyOn(api, 'getEntities').mockResolvedValue({
      next_id: 2,
      entities: [
        { id: 'E-0001', type: 'person', canonical: '林清', names: ['林清'], status: 'draft', reason: '', scenes: [] },
      ],
    })
    vi.spyOn(api, 'currentJob').mockResolvedValue({
      id: 'j1', name: 'entities', book: 'guixu', status: 'running',
      done: 1, total: 2, message: '', error: '', result: null,
      started: '', finished: '', cancel_requested: false,
    })
    const { useJobStore } = await import('@/stores/job')
    await useJobStore().refresh()
    const w = mount(EntitiesPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="接受-E-0001"]').attributes('disabled')).toBeDefined()
    expect(w.find('[data-test="拆开-E-0001"]').attributes('disabled')).toBeDefined()
  })
})
