import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ArchivePage from './ArchivePage.vue'
import * as api from '@/api/endpoints'
import type { ArchiveIndex } from '@/api/types'

const routerLinkStub = { template: '<a><slot /></a>', props: ['to'] }
const stubs = { RouterLink: routerLinkStub }

function 造index(overrides: Partial<ArchiveIndex> = {}): ArchiveIndex {
  return {
    threads: {}, worlds: {},
    map: { file: '全书地图.md', sig: 's', outdated: false, generated: '' },
    current_model: 'deepseek-flash',
    ...overrides,
  }
}

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.restoreAllMocks())

describe('ArchivePage', () => {
  it('档案的模型跟当前配置不一样时提示', async () => {
    vi.spyOn(api, 'getArchiveIndex').mockResolvedValue(造index({
      current_model: 'deepseek-v5',
      threads: { 'L-001': { file: 'x', sig: 's', outdated: false, generated: '', model: 'deepseek-flash' } },
    }))
    const w = mount(ArchivePage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.text()).toContain('deepseek-flash')
    expect(w.text()).toContain('deepseek-v5')
    expect(w.find('[data-test="换模型提示"]').exists()).toBe(true)
  })

  it('模型一样时不提示', async () => {
    vi.spyOn(api, 'getArchiveIndex').mockResolvedValue(造index({
      current_model: 'deepseek-flash',
      threads: { 'L-001': { file: 'x', sig: 's', outdated: false, generated: '', model: 'deepseek-flash' } },
    }))
    const w = mount(ArchivePage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="换模型提示"]').exists()).toBe(false)
  })

  it('outdated 的档案要标出来', async () => {
    vi.spyOn(api, 'getArchiveIndex').mockResolvedValue(造index({
      current_model: 'deepseek-flash',
      threads: { 'L-001': { file: 'x', sig: 's', outdated: true, generated: '', model: 'deepseek-flash' } },
    }))
    const w = mount(ArchivePage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.text()).toContain('过期')
  })

  it('没有 model 字段的老档案不能崩', async () => {
    vi.spyOn(api, 'getArchiveIndex').mockResolvedValue(造index({
      current_model: 'deepseek-flash',
      threads: { 'L-001': {} as never },
    }))
    const w = mount(ArchivePage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="换模型提示"]').exists()).toBe(false)
  })

  it('左边列出支线档案、世界设定集、全书地图三类', async () => {
    vi.spyOn(api, 'getArchiveIndex').mockResolvedValue(造index({
      threads: { 'L-001': { file: 'x', sig: 's', outdated: false, generated: '' } },
      worlds: { 'W-01': { file: 'y', sig: 's', outdated: false, generated: '' } },
    }))
    const w = mount(ArchivePage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="条目-L-001"]').exists()).toBe(true)
    expect(w.find('[data-test="条目-W-01"]').exists()).toBe(true)
    expect(w.find('[data-test="条目-map"]').exists()).toBe(true)
  })

  it('点支线档案条目拉正文（kind=thread）', async () => {
    vi.spyOn(api, 'getArchiveIndex').mockResolvedValue(造index({
      threads: { 'L-001': { file: 'x', sig: 's', outdated: false, generated: '' } },
    }))
    const getBody = vi.spyOn(api, 'getArchiveBody').mockResolvedValue({ id: 'L-001', body: '# L-001\n来龙去脉…' })
    const w = mount(ArchivePage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="条目-L-001"]').trigger('click')
    await flushPromises()
    expect(getBody).toHaveBeenCalledWith('guixu', 'thread', 'L-001')
    expect(w.text()).toContain('来龙去脉')
  })

  it('点全书地图条目走专门的 getArchiveMap 接口', async () => {
    vi.spyOn(api, 'getArchiveIndex').mockResolvedValue(造index())
    const getMap = vi.spyOn(api, 'getArchiveMap').mockResolvedValue({ id: 'map', body: '# 全书地图\n## 全书概况' })
    const w = mount(ArchivePage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="条目-map"]').trigger('click')
    await flushPromises()
    expect(getMap).toHaveBeenCalledWith('guixu')
    expect(w.text()).toContain('全书概况')
  })

  it('点「标记为需要重跑」按钮，带上正确的 threads/worlds/map 参数', async () => {
    vi.spyOn(api, 'getArchiveIndex').mockResolvedValue(造index({
      current_model: 'deepseek-v5',
      threads: { 'L-001': { file: 'x', sig: 's', outdated: false, generated: '', model: 'deepseek-flash' } },
    }))
    const rerun = vi.spyOn(api, 'rerunArchive').mockResolvedValue({})
    const w = mount(ArchivePage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="标过期-L-001"]').trigger('click')
    expect(rerun).toHaveBeenCalledWith('guixu', { threads: ['L-001'], worlds: [], map: false })
  })

  it('重跑按钮文案说清楚不是立刻跑', async () => {
    vi.spyOn(api, 'getArchiveIndex').mockResolvedValue(造index({
      current_model: 'deepseek-v5',
      threads: { 'L-001': { file: 'x', sig: 's', outdated: false, generated: '', model: 'deepseek-flash' } },
    }))
    const w = mount(ArchivePage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.text()).toContain('下次跑步骤 7 时才会真跑')
  })

  it('支线/世界显示名字，不只显示编号', async () => {
    vi.spyOn(api, 'getArchiveIndex').mockResolvedValue(造index({
      threads: { 'L-001': { file: 'x', sig: 's', outdated: false, generated: '' } },
      worlds: { 'W-01': { file: 'y', sig: 's', outdated: false, generated: '' } },
    }))
    vi.spyOn(api, 'getThreads').mockResolvedValue({
      next_world: 2, next_thread: 2, time_unit: '年', main_thread: 'L-001', main_by: 'auto',
      worlds: [{ id: 'W-01', name: '东土大唐', reason: '', status: 'draft', notes: [], outlines: [] }],
      threads: [{ id: 'L-001', world: 'W-01', name: '取经主线', about: '', status: 'draft', scenes: [],
        times: {}, outlines: [], offset: 0 }],
    } as never)
    const w = mount(ArchivePage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="条目-L-001"]').text()).toContain('L-001')
    expect(w.find('[data-test="条目-L-001"]').text()).toContain('取经主线')
    expect(w.find('[data-test="条目-W-01"]').text()).toContain('东土大唐')
  })

  it('读不到线名（没跑步骤 6）时退回只显示编号，不报错', async () => {
    vi.spyOn(api, 'getArchiveIndex').mockResolvedValue(造index({
      threads: { 'L-001': { file: 'x', sig: 's', outdated: false, generated: '' } },
    }))
    vi.spyOn(api, 'getThreads').mockRejectedValue(new Error('boom'))
    const w = mount(ArchivePage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="条目-L-001"]').text()).toContain('L-001')
    expect(w.text()).not.toContain('boom')
  })

  it('还没生成全书地图时（后端给空对象 {}）不列地图条目', async () => {
    vi.spyOn(api, 'getArchiveIndex').mockResolvedValue(造index({ map: {} as never }))
    const w = mount(ArchivePage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="条目-map"]').exists()).toBe(false)
  })
})
