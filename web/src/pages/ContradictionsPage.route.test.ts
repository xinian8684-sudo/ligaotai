import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { reactive } from 'vue'
import * as api from '@/api/endpoints'

// 从别的页面带 ?tab=timeline 跳过来：加载完直接是时间线分页，不用再点一下（W6）。
const route = reactive<{ query: Record<string, string | undefined> }>({ query: {} })
const replace = vi.fn()
vi.mock('vue-router', async (orig) => ({
  ...(await orig<typeof import('vue-router')>()),
  useRoute: () => route,
  useRouter: () => ({ replace }),
}))

const { default: ContradictionsPage } = await import('./ContradictionsPage.vue')

const stubs = { RouterLink: { template: '<a><slot /></a>', props: ['to'] } }

beforeEach(() => {
  setActivePinia(createPinia())
  route.query = {}
  replace.mockClear()
})
afterEach(() => vi.restoreAllMocks())

describe('ContradictionsPage 地址栏分页', () => {
  it('W6：带 ?tab=timeline 进页面直接是时间线分页', async () => {
    route.query = { tab: 'timeline' }
    vi.spyOn(api, 'getContradictions').mockResolvedValue({ groups: [], stats: {} } as never)
    vi.spyOn(api, 'getTimeline').mockResolvedValue({ conflicts: [], never_run: true, stale: false })
    const w = mount(ContradictionsPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="时间线空态"]').exists()).toBe(true)
    expect(w.find('[data-test="分页-时间线"]').classes()).toContain('on')
  })

  it('W7：时间线分页下原矛盾内容（空态）不显示', async () => {
    route.query = { tab: 'timeline' }
    vi.spyOn(api, 'getContradictions').mockResolvedValue({ groups: [], stats: {} } as never)
    vi.spyOn(api, 'getTimeline').mockResolvedValue({ conflicts: [], never_run: true, stale: false })
    const w = mount(ContradictionsPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="空态"]').exists()).toBe(false)
  })

  it('没有 ?tab 时默认矛盾分页', async () => {
    vi.spyOn(api, 'getContradictions').mockResolvedValue({ groups: [], stats: {} } as never)
    const w = mount(ContradictionsPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="空态"]').exists()).toBe(true)
    expect(w.find('[data-test="分页-矛盾"]').classes()).toContain('on')
  })
})
