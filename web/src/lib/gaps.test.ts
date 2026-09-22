import { describe, it, expect } from 'vitest'
import { buildAxis } from './axis'
import { threadPoints } from './segments'
import { layoutGaps, sceneTimeLookup } from './gaps'
import 雪月梅 from '@/components/__fixtures__/xueyuemei-threads.json'
import type { Gap, ThreadsFile } from '@/api/types'

const 雪 = 雪月梅 as unknown as ThreadsFile
const 全局点 = 雪.threads.flatMap((t) => threadPoints(t))
const axis = buildAxis(全局点)!
const 查时间 = sceneTimeLookup(雪)

function 某线缺口(tid: string): Gap[] {
  return 雪.gaps.filter((g) => g.thread === tid)
}

describe('sceneTimeLookup', () => {
  it('查得到场景的全局时间', () => {
    const l1 = 雪.threads.find((t) => t.id === 'L-001')!
    const sid = l1.scenes[0]
    expect(查时间(sid)).not.toBeNull()
  })

  it('查不到的场景返回 null', () => {
    expect(查时间('S-9999')).toBeNull()
  })

  it('t 为 null 的场景查出来是 null（真数据里 L-001 有一个）', () => {
    const l1 = 雪.threads.find((t) => t.id === 'L-001')!
    const 没时间的 = Object.entries(l1.times).find(([, v]) => v.t === null)!
    expect(没时间的).toBeDefined()
    expect(查时间(没时间的[0])).toBeNull()
  })
})

describe('layoutGaps 定位', () => {
  it('有 before 时用 before', () => {
    const l1 = 雪.threads.find((t) => t.id === 'L-001')!
    const sid = l1.scenes[3]
    const g: Gap = { id: 'Q-x', world: 'W-01', event: 'e', mentioned_in: [], thread: 'L-001', after: null, before: sid }
    const r = layoutGaps([g], 查时间, axis)
    expect(r.orphans).toHaveLength(0)
    expect(r.clusters[0].x).toBeCloseTo(axis.x(查时间(sid)!), 4)
  })

  it('没有 before 时退到 after', () => {
    const l1 = 雪.threads.find((t) => t.id === 'L-001')!
    const sid = l1.scenes[3]
    const g: Gap = { id: 'Q-x', world: 'W-01', event: 'e', mentioned_in: [], thread: 'L-001', after: sid, before: null }
    const r = layoutGaps([g], 查时间, axis)
    expect(r.orphans).toHaveLength(0)
    expect(r.clusters[0].x).toBeCloseTo(axis.x(查时间(sid)!), 4)
  })

  it('before 指向一个查不到时间的场景时退到 after', () => {
    // 造一个：before 查不到时间，after 查得到
    const l1 = 雪.threads.find((t) => t.id === 'L-001')!
    const 好 = l1.scenes[3]
    const g: Gap = { id: 'Q-x', world: 'W-01', event: 'e', mentioned_in: [], thread: 'L-001', after: 好, before: 'S-9999' }
    const r = layoutGaps([g], 查时间, axis)
    expect(r.orphans).toHaveLength(0)
    expect(r.clusters).toHaveLength(1)
  })

  it('两端都查不到时进 orphans，不丢掉', () => {
    const g: Gap = { id: 'Q-x', world: 'W-01', event: 'e', mentioned_in: [], thread: 'L-001', after: null, before: null }
    const r = layoutGaps([g], 查时间, axis)
    expect(r.clusters).toHaveLength(0)
    expect(r.orphans.map((x) => x.id)).toEqual(['Q-x'])
  })

  it('一个缺口都不丢：簇里的 + orphan = 输入总数', () => {
    for (const tid of ['L-001', 'L-002', 'L-003', 'L-004', 'L-005']) {
      const gs = 某线缺口(tid)
      const r = layoutGaps(gs, 查时间, axis)
      const 进簇 = r.clusters.reduce((s, c) => s + c.gaps.length, 0)
      expect(进簇 + r.orphans.length).toBe(gs.length)
    }
  })
})

describe('layoutGaps 两层聚合（《雪月梅》L-005 真数据）', () => {
  const gs = 某线缺口('L-005')
  const r = layoutGaps(gs, 查时间, axis)

  it('这条线有 36 个缺口，31 个定得了位、5 个 orphan', () => {
    expect(gs).toHaveLength(36)
    expect(r.clusters.reduce((s, c) => s + c.gaps.length, 0)).toBe(31)
    expect(r.orphans).toHaveLength(5)
  })

  it('两层聚合后收成 13 个落点', () => {
    expect(r.clusters).toHaveLength(13)
  })

  it('第二层确实起了作用：只做第一层是 14 个落点', () => {
    // x(0.7)=14.18% 和 x(0.8)=15.64% 相差 1.45% < 1.5%，会被第二层并掉
    const 只做第一层 = layoutGaps(gs, 查时间, axis, { clusterRatio: 0 })
    expect(只做第一层.clusters).toHaveLength(14)
  })

  it('合并簇的位置是成员 x 的中点', () => {
    const 合并的 = r.clusters.find((c) => c.gaps.length === 7)
    expect(合并的).toBeDefined()
    expect(合并的!.x).toBeCloseTo(14.91, 1)
  })

  it('落点按 x 升序', () => {
    for (let i = 1; i < r.clusters.length; i++) {
      expect(r.clusters[i].x).toBeGreaterThan(r.clusters[i - 1].x)
    }
  })

  it('相邻落点至少隔开 clusterRatio，不会叠在一起', () => {
    for (let i = 1; i < r.clusters.length; i++) {
      expect(r.clusters[i].x - r.clusters[i - 1].x).toBeGreaterThanOrEqual(1.5)
    }
  })

  it('clusterRatio 调大后落点变少（窄屏会走到这一支）', () => {
    const 窄 = layoutGaps(gs, 查时间, axis, { clusterRatio: 10 })
    expect(窄.clusters.length).toBeLessThan(r.clusters.length)
    const 进簇 = 窄.clusters.reduce((s, c) => s + c.gaps.length, 0)
    expect(进簇 + 窄.orphans.length).toBe(36)
  })
})

describe('layoutGaps 迭代收敛', () => {
  it('一串等距的点，合并后又靠近的要继续合，不能只合一轮', () => {
    // breakRatio 放宽才是一条等比例的直轴；默认 0.05 时 [0,100] 会被断成两块，
    // 1~4 全落在断口里、被吸到同一个边界上，这个用例就测不到聚合了。
    const a = buildAxis([0, 100], { breakRatio: 2 })!
    expect(a.blocks).toHaveLength(1)
    // 在 x 上等距 1% 排 5 个点，clusterRatio=1.5 时应该全部并成 1 个
    const 场景时间: Record<string, number> = { a: 0, b: 1, c: 2, d: 3, e: 4 }
    const 查: (sid: string) => number | null = (s) => 场景时间[s] ?? null
    const gs: Gap[] = Object.keys(场景时间).map((s) => ({
      id: `Q-${s}`, world: 'W', event: 'e', mentioned_in: [], thread: 'L-1', after: null, before: s,
    }))
    const r = layoutGaps(gs, 查, a, { clusterRatio: 1.5 })
    expect(r.clusters).toHaveLength(1)
    expect(r.clusters[0].gaps).toHaveLength(5)
  })
})
