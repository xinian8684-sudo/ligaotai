import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { reactive } from 'vue'
import * as api from '@/api/endpoints'
import type { SceneMeta } from '@/api/types'

// 从别的页面点场景编号跳过来：地址带 ?s=S-0002，加载完要选中它；地址里的 s 变了要跟着换
const route = reactive<{ query: Record<string, string> }>({ query: { s: 'S-0002' } })
vi.mock('vue-router', async (orig) => ({ ...(await orig<typeof import('vue-router')>()), useRoute: () => route }))

const { default: ScenesPage } = await import('./ScenesPage.vue')

const stubs = { RouterLink: { template: '<a><slot /></a>', props: ['to'] } }

function 造场景(id: string): SceneMeta {
  return { id, source: 'a.txt', index: 1, start: 0, end: 10, chars: 10, hash: `h-${id}`,
    heading: '', part: 1, kind_hint: '', stale: false, removed: false }
}

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.restoreAllMocks())

describe('ScenesPage 从地址选中场景', () => {
  it('?s=S-0002 → 加载完选中 S-0002；地址换成 S-0001 → 跟着选中 S-0001', async () => {
    vi.spyOn(api, 'listScenes').mockResolvedValue([造场景('S-0001'), 造场景('S-0002')])
    vi.spyOn(api, 'listCards').mockResolvedValue([])
    vi.spyOn(api, 'getVersions').mockResolvedValue({ params: {}, groups: [] })
    const getScene = vi.spyOn(api, 'getScene').mockImplementation(async (_b, sid) => ({ ...造场景(sid), text: `${sid} 原文` }))
    vi.spyOn(api, 'getCard').mockRejectedValue(new (await import('@/api/client')).ApiError(404, '没有卡'))
    const w = mount(ScenesPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(getScene).toHaveBeenLastCalledWith('guixu', 'S-0002')
    expect(w.find('[data-test="场景-S-0002"]').classes()).toContain('active')
    expect(w.text()).toContain('S-0002 原文')

    route.query = { s: 'S-0001' }
    await flushPromises()
    expect(w.find('[data-test="场景-S-0001"]').classes()).toContain('active')
    expect(w.text()).toContain('S-0001 原文')
  })
})
