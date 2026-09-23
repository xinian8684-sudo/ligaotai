import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ContradictionsPage from './ContradictionsPage.vue'
import * as api from '@/api/endpoints'
import type { ContradictionGroup, ContradictionsFile } from '@/api/types'
import { useJobStore } from '@/stores/job'

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
    expect(w.text()).toContain('值变了，请重看')
  })

  it('verdict_stale 为假时不显示', async () => {
    vi.spyOn(api, 'getContradictions').mockResolvedValue(造文件([造组({ verdict_stale: false })]))
    const w = mount(ContradictionsPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="verdict过期"]').exists()).toBe(false)
  })

  // 计划④（本 Task）起矛盾页有了真的裁决按钮，「一期不给裁决按钮」这条断言（零按钮）
  // 跟本 Task 的目标直接矛盾，已改成断言不出现设计草稿里设想过、但从没真正做成 UI 文案
  // 的那两个按钮名——这是本 Task 有意改的断言，原因见 Task 报告。
  it('不出现旧版本设想过的「确认矛盾」「不是矛盾」按钮', async () => {
    vi.spyOn(api, 'getContradictions').mockResolvedValue(造文件([
      造组({ id: 'C-001', level: '严重' }),
      造组({ id: 'C-002', status: '无法判断', level: '' }),
      造组({ id: 'C-003', status: '合理变化', level: '' }),
    ]))
    const w = mount(ContradictionsPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
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

  it('每个值一个「以此为准」按钮，点了写裁决并刷新', async () => {
    const get = vi.spyOn(api, 'getContradictions').mockResolvedValue(造文件([造组()]))
    const put = vi.spyOn(api, 'putVerdict').mockResolvedValue(造组({
      verdict: { kind: 'pick', value: '如意金箍棒', by: 'author', at: 'x' } }))
    const w = mount(ContradictionsPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    const btns = w.findAll('[data-test^="以此为准-"]')
    expect(btns.map((b) => b.text())).toEqual(['以「如意金箍棒」为准', '以「降妖宝杖」为准'])
    await btns[0].trigger('click')
    await flushPromises()
    expect(put).toHaveBeenCalledWith('guixu', 'C-001', { kind: 'pick', value: '如意金箍棒' })
    expect(get).toHaveBeenCalledTimes(2)
  })

  it('自己写：空的不许提交', async () => {
    vi.spyOn(api, 'getContradictions').mockResolvedValue(造文件([造组()]))
    const put = vi.spyOn(api, 'putVerdict').mockResolvedValue(造组())
    const w = mount(ContradictionsPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="自己写-C-001"]').trigger('click')
    expect(w.find('[data-test="自己写确定-C-001"]').attributes('disabled')).toBeDefined()
    await w.find('[data-test="自己写输入-C-001"]').setValue('金箍棒')
    await w.find('[data-test="自己写确定-C-001"]').trigger('click')
    await flushPromises()
    expect(put).toHaveBeenCalledWith('guixu', 'C-001', { kind: 'own', value: '金箍棒' })
  })

  it('已裁决的显示结论和撤销，要跟着改的场景点开才拉', async () => {
    vi.spyOn(api, 'getContradictions').mockResolvedValue(造文件([造组({
      verdict: { kind: 'pick', value: '如意金箍棒', by: 'author', at: 'x' } })]))
    const fu = vi.spyOn(api, 'getFollowups').mockResolvedValue({ id: 'C-001', verdict: null,
      scenes: [{ id: 'S-0207', quote: '行者举起降妖宝杖', value: '降妖宝杖' }] })
    const put = vi.spyOn(api, 'putVerdict').mockResolvedValue(造组())
    const w = mount(ContradictionsPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="结论-C-001"]').text()).toContain('定为：如意金箍棒')
    expect(fu).not.toHaveBeenCalled()
    await w.find('[data-test="跟着改-C-001"]').trigger('click')
    await flushPromises()
    expect(w.text()).toContain('S-0207')
    await w.find('[data-test="撤销-C-001"]').trigger('click')
    expect(put).toHaveBeenCalledWith('guixu', 'C-001', { kind: null })
  })

  it('筛选：未裁决 / 需重看', async () => {
    vi.spyOn(api, 'getContradictions').mockResolvedValue(造文件([
      造组({ id: 'C-001' }),
      造组({ id: 'C-002', verdict: { kind: 'later', by: 'author', at: 'x' } }),
      造组({ id: 'C-003', verdict: { kind: 'pick', value: '降妖宝杖', by: 'author', at: 'x' }, verdict_stale: true }),
    ]))
    const w = mount(ContradictionsPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="筛选-未裁决"]').trigger('click')
    expect(w.findAll('[data-test="矛盾组"]').length).toBe(1)
    await w.find('[data-test="筛选-需重看"]').trigger('click')
    const groups = w.findAll('[data-test="矛盾组"]')
    expect(groups.length).toBe(1)
    expect(groups[0].text()).toContain('值变了，请重看')
  })

  it('有任务在跑时裁决按钮禁用', async () => {
    vi.spyOn(api, 'getContradictions').mockResolvedValue(造文件([造组()]))
    const w = mount(ContradictionsPage, { props: { name: 'guixu' }, global: { stubs } })
    await flushPromises()
    useJobStore().current = { id: 'j', name: 'archive', book: 'guixu', status: 'running', done: 0, total: 1,
      message: '', error: '', result: null, started: '', finished: '', cancel_requested: false }
    await flushPromises()
    expect(w.find('[data-test="以此为准-C-001-0"]').attributes('disabled')).toBeDefined()
  })
})
