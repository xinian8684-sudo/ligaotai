import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ContradictionsPage from './ContradictionsPage.vue'
import * as api from '@/api/endpoints'
import type { ContradictionGroup, ContradictionsFile } from '@/api/types'

const routerLinkStub = { template: '<a><slot /></a>', props: ['to'] }
const stubs = { RouterLink: routerLinkStub }

function 造组(overrides: Partial<ContradictionGroup> = {}): ContradictionGroup {
  return {
    id: 'C-001', subject: '孙悟空', attribute: '兵器', status: '真矛盾', level: '严重', category: '人物',
    reason: '两处都在取经途中，同一件兵器写成了两个名字 [S-0014][S-0207]',
    values: [
      { value: '如意金箍棒', scenes: [{ id: 'S-0014', quote: '悟空掣出如意金箍棒', thread: 'L-001', t: 3, conf: '高' }] },
      { value: '降妖宝杖', scenes: [{ id: 'S-0207', quote: '行者举起降妖宝杖', thread: 'L-001', t: 5, conf: '低' }] },
    ],
    values_sig: 'sig1', verdict: null, verdict_sig: null, verdict_stale: false,
    ...overrides,
  }
}

function 造文件(groups: ContradictionGroup[], extra: Partial<ContradictionsFile> = {}): ContradictionsFile {
  return { groups, stats: {}, ...extra }
}

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.restoreAllMocks())

describe('ContradictionsPage', () => {
  it('默认只展开「严重」，其它桶折叠', async () => {
    vi.spyOn(api, 'getContradictions').mockResolvedValue(造文件([
      造组({ id: 'C-001', level: '严重' }),
      造组({ id: 'C-002', status: '无法判断', level: '', reason: '证据不够' }),
      造组({ id: 'C-003', status: '合理变化', level: '', reason: '随时间推移的合理变化' }),
    ]))
    const w = mount(ContradictionsPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()

    const 严重桶 = w.find('[data-test="桶-严重"]')
    const 无法判断桶 = w.find('[data-test="桶-无法判断"]')
    const 合理变化桶 = w.find('[data-test="桶-合理变化"]')
    expect(严重桶.attributes('open')).toBeDefined()
    expect(无法判断桶.attributes('open')).toBeUndefined()
    expect(合理变化桶.attributes('open')).toBeUndefined()
  })

  it('真矛盾但非严重（中等/轻微）也默认折叠', async () => {
    vi.spyOn(api, 'getContradictions').mockResolvedValue(造文件([
      造组({ id: 'C-001', level: '中等' }),
      造组({ id: 'C-002', level: '轻微' }),
    ]))
    const w = mount(ContradictionsPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="桶-中等"]').attributes('open')).toBeUndefined()
    expect(w.find('[data-test="桶-轻微"]').attributes('open')).toBeUndefined()
  })

  it('每组显示主语、属性、值、场景引用、判断理由', async () => {
    vi.spyOn(api, 'getContradictions').mockResolvedValue(造文件([造组()]))
    const w = mount(ContradictionsPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    const t = w.text()
    expect(t).toContain('孙悟空')
    expect(t).toContain('兵器')
    expect(t).toContain('如意金箍棒')
    expect(t).toContain('降妖宝杖')
    expect(t).toContain('S-0014')
    expect(t).toContain('S-0207')
    expect(t).toContain('两处都在取经途中')
  })

  it('verdict_stale 的组要标出来', async () => {
    vi.spyOn(api, 'getContradictions').mockResolvedValue(造文件([造组({ verdict_stale: true })]))
    const w = mount(ContradictionsPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="verdict过期"]').exists()).toBe(true)
    expect(w.text()).toContain('旧数据上做的')
  })

  it('verdict_stale 为假时不显示', async () => {
    vi.spyOn(api, 'getContradictions').mockResolvedValue(造文件([造组({ verdict_stale: false })]))
    const w = mount(ContradictionsPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="verdict过期"]').exists()).toBe(false)
  })

  it('一期不给裁决按钮', async () => {
    vi.spyOn(api, 'getContradictions').mockResolvedValue(造文件([
      造组({ id: 'C-001', level: '严重' }),
      造组({ id: 'C-002', status: '无法判断', level: '' }),
      造组({ id: 'C-003', status: '合理变化', level: '' }),
    ]))
    const w = mount(ContradictionsPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.findAll('button').length).toBe(0)
    expect(w.text()).not.toContain('确认矛盾')
    expect(w.text()).not.toContain('不是矛盾')
  })

  it('矛盾.json 不存在（步骤 7 没跑过）时出空态', async () => {
    vi.spyOn(api, 'getContradictions').mockResolvedValue(造文件([]))
    const w = mount(ContradictionsPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="空态"]').exists()).toBe(true)
    expect(w.text()).toContain('还没有矛盾扫描结果')
  })

  it('一个费用数字都不显示', async () => {
    vi.spyOn(api, 'getContradictions').mockResolvedValue(造文件([造组()], {
      stats: { facts: 1538, candidates: 83, cost_usd: 2.77 } as never,
    }))
    const w = mount(ContradictionsPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    const t = w.text()
    expect(t).not.toContain('2.77')
    expect(t).not.toContain('$')
    expect(t).not.toContain('费用')
  })
})
