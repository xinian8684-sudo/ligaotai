import { describe, it, expect, vi, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import PanoramaPage from './PanoramaPage.vue'
import LaneChart from '@/components/LaneChart.vue'
import * as api from '@/api/endpoints'
import type { ThreadsFile } from '@/api/types'
import 雪 from '@/components/__fixtures__/xueyuemei-threads.json'

const routerLinkStub = { template: '<a><slot /></a>', props: ['to'] }
const stubs = { RouterLink: routerLinkStub }

afterEach(() => vi.restoreAllMocks())

describe('PanoramaPage', () => {
  it('拉归线和版本组两份数据', async () => {
    const t = vi.spyOn(api, 'getThreads').mockResolvedValue(雪 as never)
    const v = vi.spyOn(api, 'getVersions').mockResolvedValue({ params: {}, groups: [] })
    mount(PanoramaPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(t).toHaveBeenCalled()
    expect(v).toHaveBeenCalled()
  })

  it('顶部统计不含任何费用', async () => {
    vi.spyOn(api, 'getThreads').mockResolvedValue(雪 as never)
    vi.spyOn(api, 'getVersions').mockResolvedValue({ params: {}, groups: [] })
    const w = mount(PanoramaPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.text()).not.toContain('$')
    expect(w.text()).not.toContain('费用')
  })

  it('选中一条线时右侧出详情', async () => {
    vi.spyOn(api, 'getThreads').mockResolvedValue(雪 as never)
    vi.spyOn(api, 'getVersions').mockResolvedValue({ params: {}, groups: [] })
    const w = mount(PanoramaPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    await w.findComponent(LaneChart).vm.$emit('select-thread', 'L-001')
    await flushPromises()
    expect(w.find('[data-test="详情"]').text()).toContain('岑秀')
  })

  it('详情里显示 end.note（写到哪）', async () => {
    vi.spyOn(api, 'getThreads').mockResolvedValue(雪 as never)
    vi.spyOn(api, 'getVersions').mockResolvedValue({ params: {}, groups: [] })
    const w = mount(PanoramaPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    await w.findComponent(LaneChart).vm.$emit('select-thread', 'L-001')
    await flushPromises()
    expect(w.find('[data-test="详情"]').text()).toContain('大结局')
  })

  it('点缺口簇时右侧列出那几处缺口的原文', async () => {
    vi.spyOn(api, 'getThreads').mockResolvedValue(雪 as never)
    vi.spyOn(api, 'getVersions').mockResolvedValue({ params: {}, groups: [] })
    const w = mount(PanoramaPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    const gaps = (雪 as unknown as ThreadsFile).gaps.slice(0, 2)
    await w.findComponent(LaneChart).vm.$emit('select-cluster', { threadId: 'L-005', gaps })
    await flushPromises()
    expect(w.find('[data-test="详情"]').text()).toContain(gaps[0].event.slice(0, 8))
  })

  it('点 orphan 时也出同样的详情（不静默丢掉定不了位的缺口）', async () => {
    vi.spyOn(api, 'getThreads').mockResolvedValue(雪 as never)
    vi.spyOn(api, 'getVersions').mockResolvedValue({ params: {}, groups: [] })
    const w = mount(PanoramaPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    const gaps = (雪 as unknown as ThreadsFile).gaps.slice(0, 1)
    await w.findComponent(LaneChart).vm.$emit('select-orphans', { threadId: 'L-005', gaps })
    await flushPromises()
    expect(w.find('[data-test="详情"]').text()).toContain(gaps[0].event.slice(0, 8))
  })

  it('步骤 6 没跑时出空态而不是报错', async () => {
    vi.spyOn(api, 'getThreads').mockResolvedValue({
      next_world: 1, next_thread: 1, time_unit: '年', main_thread: '', main_by: 'auto',
      worlds: [], threads: [], intersections: [], gaps: [], unassigned: [], pending: [],
    })
    vi.spyOn(api, 'getVersions').mockResolvedValue({ params: {}, groups: [] })
    const w = mount(PanoramaPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.text()).toContain('还没有')
  })

  it('拉数据失败时显示后端的话', async () => {
    const { ApiError } = await import('@/api/client')
    vi.spyOn(api, 'getThreads').mockRejectedValue(new ApiError(409, '世界与支线.json 结构不对'))
    vi.spyOn(api, 'getVersions').mockResolvedValue({ params: {}, groups: [] })
    const w = mount(PanoramaPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.text()).toContain('世界与支线.json 结构不对')
  })
})
