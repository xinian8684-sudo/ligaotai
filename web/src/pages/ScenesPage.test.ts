import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ScenesPage from './ScenesPage.vue'
import * as api from '@/api/endpoints'
import { ApiError } from '@/api/client'
import type { SceneMeta, SceneDetail, CardRow, CardRecord, VersionsFile, Job } from '@/api/types'

const routerLinkStub = { template: '<a><slot /></a>', props: ['to'] }
const stubs = { RouterLink: routerLinkStub }

function 造场景(id: string, extra: Partial<SceneMeta> = {}): SceneMeta {
  return {
    id, source: 'a.txt', index: 1, start: 0, end: 10, chars: 10, hash: `h-${id}`,
    heading: '', part: 1, kind_hint: '', stale: false, removed: false, ...extra,
  }
}

function 造详情(id: string, text: string): SceneDetail {
  return { ...造场景(id), text }
}

function 造卡列表行(id: string, summary = `${id} 摘要`): CardRow {
  return { id, fresh: true, kind: '正文', summary, problems: 0, dropped: 0 }
}

function 造卡片(id: string): CardRecord {
  return {
    id, scene_hash: `h-${id}`, model: 'deepseek-flash', created: '', problems: [], dropped: {},
    card: {
      summary: `${id} 摘要`, pov: '', characters: [{ name: '悟空', role: '主要' }], locations: [],
      organizations: [], world_hint: '', time_hints: [], events: [],
      facts: [{ subject: '悟空', attribute: '兵器', value: '如意金箍棒', quote: '悟空掣出如意金箍棒' }],
      hooks_planted: [], hooks_resolved: [], refs_elsewhere: [], incomplete: false, incomplete_note: '', kind: '正文',
    },
  }
}

const 空版本: VersionsFile = { params: {}, groups: [] }

function mockJob(status: Job['status'] | null): void {
  vi.spyOn(api, 'currentJob').mockResolvedValue(
    status === null ? null : { id: 'j1', name: 'dedup', book: 'guixu', status, done: 0, total: 0,
      message: '', error: '', result: null, started: '', finished: '', cancel_requested: false },
  )
}

beforeEach(() => {
  setActivePinia(createPinia())
  mockJob(null)
})
afterEach(() => vi.restoreAllMocks())

describe('ScenesPage', () => {
  it('1000 个场景不卡死，都能渲染出来', async () => {
    const many = Array.from({ length: 1000 }, (_, i) => 造场景(`S-${String(i + 1).padStart(4, '0')}`))
    vi.spyOn(api, 'listScenes').mockResolvedValue(many)
    vi.spyOn(api, 'listCards').mockResolvedValue([])
    vi.spyOn(api, 'getVersions').mockResolvedValue(空版本)
    const w = mount(ScenesPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.findAll('[data-test^="场景-"]').length).toBe(1000)
  })

  it('选中场景：左边原文，右边场景卡', async () => {
    vi.spyOn(api, 'listScenes').mockResolvedValue([造场景('S-0001')])
    vi.spyOn(api, 'listCards').mockResolvedValue([造卡列表行('S-0001')])
    vi.spyOn(api, 'getVersions').mockResolvedValue(空版本)
    vi.spyOn(api, 'getScene').mockResolvedValue(造详情('S-0001', '悟空掣出如意金箍棒。'))
    vi.spyOn(api, 'getCard').mockResolvedValue(造卡片('S-0001'))
    const w = mount(ScenesPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="场景-S-0001"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-test="原文栏"]').text()).toContain('悟空掣出如意金箍棒')
    expect(w.find('[data-test="卡片栏"]').text()).toContain('如意金箍棒')
    expect(w.find('[data-test="卡片栏"]').text()).toContain('悟空')
  })

  it('卡还没生成时提示「这个场景还没有场景卡」，不是红色报错', async () => {
    vi.spyOn(api, 'listScenes').mockResolvedValue([造场景('S-0001')])
    vi.spyOn(api, 'listCards').mockResolvedValue([])
    vi.spyOn(api, 'getVersions').mockResolvedValue(空版本)
    vi.spyOn(api, 'getScene').mockResolvedValue(造详情('S-0001', '正文'))
    vi.spyOn(api, 'getCard').mockRejectedValue(new ApiError(404, '这个场景还没有场景卡'))
    const w = mount(ScenesPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="场景-S-0001"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-test="卡片栏"]').text()).toContain('这个场景还没有场景卡')
    expect(w.find('.err').exists()).toBe(false)
  })

  it('版本组并排对比，能设为主版本', async () => {
    vi.spyOn(api, 'listScenes').mockResolvedValue([造场景('S-0001'), 造场景('S-0002')])
    vi.spyOn(api, 'listCards').mockResolvedValue([])
    vi.spyOn(api, 'getVersions').mockResolvedValue({
      params: {},
      groups: [{ id: 'G-001', members: ['S-0001', 'S-0002'], main: 'S-0001', main_by: 'auto', pairs: [] }],
    })
    const setMain = vi.spyOn(api, 'setMainVersion').mockResolvedValue({})
    const w = mount(ScenesPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="版本组-G-001"]').text()).toContain('S-0001')
    expect(w.find('[data-test="版本组-G-001"]').text()).toContain('S-0002')
    await w.find('[data-test="设为主版本-G-001-S-0002"]').trigger('click')
    expect(setMain).toHaveBeenCalledWith('guixu', 'G-001', 'S-0002')
  })

  it('查重在跑时设为主版本禁用', async () => {
    mockJob('running')
    vi.spyOn(api, 'listScenes').mockResolvedValue([造场景('S-0001'), 造场景('S-0002')])
    vi.spyOn(api, 'listCards').mockResolvedValue([])
    vi.spyOn(api, 'getVersions').mockResolvedValue({
      params: {},
      groups: [{ id: 'G-001', members: ['S-0001', 'S-0002'], main: 'S-0001', main_by: 'auto', pairs: [] }],
    })
    const { useJobStore } = await import('@/stores/job')
    await useJobStore().refresh()
    const w = mount(ScenesPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    const 按钮 = w.find('[data-test="设为主版本-G-001-S-0002"]')
    expect(按钮.attributes('disabled')).toBeDefined()
  })

  it('搜索：卡片摘要和标题都能搜到', async () => {
    vi.spyOn(api, 'listScenes').mockResolvedValue([
      造场景('S-0001', { heading: '雪夜出走' }),
      造场景('S-0002', { heading: '龙宫借宝' }),
    ])
    vi.spyOn(api, 'listCards').mockResolvedValue([
      造卡列表行('S-0001', '清儿离开青州城'),
      造卡列表行('S-0002', '悟空闹龙宫'),
    ])
    vi.spyOn(api, 'getVersions').mockResolvedValue(空版本)
    const w = mount(ScenesPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="搜索"]').setValue('龙宫')
    await flushPromises()
    const 列表 = w.find('[data-test="场景列表"]').text()
    expect(列表).toContain('S-0002')
    expect(列表).not.toContain('S-0001')
  })

  it('勾选「也搜原文」后能搜到原文里的词', async () => {
    vi.spyOn(api, 'listScenes').mockResolvedValue([造场景('S-0001'), 造场景('S-0002')])
    vi.spyOn(api, 'listCards').mockResolvedValue([造卡列表行('S-0001', '摘要一'), 造卡列表行('S-0002', '摘要二')])
    vi.spyOn(api, 'getVersions').mockResolvedValue(空版本)
    vi.spyOn(api, 'getScene').mockImplementation(async (_n, sid) => {
      const text = sid === 'S-0001' ? '悟空掣出如意金箍棒' : '八戒扛着九齿钉耙'
      return 造详情(sid, text)
    })
    const w = mount(ScenesPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="搜原文开关"]').setValue(true)
    await flushPromises()
    await w.find('[data-test="搜索"]').setValue('九齿钉耙')
    await flushPromises()
    const 列表 = w.find('[data-test="场景列表"]').text()
    expect(列表).toContain('S-0002')
    expect(列表).not.toContain('S-0001')
  })

  it('GET /scenes 报 500 时显示后端给的文件名', async () => {
    vi.spyOn(api, 'listScenes').mockRejectedValue(new ApiError(500, '场景文件读不了：S-0007.md（YAML 头解析失败）'))
    const w = mount(ScenesPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.text()).toContain('S-0007.md')
    expect(w.text()).toContain('YAML 头解析失败')
  })
})
