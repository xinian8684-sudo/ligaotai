import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import BookLayout from './BookLayout.vue'
import * as api from '@/api/endpoints'
import type { BookMeta, Job, StepName, StepState } from '@/api/types'
import { useJobStore } from '@/stores/job'

const routerLinkStub = { template: '<a><slot /></a>', props: ['to'] }
const stubs = { RouterLink: routerLinkStub, RouterView: { template: '<div>子页面内容</div>' } }

function 造书(steps: Partial<Record<StepName, Partial<StepState>>> = {}): BookMeta {
  const 全部: StepName[] = ['import', 'split', 'dedup', 'cards', 'entities', 'threads', 'archive']
  const s = {} as Record<StepName, StepState>
  for (const k of 全部) s[k] = { status: 'todo', updated: null, summary: {}, ...steps[k] }
  return { name: 'guixu', schema: 1, title: '归墟', created: '', settings: {}, steps: s, roots: {} }
}

function 造任务(over: Partial<Job> = {}): Job {
  return {
    id: 'j1', name: 'cards', book: 'guixu', status: 'running',
    done: 3, total: 10, message: '', error: '', result: null,
    started: '', finished: '', cancel_requested: false, ...over,
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.spyOn(api, 'currentJob').mockResolvedValue(null)
})
afterEach(() => vi.restoreAllMocks())

describe('BookLayout', () => {
  it('导航栏和子页面都渲染出来，书名来自后端', async () => {
    vi.spyOn(api, 'getBook').mockResolvedValue(造书())
    const w = mount(BookLayout, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.text()).toContain('理稿台')
    expect(w.text()).toContain('《归墟》')
    expect(w.text()).toContain('子页面内容')
  })

  it('角标取自各步 summary：实体待确认、待归线、矛盾组总数', async () => {
    vi.spyOn(api, 'getBook').mockResolvedValue(造书({
      entities: { status: 'done', summary: { draft_groups: 4 } },
      threads: { status: 'done', summary: { pending: 2 } },
      archive: { status: 'done', summary: { contradictions: 58, 严重: 11 } },
    }))
    const w = mount(BookLayout, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="实体角标"]').text()).toBe('4')
    expect(w.find('[data-test="归线角标"]').text()).toBe('2')
    expect(w.find('[data-test="矛盾角标"]').text()).toBe('58')
  })

  it('没有待办时子路由收起、矛盾不挂角标', async () => {
    vi.spyOn(api, 'getBook').mockResolvedValue(造书())
    const w = mount(BookLayout, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="实体角标"]').exists()).toBe(false)
    expect(w.find('[data-test="归线角标"]').exists()).toBe(false)
    expect(w.find('[data-test="矛盾角标"]').exists()).toBe(false)
  })

  it('后台任务结束后重新拉书，角标跟着变', async () => {
    const getBook = vi.spyOn(api, 'getBook').mockResolvedValue(造书())
    const w = mount(BookLayout, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    const s = useJobStore()
    vi.mocked(api.currentJob).mockResolvedValue(造任务())
    await s.refresh()
    getBook.mockResolvedValue(造书({ entities: { status: 'done', summary: { draft_groups: 7 } } }))
    vi.mocked(api.currentJob).mockResolvedValue(造任务({ status: 'done' }))
    await s.refresh()
    await flushPromises()
    expect(w.find('[data-test="实体角标"]').text()).toBe('7')
  })

  it('书拉不下来时给出原因，而不是空白', async () => {
    vi.spyOn(api, 'getBook').mockRejectedValue(new Error('书不存在'))
    const w = mount(BookLayout, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.text()).toContain('书不存在')
  })
})
