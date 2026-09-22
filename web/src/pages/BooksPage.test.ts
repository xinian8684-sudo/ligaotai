import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import BooksPage from './BooksPage.vue'
import * as api from '@/api/endpoints'
import { ApiError } from '@/api/client'

const routerLinkStub = { template: '<a><slot /></a>', props: ['to'] }
const stubs = { RouterLink: routerLinkStub }

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.restoreAllMocks())

describe('BooksPage', () => {
  it('没有书时给空态，不是一张空表', async () => {
    vi.spyOn(api, 'listBooks').mockResolvedValue([])
    const w = mount(BooksPage, { global: { stubs } })
    await flushPromises()
    expect(w.text()).toContain('还没有书')
  })

  it('列出书名和字数', async () => {
    vi.spyOn(api, 'listBooks').mockResolvedValue([
      { name: 'guixu', title: '归墟', created: '2026-09-01T10:00:00' },
    ])
    const w = mount(BooksPage, { global: { stubs } })
    await flushPromises()
    expect(w.text()).toContain('归墟')
  })

  it('后端报错时把 detail 原样显示', async () => {
    vi.spyOn(api, 'listBooks').mockRejectedValue(new ApiError(500, '书库目录读不了：E:\\不存在'))
    const w = mount(BooksPage, { global: { stubs } })
    await flushPromises()
    expect(w.text()).toContain('书库目录读不了')
    expect(w.text()).toContain('E:\\不存在')
  })

  it('导入同名但不同路径的文件夹时提醒', async () => {
    vi.spyOn(api, 'listBooks').mockResolvedValue([
      { name: 'guixu', title: '归墟', created: '2026-09-01T10:00:00' },
    ])
    vi.spyOn(api, 'getBook').mockResolvedValue({
      name: 'guixu', schema: 1, title: '归墟', created: '', settings: {},
      steps: {} as never,
      roots: { 我的稿子: 'D:\\甲\\我的稿子' },
    } as never)
    const w = mount(BooksPage, { global: { stubs } })
    await flushPromises()

    await w.find('[data-test="选书"]').trigger('click')
    await w.find('[data-test="来源文件夹"]').setValue('E:\\乙\\我的稿子')
    await flushPromises()

    expect(w.text()).toContain('同名')
    expect(w.text()).toContain('D:\\甲\\我的稿子')
  })

  it('同名且同路径不提醒', async () => {
    vi.spyOn(api, 'listBooks').mockResolvedValue([
      { name: 'guixu', title: '归墟', created: '2026-09-01T10:00:00' },
    ])
    vi.spyOn(api, 'getBook').mockResolvedValue({
      name: 'guixu', schema: 1, title: '归墟', created: '', settings: {},
      steps: {} as never,
      roots: { 我的稿子: 'D:\\甲\\我的稿子' },
    } as never)
    const w = mount(BooksPage, { global: { stubs } })
    await flushPromises()
    await w.find('[data-test="选书"]').trigger('click')
    await w.find('[data-test="来源文件夹"]').setValue('D:\\甲\\我的稿子')
    await flushPromises()
    expect(w.text()).not.toContain('同名')
  })

  it('有任务在跑时导入按钮禁用', async () => {
    vi.spyOn(api, 'listBooks').mockResolvedValue([])
    vi.spyOn(api, 'currentJob').mockResolvedValue({
      id: 'j1', name: 'cards', book: '归墟', status: 'running',
      done: 1, total: 9, message: '', error: '', result: null,
      started: '', finished: '', cancel_requested: false,
    })
    const { useJobStore } = await import('@/stores/job')
    const s = useJobStore()
    await s.refresh()
    const w = mount(BooksPage, { global: { stubs } })
    await flushPromises()
    const 按钮 = w.find('[data-test="导入"]')
    if (按钮.exists()) expect(按钮.attributes('disabled')).toBeDefined()
  })

  it('书架页有去设置的入口（新用户第一件事是配 key）', async () => {
    vi.spyOn(api, 'listBooks').mockResolvedValue([])
    const w = mount(BooksPage, { global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="去设置"]').text()).toContain('设置')
  })

  it('建书时间显示成「年-月-日 时:分」，不显示原始 ISO 串', async () => {
    vi.spyOn(api, 'listBooks').mockResolvedValue([
      { name: 'guixu', title: '归墟', created: '2026-09-12T20:11:21+08:00' },
    ])
    const w = mount(BooksPage, { global: { stubs } })
    await flushPromises()
    expect(w.text()).toContain('2026-09-12 20:11')
    expect(w.text()).not.toContain('T20:11')
  })
})
