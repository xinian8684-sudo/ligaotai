import { describe, it, expect } from 'vitest'
import { buildAxis } from './axis'
import { buildSegments, isAligned, scenesWithoutTime, threadPoints } from './segments'
import 雪月梅 from '@/components/__fixtures__/xueyuemei-threads.json'
import 西游记 from '@/components/__fixtures__/xiyouji-threads.json'
import type { Thread, ThreadsFile } from '@/api/types'

const 雪 = 雪月梅 as unknown as ThreadsFile
const 西 = 西游记 as unknown as ThreadsFile

function 全局点(d: ThreadsFile): number[] {
  return d.threads.flatMap((t) => threadPoints(t))
}

/**
 * 小数据的轴：默认 breakRatio 是 0.05，[0,1,2,3] 的跨度只有 3，阈值 0.15，
 * 每个间隙 1 都超了会切成 4 块。这些用例要的是「一整块」，所以把阈值放宽。
 */
function 单块轴(点: number[]) {
  return buildAxis(点, { breakRatio: 0.5 })!
}

describe('threadPoints', () => {
  it('把 offset 加到线内时间上', () => {
    const t = {
      offset: 10,
      times: { 'S-1': { t: 1, conf: '中' }, 'S-2': { t: 2, conf: '中' } },
    } as unknown as Thread
    expect(threadPoints(t)).toEqual([11, 12])
  })

  it('排除 t 为 null 的场景，不插值', () => {
    const t = {
      offset: 0,
      times: { 'S-1': { t: 1, conf: '中' }, 'S-2': { t: null, conf: '低' }, 'S-3': { t: 3, conf: '中' } },
    } as unknown as Thread
    expect(threadPoints(t)).toEqual([1, 3])
  })

  it('offset 为 null 的线一个点都不给，不能当成 0（审查 M2）', () => {
    const t = {
      offset: null,
      times: { 'S-1': { t: 1, conf: '中' }, 'S-2': { t: 2, conf: '中' } },
    } as unknown as Thread
    expect(isAligned(t)).toBe(false)
    expect(threadPoints(t)).toEqual([])
  })

  it('真数据里确实有 t 为 null 的场景', () => {
    const 全部 = 雪.threads.flatMap((t) => Object.values(t.times ?? {}))
    expect(全部.some((v) => v.t === null)).toBe(true)
  })
})

describe('buildSegments', () => {
  it('同一区块内的点合成一段', () => {
    const axis = 单块轴([0, 1, 2, 3])
    expect(axis.blocks).toHaveLength(1)
    const segs = buildSegments([0, 1, 2, 3], axis)
    expect(segs).toHaveLength(1)
    expect(segs[0].t0).toBe(0)
    expect(segs[0].t1).toBe(3)
  })

  it('跨区块自然断成两段', () => {
    const axis = buildAxis([0, 1, 500, 501])!
    expect(axis.blocks).toHaveLength(2)
    const segs = buildSegments([0, 1, 500, 501], axis)
    expect(segs).toHaveLength(2)
  })

  it('一条线在某个区块里一个点都没有时，那个区块不产段', () => {
    const axis = buildAxis([0, 1, 500, 501])!
    const segs = buildSegments([0, 1], axis)
    expect(segs).toHaveLength(1)
    expect(segs[0].t1).toBe(1)
  })

  it('单点段给最小宽度，不是 0 宽', () => {
    const axis = 单块轴([0, 1, 2, 3])
    const segs = buildSegments([2], axis)
    expect(segs).toHaveLength(1)
    expect(segs[0].x1 - segs[0].x0).toBeGreaterThan(0)
  })

  it('单点贴在区块右沿时也拿满 0.6 的宽度，整段夹在区块里（审查 S6）', () => {
    // breakRatio 2 → 一整块 t[0,10] → x[0,100]。x(10)=100，中=100：
    // x0 = min(max(0, 100-0.3), 100-0.6) = 99.4，x1 = 99.4+0.6 = 100（原先只夹 x1，得 [99.7,100]）
    const axis = buildAxis([0, 10], { breakRatio: 2 })!
    expect(axis.blocks).toHaveLength(1)
    const segs = buildSegments([10], axis)
    expect(segs).toHaveLength(1)
    expect(segs[0].x0).toBeCloseTo(99.4, 6)
    expect(segs[0].x1).toBeCloseTo(100, 6)
    expect(segs[0].x1 - segs[0].x0).toBeCloseTo(0.6, 6)
    // 贴左沿：x0 = max(0, -0.3) = 0，x1 = 0.6
    const 左 = buildSegments([0], axis)
    expect(左[0].x0).toBeCloseTo(0, 6)
    expect(左[0].x1).toBeCloseTo(0.6, 6)
  })

  it('空输入给空数组', () => {
    const axis = 单块轴([0, 1, 2])
    expect(buildSegments([], axis)).toEqual([])
  })

  it('《雪月梅》L-002 横跨断口，要断成两段', () => {
    // 这条线有一个场景在 -10 年，其余在 0 年之后——断轴正好从中间切过
    const axis = buildAxis(全局点(雪))!
    const l2 = 雪.threads.find((t) => t.id === 'L-002')!
    const segs = buildSegments(threadPoints(l2), axis)
    expect(segs).toHaveLength(2)
    expect(segs[0].x0).toBeCloseTo(0, 1)
    expect(segs[0].x1).toBeCloseTo(1, 1)
    expect(segs[1].x0).toBeCloseTo(4, 1)
    expect(segs[1].x1).toBeCloseTo(68, 0)
  })

  it('《西游记》主线只在最后一个区块里，一段', () => {
    const axis = buildAxis(全局点(西))!
    const l1 = 西.threads.find((t) => t.id === 'L-001')!
    const segs = buildSegments(threadPoints(l1), axis)
    expect(segs).toHaveLength(1)
    expect(segs[0].x1 - segs[0].x0).toBeCloseTo(28.67, 1)
  })

  it('《西游记》L-002 也横跨断口', () => {
    const axis = buildAxis(全局点(西))!
    const l2 = 西.threads.find((t) => t.id === 'L-002')!
    const segs = buildSegments(threadPoints(l2), axis)
    expect(segs).toHaveLength(2)
  })
})

describe('offset 为 null 的线（审查 M2，《西游记》fixture 副本把 L-002 的 offset 置 null）', () => {
  // 期望值由 F1 的独立 Python（scratchpad/f1_indep.py，按 spec 4.2 重写、只读 fixture）算出，并手算核过：
  // 去掉 L-002 后全局点只剩 L-001（0~14）和 L-003（-19~0），lo=-19、hi=14、跨度 33、阈值 1.65。
  // L-003 的点 -19、-18.5、-1、…、0：-18.5→-1 间隙 17.5 > 1.65 断开，其余间隙都 ≤ 1.65。
  // → 区块 [-19,-18.5]、[-1,14]，1 个断口跨 17.5 年。
  // 余 = 100 - 3 - 2 = 95，总跨度 0.5+15 = 15.5：
  //   块一宽 1 + 0.5/15.5×95 = 4.0645 → [0, 4.0645]；断口 → 7.0645；块二 [7.0645, 100]
  //   x(0) = 7.0645 + 1/15 × 92.9355 = 13.2602 → 主线宽 100 - 13.2602 = 86.7398
  const 脏 = JSON.parse(JSON.stringify(西游记)) as ThreadsFile
  const l2 = 脏.threads.find((t) => t.id === 'L-002')!
  l2.offset = null
  const axis = buildAxis(全局点(脏))!

  it('轴不再被它撑开：范围 -19 ~ 14，2 个区块、1 个 17.5 年的断口', () => {
    expect(axis.lo).toBeCloseTo(-19, 6)
    expect(axis.hi).toBeCloseTo(14, 6)
    expect(axis.blocks).toHaveLength(2)
    expect(axis.breaks).toHaveLength(1)
    expect(axis.breaks[0].years).toBeCloseTo(17.5, 6)
    expect(axis.blocks[0].x1).toBeCloseTo(4.0645, 3)
    expect(axis.blocks[1].x0).toBeCloseTo(7.0645, 3)
  })

  it('主线宽 86.74%（不是审查探针里被 L-002 当 0 撑出来的 29.91%）', () => {
    const l1 = 脏.threads.find((t) => t.id === 'L-001')!
    const segs = buildSegments(threadPoints(l1), axis)
    expect(segs).toHaveLength(1)
    expect(segs[0].x0).toBeCloseTo(13.2602, 3)
    expect(segs[0].x1).toBeCloseTo(100, 6)
    expect(segs[0].x1 - segs[0].x0).toBeCloseTo(86.7398, 3)
  })

  it('这条线自己不画段', () => {
    expect(isAligned(l2)).toBe(false)
    expect(buildSegments(threadPoints(l2), axis)).toEqual([])
  })
})

describe('scenesWithoutTime（线尾「N 个场景没有时间」的口径，审查 S2）', () => {
  it('t 为 null 的和 times 里缺键的都算', () => {
    const t = {
      offset: 0,
      scenes: ['S-1', 'S-2', 'S-3', 'S-4'],
      times: { 'S-1': { t: 1, conf: '中' }, 'S-2': { t: null, conf: '低' }, 'S-4': { t: 0, conf: '高' } },
    } as unknown as Thread
    // S-2：t 为 null；S-3：times 里没有这个键。S-4 的 t=0 是有时间的，不能被 == null 误伤
    expect(scenesWithoutTime(t)).toEqual(['S-2', 'S-3'])
  })

  it('《雪月梅》L-001 43 个场景里有 1 个没有时间（fixture 里没有缺键的）', () => {
    // 数字来自 F1 独立脚本 f1_check3.py 直接数 fixture：scenes 43、times 43、缺键 0、t 为 null 1
    const l1 = 雪.threads.find((t) => t.id === 'L-001')!
    expect(scenesWithoutTime(l1)).toHaveLength(1)
  })
})
