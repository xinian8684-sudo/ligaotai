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

  it('拒绝不直接打后端，而是换成选线归入的控件', async () => {
    const d = structuredClone(雪月梅) as unknown as ThreadsFile
    d.pending = [{ scene: 'S-0099', thread: 'L-002', reason: '模型建议' }]
    vi.spyOn(api, 'getThreads').mockResolvedValue(d)
    const move = vi.spyOn(api, 'moveScenes').mockResolvedValue({})
    const w = mount(ThreadsPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="拒绝-S-0099"]').trigger('click')
    await flushPromises()
    expect(move).not.toHaveBeenCalled()
    expect(w.find('[data-test="归入-S-0099"]').exists()).toBe(true)
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
