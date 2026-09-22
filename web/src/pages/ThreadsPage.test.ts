import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ThreadsPage from './ThreadsPage.vue'
import * as api from '@/api/endpoints'
import { ApiError } from '@/api/client'
import type { ThreadsFile } from '@/api/types'
import 雪月梅 from '@/components/__fixtures__/xueyuemei-threads.json'

const routerLinkStub = { template: '<a><slot /></a>', props: ['to'] }
const stubs = { RouterLink: routerLinkStub }

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.restoreAllMocks())

describe('ThreadsPage', () => {
  it('order_failed 的线要醒目提示', async () => {
    const d = structuredClone(雪月梅) as unknown as ThreadsFile
    d.threads[0].order_failed = true
    vi.spyOn(api, 'getThreads').mockResolvedValue(d)
    const w = mount(ThreadsPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="排序失败"]').exists()).toBe(true)
    expect(w.text()).toContain('顺序不可信')
  })

  it('pending 逐条给接受和拒绝', async () => {
    const d = structuredClone(雪月梅) as unknown as ThreadsFile
    d.pending = [{ scene: 'S-0099', thread: 'L-001', reason: '模型建议' }]
    vi.spyOn(api, 'getThreads').mockResolvedValue(d)
    const w = mount(ThreadsPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="接受-S-0099"]').exists()).toBe(true)
    expect(w.find('[data-test="拒绝-S-0099"]').exists()).toBe(true)
  })

  it('接受调用 moveScenes 把块挪进模型建议的那条线', async () => {
    const d = structuredClone(雪月梅) as unknown as ThreadsFile
    d.pending = [{ scene: 'S-0099', thread: 'L-002', reason: '模型建议' }]
    vi.spyOn(api, 'getThreads').mockResolvedValue(d)
    const move = vi.spyOn(api, 'moveScenes').mockResolvedValue({})
    const w = mount(ThreadsPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="接受-S-0099"]').trigger('click')
    await flushPromises()
    expect(move).toHaveBeenCalledWith('guixu', 'L-002', { ids: ['S-0099'] })
  })

  // F1 G1 改了这条：原先断言「拒绝不打后端、换成选线控件」——那是后端没有拒绝接口时的权宜做法，
  // 刷新后 pending 又回来，是假确认。现在拒绝调 POST /threads/reject 落盘（pending → unassigned），
  // 成功后重拉；被拒的块出现在「未分配的块」里，由那里的选线控件归入。
  it('拒绝调后端落盘（pending → unassigned），成功后重拉，块出现在未分配里', async () => {
    const d = structuredClone(雪月梅) as unknown as ThreadsFile
    d.pending = [{ scene: 'S-0099', thread: 'L-002', reason: '模型建议' }]
    d.unassigned = []
    const 拒后 = structuredClone(d)
    拒后.pending = []
    拒后.unassigned = [{ scene: 'S-0099', reason: '作者拒绝了模型的建议' }]
    const get = vi.spyOn(api, 'getThreads').mockResolvedValueOnce(d).mockResolvedValue(拒后)
    const reject = vi.spyOn(api, 'rejectPending').mockResolvedValue([])
    const move = vi.spyOn(api, 'moveScenes').mockResolvedValue({})
    const 刷新书 = vi.fn().mockResolvedValue(undefined)
    const w = mount(ThreadsPage, {
      props: { name: 'guixu' },
      global: { stubs, provide: { 刷新书 } },
    })
    await flushPromises()
    await w.find('[data-test="拒绝-S-0099"]').trigger('click')
    await flushPromises()
    expect(reject).toHaveBeenCalledWith('guixu', ['S-0099'])
    expect(move).not.toHaveBeenCalled()
    expect(get).toHaveBeenCalledTimes(2)
    expect(刷新书).toHaveBeenCalledTimes(1)
    expect(w.find('[data-test="拒绝-S-0099"]').exists()).toBe(false)
    expect(w.find('[data-test="归入-S-0099"]').exists()).toBe(true)
    expect(w.text()).toContain('作者拒绝了模型的建议')
  })

  it('拒绝失败时把后端的话显示出来，pending 那行还在', async () => {
    const d = structuredClone(雪月梅) as unknown as ThreadsFile
    d.pending = [{ scene: 'S-0099', thread: 'L-002', reason: '模型建议' }]
    vi.spyOn(api, 'getThreads').mockResolvedValue(d)
    vi.spyOn(api, 'rejectPending').mockRejectedValue(new ApiError(400, '这些块不在待确认的建议里：S-0099'))
    const w = mount(ThreadsPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="拒绝-S-0099"]').trigger('click')
    await flushPromises()
    expect(w.text()).toContain('这些块不在待确认的建议里')
    expect(w.find('[data-test="拒绝-S-0099"]').exists()).toBe(true)
  })

  it('unassigned 列出来并能选线归入', async () => {
    const d = structuredClone(雪月梅) as unknown as ThreadsFile
    d.unassigned = [{ scene: 'S-0123', reason: '没归上' }]
    vi.spyOn(api, 'getThreads').mockResolvedValue(d)
    const w = mount(ThreadsPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.text()).toContain('S-0123')
    expect(w.find('[data-test="归入-S-0123"]').exists()).toBe(true)
  })

  it('归入前没选线时按钮是禁用的，选了才能点', async () => {
    const d = structuredClone(雪月梅) as unknown as ThreadsFile
    d.unassigned = [{ scene: 'S-0123', reason: '没归上' }]
    vi.spyOn(api, 'getThreads').mockResolvedValue(d)
    const move = vi.spyOn(api, 'moveScenes').mockResolvedValue({})
    const w = mount(ThreadsPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    const 按钮 = w.find('[data-test="归入-S-0123"]')
    expect(按钮.attributes('disabled')).toBeDefined()
    await w.find('select').setValue('L-001')
    await w.find('[data-test="归入-S-0123"]').trigger('click')
    await flushPromises()
    expect(move).toHaveBeenCalledWith('guixu', 'L-001', { ids: ['S-0123'] })
  })

  it('线的完没完取 end.state，不取 status', async () => {
    // status 是「划分确认了没有」不是「故事完了没有」，拿它判完结会全错
    const d = structuredClone(雪月梅) as unknown as ThreadsFile
    vi.spyOn(api, 'getThreads').mockResolvedValue(d)
    const w = mount(ThreadsPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.text()).toContain('完结')   // L-001 的 end.state
    expect(w.text()).toContain('待定')   // 其余几条
  })

  it('归线文件坏了（409）时显示后端的话', async () => {
    vi.spyOn(api, 'getThreads').mockRejectedValue(new ApiError(409, '世界与支线.json 结构不对：threads 不是数组'))
    const w = mount(ThreadsPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.text()).toContain('threads 不是数组')
  })

  it('可以把某条线设为主线', async () => {
    const d = structuredClone(雪月梅) as unknown as ThreadsFile
    vi.spyOn(api, 'getThreads').mockResolvedValue(d)
    const setMain = vi.spyOn(api, 'setMainThread').mockResolvedValue({})
    const w = mount(ThreadsPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="设为主线-L-002"]').trigger('click')
    await flushPromises()
    expect(setMain).toHaveBeenCalledWith('guixu', { thread: 'L-002' })
  })

  it('有任务在跑时接受/拒绝/归入/设为主线按钮都禁用', async () => {
    const d = structuredClone(雪月梅) as unknown as ThreadsFile
    d.pending = [{ scene: 'S-0099', thread: 'L-001', reason: '模型建议' }]
    d.unassigned = [{ scene: 'S-0123', reason: '没归上' }]
    vi.spyOn(api, 'getThreads').mockResolvedValue(d)
    vi.spyOn(api, 'currentJob').mockResolvedValue({
      id: 'j1', name: 'threads', book: 'guixu', status: 'running',
      done: 1, total: 2, message: '', error: '', result: null,
      started: '', finished: '', cancel_requested: false,
    })
    const { useJobStore } = await import('@/stores/job')
    await useJobStore().refresh()
    const w = mount(ThreadsPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="接受-S-0099"]').attributes('disabled')).toBeDefined()
    expect(w.find('[data-test="拒绝-S-0099"]').attributes('disabled')).toBeDefined()
    expect(w.find('[data-test="设为主线-L-002"]').attributes('disabled')).toBeDefined()
  })
})
