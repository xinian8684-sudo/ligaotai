import { describe, it, expect } from 'vitest'
import { buildAxis } from './axis'
import { buildSegments, threadPoints } from './segments'
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
