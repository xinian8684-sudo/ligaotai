import { describe, it, expect } from 'vitest'
import { buildAxis } from './axis'
import 西游记 from '@/components/__fixtures__/xiyouji-threads.json'
import 雪月梅 from '@/components/__fixtures__/xueyuemei-threads.json'
import type { ThreadsFile } from '@/api/types'

/** 把一本书的全部场景摊成全局时间点（t 为 null 的排除）。 */
function 全局点(d: ThreadsFile): number[] {
  const out: number[] = []
  for (const t of d.threads) {
    if (t.offset === null) continue // 没对齐到主线的线不进全局轴（审查 M2）；两本 fixture 里没有
    const off = t.offset
    for (const v of Object.values(t.times ?? {})) {
      if (v?.t !== null && v?.t !== undefined) out.push(off + v.t)
    }
  }
  return out
}

describe('buildAxis 边界', () => {
  it('一个点都没有时返回 null（调用方出空态）', () => {
    expect(buildAxis([])).toBeNull()
  })

  it('全部点相同时给一个满宽的区块，点画在正中间', () => {
    const a = buildAxis([5, 5, 5])!
    expect(a.blocks).toHaveLength(1)
    expect(a.breaks).toHaveLength(0)
    // 计划原先钉的是 0；spec 4.2 写「全部时间点相同 → 单区块居中」，spec 与计划冲突、以 spec 为准
    // （审查 S7，fix_A1toC.md 点名可改的断言）。段画满 [0,100]，标记在 0 会全挤到最左边。
    expect(a.x(5)).toBeCloseTo(50, 5)
  })

  it('中间的单点区块，标记落在区块中点（不贴左沿）', () => {
    // 手算（默认 breakRatio 0.05）：跨度 100，阈值 5；间隙 1/49/49/1 → 区块 [0,1] [50,50] [99,100]、2 个断口。
    // 余 = 100 - 2×3 - 3×1 = 91，总跨度 2 → 宽度 1+45.5 / 1+0 / 1+45.5
    // → [0,46.5]、断口、[49.5,50.5]、断口、[53.5,100]。t=50 落在中间单点块，中点 50（原先给左沿 49.5）。
    const a = buildAxis([0, 1, 50, 99, 100])!
    expect(a.blocks).toHaveLength(3)
    expect(a.blocks[1].x0).toBeCloseTo(49.5, 6)
    expect(a.blocks[1].x1).toBeCloseTo(50.5, 6)
    expect(a.x(50)).toBeCloseTo(50, 6)
  })

  it('单个点', () => {
    const a = buildAxis([3])!
    expect(a.blocks).toHaveLength(1)
    expect(a.lo).toBe(3)
    expect(a.hi).toBe(3)
  })

  it('间隙没超阈值时不断轴', () => {
    // 跨度 100，阈值 5；间隙全是 4，不该断
    const a = buildAxis(Array.from({ length: 26 }, (_, i) => i * 4))!
    expect(a.breaks).toHaveLength(0)
  })

  it('间隙恰好等于阈值时不断轴（判据是严格大于）', () => {
    // 跨度 100，阈值 5，间隙正好 5
    const a = buildAxis([0, 5, 100])!
    const 大间隙 = a.breaks.filter((b) => b.years === 5)
    expect(大间隙).toHaveLength(0)
  })

  it('间隙刚超过阈值就断', () => {
    const a = buildAxis([0, 5.1, 100])!
    expect(a.breaks.length).toBeGreaterThanOrEqual(1)
  })

  it('x 单调不减', () => {
    const a = buildAxis(全局点(西游记 as unknown as ThreadsFile))!
    const 点 = [...new Set(全局点(西游记 as unknown as ThreadsFile))].sort((p, q) => p - q)
    for (let i = 1; i < 点.length; i++) {
      expect(a.x(点[i])).toBeGreaterThanOrEqual(a.x(点[i - 1]) - 1e-9)
    }
  })

  it('最左的点在 0%，最右的点在 100%', () => {
    const a = buildAxis(全局点(西游记 as unknown as ThreadsFile))!
    expect(a.x(a.lo)).toBeCloseTo(0, 4)
    expect(a.x(a.hi)).toBeCloseTo(100, 4)
  })
})

describe('buildAxis 在《西游记》真数据上', () => {
  const a = buildAxis(全局点(西游记 as unknown as ThreadsFile))!

  it('范围是 -871.8 ~ 14', () => {
    expect(a.lo).toBeCloseTo(-871.8, 4)
    expect(a.hi).toBeCloseTo(14, 4)
  })

  it('切出 3 个区块、2 个断口', () => {
    expect(a.blocks).toHaveLength(3)
    expect(a.breaks).toHaveLength(2)
  })

  it('两个断口分别跨掉 360 年和 480.7 年', () => {
    expect(a.breaks[0].years).toBeCloseTo(360, 1)
    expect(a.breaks[1].years).toBeCloseTo(480.7, 1)
  })

  it('主线从 1.6% 变成 28.7%（这是整个断轴的意义）', () => {
    // L-001 全局 0 ~ 14
    const 宽 = a.x(14) - a.x(0)
    expect(宽).toBeGreaterThan(25)
    expect(宽).toBeCloseTo(28.67, 1)
    // 对照：等比例轴下只有 14/885.8 = 1.58%
    expect((14 / 885.8) * 100).toBeCloseTo(1.58, 1)
  })

  it('单点区块拿到的是最小宽度 1%', () => {
    const 第一块 = a.blocks[0]
    expect(第一块.t0).toBeCloseTo(-871.8, 2)
    expect(第一块.t1).toBeCloseTo(-871.8, 2)
    expect(第一块.x1 - 第一块.x0).toBeCloseTo(1, 4)
  })

  it('没退化成等比例轴', () => {
    expect(a.degraded).toBe(false)
  })
})

describe('buildAxis 在《雪月梅》真数据上', () => {
  const a = buildAxis(全局点(雪月梅 as unknown as ThreadsFile))!

  it('范围 -10 ~ 6.6，2 个区块 1 个断口', () => {
    expect(a.lo).toBeCloseTo(-10, 4)
    expect(a.hi).toBeCloseTo(6.6, 4)
    expect(a.blocks).toHaveLength(2)
    expect(a.breaks).toHaveLength(1)
  })

  it('第二个区块占 96%', () => {
    const b = a.blocks[1]
    expect(b.x0).toBeCloseTo(4, 2)
    expect(b.x1).toBeCloseTo(100, 2)
  })
})

describe('buildAxis 参数', () => {
  it('breakRatio 调大后断口变少', () => {
    const 点 = 全局点(西游记 as unknown as ThreadsFile)
    const 松 = buildAxis(点, { breakRatio: 0.6 })!
    expect(松.breaks.length).toBeLessThan(2)
  })

  it('区块碎到放不下时把断口压窄，算出来的坐标仍在 [0,100]', () => {
    // 造 40 个彼此远离的点：40 个区块保底 40% + 39 个断口 117% > 100%
    // breakRatio 调到 0.01 才真的切成 40 块（默认 0.05 时阈值 1950 > 间距 1000，一块都不切）
    const 点 = Array.from({ length: 40 }, (_, i) => i * 1000)
    const a = buildAxis(点, { breakRatio: 0.01 })!
    expect(a.x(点[0])).toBeCloseTo(0, 4)
    expect(a.x(点[39])).toBeCloseTo(100, 4)
    // 要么把断口压窄放下了，要么退化；两种都可以，但不能算出超过 100% 的坐标
    for (const p of 点) {
      expect(a.x(p)).toBeGreaterThanOrEqual(-1e-6)
      expect(a.x(p)).toBeLessThanOrEqual(100 + 1e-6)
    }
  })
})
