import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import LaneChart from './LaneChart.vue'
import 西游记 from './__fixtures__/xiyouji-threads.json'
import 雪月梅 from './__fixtures__/xueyuemei-threads.json'
import type { ThreadsFile } from '@/api/types'

const 西 = 西游记 as unknown as ThreadsFile
const 雪 = 雪月梅 as unknown as ThreadsFile

describe('LaneChart 结构', () => {
  it('每条线一条泳道', () => {
    const w = mount(LaneChart, { props: { data: 西 } })
    expect(w.findAll('[data-test="泳道"]')).toHaveLength(3)
  })

  it('按世界分组', () => {
    const w = mount(LaneChart, { props: { data: 西 } })
    expect(w.findAll('[data-test="世界"]')).toHaveLength(1)
  })

  it('断口画出来并标明跨掉多少年', () => {
    const w = mount(LaneChart, { props: { data: 西 } })
    const 断口 = w.findAll('[data-test="断口"]')
    expect(断口).toHaveLength(2)
    expect(w.text()).toContain('360')
    expect(w.text()).toContain('480')
  })

  it('一个时间点都没有时出空态，不画空图', () => {
    const 空: ThreadsFile = { ...雪, threads: [] }
    const w = mount(LaneChart, { props: { data: 空 } })
    expect(w.findAll('[data-test="泳道"]')).toHaveLength(0)
    expect(w.text()).toContain('还没有')
  })
})

describe('LaneChart 段', () => {
  it('《西游记》主线一段，占 28% 以上', () => {
    const w = mount(LaneChart, { props: { data: 西 } })
    const 道 = w.find('[data-test="泳道-L-001"]')
    const 段 = 道.findAll('[data-test="段"]')
    expect(段).toHaveLength(1)
    const style = 段[0].attributes('style') ?? ''
    const m = /width:\s*([\d.]+)%/.exec(style)
    expect(m).not.toBeNull()
    expect(Number(m![1])).toBeGreaterThan(25)
  })

  it('《雪月梅》L-002 横跨断口，画成两段', () => {
    const w = mount(LaneChart, { props: { data: 雪 } })
    expect(w.find('[data-test="泳道-L-002"]').findAll('[data-test="段"]')).toHaveLength(2)
  })

  it('不画「只有提纲碎片」那种条带（outlines 在真数据里全是空的）', () => {
    const w = mount(LaneChart, { props: { data: 西 } })
    expect(w.find('[data-test="提纲段"]').exists()).toBe(false)
    expect(w.text()).not.toContain('提纲')
  })
})

describe('LaneChart 标记', () => {
  it('完没完取 end.state 不取 status', () => {
    const w = mount(LaneChart, { props: { data: 西 } })
    // L-001、L-002 是「完结」，L-003 是「待定」
    expect(w.findAll('[data-test="标记-完"]')).toHaveLength(2)
    expect(w.findAll('[data-test="标记-待定"]')).toHaveLength(1)
  })

  it('交汇点按 intersections 画', () => {
    const w = mount(LaneChart, { props: { data: 西 } })
    expect(w.findAll('[data-test="交汇"]')).toHaveLength(西.intersections.length)
  })

  it('order_failed 的线整条标出来', () => {
    const d = structuredClone(雪) as ThreadsFile
    d.threads[0].order_failed = true
    const w = mount(LaneChart, { props: { data: d } })
    expect(w.find('[data-test="泳道-L-001"]').classes()).toContain('排序失败')
  })
})

describe('LaneChart 缺口', () => {
  it('L-005 的 36 个缺口一个不丢：簇里的 + orphan = 36', () => {
    const w = mount(LaneChart, { props: { data: 雪, width: 1200 } })
    const 道 = w.find('[data-test="泳道-L-005"]')
    const 簇 = 道.findAll('[data-test="缺口簇"]')
    const 总数 = 簇.reduce((s, e) => s + Number(e.attributes('data-count') ?? 0), 0)
    const orphan元素 = 道.find('[data-test="缺口orphan"]')
    // find() 找不到时返回的是空 wrapper，直接调 attributes() 会抛，所以先判 exists
    const orphan = orphan元素.exists() ? Number(orphan元素.attributes('data-count') ?? 0) : 0
    expect(总数 + orphan).toBe(36)
    expect(orphan).toBe(5)
  })

  it('定不了位的 5 个有可见的落脚处，不是悄悄没了', () => {
    const w = mount(LaneChart, { props: { data: 雪 } })
    const 标签 = w.find('[data-test="泳道-L-005"]').find('[data-test="缺口orphan"]')
    expect(标签.exists()).toBe(true)
    expect(标签.text()).toContain('5')
  })

  it('窄容器下落点变少（二次聚合按像素算）', () => {
    const 宽 = mount(LaneChart, { props: { data: 雪, width: 2000 } })
    const 窄 = mount(LaneChart, { props: { data: 雪, width: 400 } })
    const 数 = (w: typeof 宽) => w.find('[data-test="泳道-L-005"]').findAll('[data-test="缺口簇"]').length
    expect(数(窄)).toBeLessThan(数(宽))
  })

  it('t 为 null 的场景不参与画图，也不插值', () => {
    // 雪月梅 L-001 有一个场景 t 是 null
    const w = mount(LaneChart, { props: { data: 雪 } })
    const 道 = w.find('[data-test="泳道-L-001"]')
    const 标签 = 道.find('[data-test="无时间场景"]')
    expect(标签.exists()).toBe(true)
  })
})

describe('LaneChart 交互', () => {
  it('点泳道抛 select-thread', async () => {
    const w = mount(LaneChart, { props: { data: 西 } })
    await w.find('[data-test="泳道-L-001"]').trigger('click')
    expect(w.emitted('select-thread')?.[0]).toEqual(['L-001'])
  })

  it('点缺口簇抛 select-cluster，带上这一簇的全部缺口', async () => {
    const w = mount(LaneChart, { props: { data: 雪 } })
    const 簇 = w.find('[data-test="泳道-L-005"]').find('[data-test="缺口簇"]')
    await 簇.trigger('click')
    const e = w.emitted('select-cluster')?.[0]?.[0] as { threadId: string; gaps: unknown[] }
    expect(e.threadId).toBe('L-005')
    expect(e.gaps.length).toBeGreaterThan(0)
  })
})

describe('LaneChart offset 为 null 的线（F1 给 D3 的坑：不能当 0）', () => {
  it('没对齐的线不画段，线尾标「没对齐」，不进全局轴', () => {
    const d = structuredClone(西) as ThreadsFile
    d.threads.find((t) => t.id === 'L-002')!.offset = null
    const w = mount(LaneChart, { props: { data: d } })
    const 道 = w.find('[data-test="泳道-L-002"]')
    expect(道.findAll('[data-test="段"]')).toHaveLength(0)
    expect(道.find('[data-test="未对齐"]').exists()).toBe(true)
    expect(道.text()).toContain('没对齐到主线')
  })

  it('它的缺口进 orphan，不拿 0 当偏移去定位', () => {
    const d = structuredClone(西) as ThreadsFile
    d.threads.find((t) => t.id === 'L-002')!.offset = null
    const w = mount(LaneChart, { props: { data: d } })
    const 道 = w.find('[data-test="泳道-L-002"]')
    const orphan = 道.find('[data-test="缺口orphan"]')
    expect(orphan.exists()).toBe(true)
    expect(orphan.attributes('data-count')).toBe('2')
  })
})

describe('LaneChart 没归到线的缺口（F1 给 D3 的坑：gap.thread === null）', () => {
  it('挂到世界级「N 处没归到线」，不是哪条线都不挂就丢了', () => {
    const d = structuredClone(雪) as ThreadsFile
    d.gaps.push({ id: 'Q-null', world: 'W-01', event: 'e', mentioned_in: [], thread: null, after: null, before: null })
    const w = mount(LaneChart, { props: { data: d } })
    expect(w.text()).toContain('1 处没归到线')
  })
})
