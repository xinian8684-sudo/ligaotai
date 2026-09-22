import { describe, it, expect } from 'vitest'
import { buildAxis } from './axis'
import { threadPoints } from './segments'
import { gapsWithoutThread, layoutGaps, sceneTimeLookup } from './gaps'
import 雪月梅 from '@/components/__fixtures__/xueyuemei-threads.json'
import 西游记 from '@/components/__fixtures__/xiyouji-threads.json'
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
    // 在 x 上等距 1% 排 5 个点（x = 0,1,2,3,4），clusterRatio=1.5。
    // 9-22 作者拍板改规则，见 review_A1toC.md M3：原先单链规则下这里断言「全部并成 1 个」，
    // 改成「比当前簇中心、不连锁」后按新规则手算：
    //   0 开簇（中心 0）；1-0=1 <1.5 并入，中心 (0+1)/2=0.5；2-0.5=1.5 不小于 1.5，新簇（中心 2）；
    //   3-2=1 并入，中心 2.5；4-2.5=1.5 不并，新簇 4。→ 3 个落点 0.5×2、2.5×2、4×1
    const 场景时间: Record<string, number> = { a: 0, b: 1, c: 2, d: 3, e: 4 }
    const 查: (sid: string) => number | null = (s) => 场景时间[s] ?? null
    const gs: Gap[] = Object.keys(场景时间).map((s) => ({
      id: `Q-${s}`, world: 'W', event: 'e', mentioned_in: [], thread: 'L-1', after: null, before: s,
    }))
    const r = layoutGaps(gs, 查, a, { clusterRatio: 1.5 })
    expect(r.clusters).toHaveLength(3)
    expect(r.clusters.map((c) => c.gaps.length)).toEqual([2, 2, 1])
    expect(r.clusters[0].x).toBeCloseTo(0.5, 6)
    expect(r.clusters[1].x).toBeCloseTo(2.5, 6)
    expect(r.clusters[2].x).toBeCloseTo(4, 6)
  })
})

/**
 * 以下期望值全部由 F1 的独立 Python（scratchpad/f1_indep.py：按 spec 4.2–4.4 重写断轴与定位，
 * 第二层用「当前簇中心 vs 下一个点」扫描；同时跑了审查者 indep.py 的 cluster_center 原函数对照，
 * 两者在所有线、所有 r 上逐簇一致）从 fixture 算出，**不是拿实现跑出来的数反填**。
 */
describe('第二层按簇中心合并（9-22 作者拍板，review_A1toC.md M3）', () => {
  const 西 = 西游记 as unknown as ThreadsFile
  const 西轴 = buildAxis(西.threads.flatMap((t) => threadPoints(t)))!
  const 西查 = sceneTimeLookup(西)
  const 西主线 = 西.gaps.filter((g) => g.thread === 'L-001')

  it('《西游记》主线 33 个缺口全定得了位，第一层 27 个落点', () => {
    const r = layoutGaps(西主线, 西查, 西轴, { clusterRatio: 0 })
    expect(西主线).toHaveLength(33)
    expect(r.orphans).toHaveLength(0)
    expect(r.clusters).toHaveLength(27)
  })

  it('《西游记》主线 @ 1200px（clusterRatio = 28/1200×100 = 2.33%）收成 7 簇，不再把 30 个压成一个', () => {
    // 独立算的 7 簇：72.45×7 76.35×4 79.72×7 83.00×4 87.51×4 92.01×4 96.83×3
    const r = layoutGaps(西主线, 西查, 西轴, { clusterRatio: (28 / 1200) * 100 })
    expect(r.clusters).toHaveLength(7)
    expect(r.clusters.map((c) => c.gaps.length)).toEqual([7, 4, 7, 4, 4, 4, 3])
    expect(r.clusters[0].x).toBeCloseTo(72.4538, 2)
    expect(r.clusters[6].x).toBeCloseTo(96.8255, 2)
  })

  it('《西游记》主线 @ 800px（clusterRatio = 3.5%）收成 4 簇', () => {
    // 独立算的 4 簇：73.07×8 80.34×14 88.33×6 94.78×5
    const r = layoutGaps(西主线, 西查, 西轴, { clusterRatio: (28 / 800) * 100 })
    expect(r.clusters).toHaveLength(4)
    expect(r.clusters.map((c) => c.gaps.length)).toEqual([8, 14, 6, 5])
    expect(r.clusters[1].x).toBeCloseTo(80.3388, 2)
  })

  it('《西游记》主线 @ 1440px（clusterRatio = 28/1440×100 = 1.94%）收成 9 簇', () => {
    const r = layoutGaps(西主线, 西查, 西轴, { clusterRatio: (28 / 1440) * 100 })
    expect(r.clusters).toHaveLength(9)
  })

  it('《雪月梅》L-001 默认 1.5% 收成 10 簇（跟 gaps_expected.md 手算的 10 一致）', () => {
    const gs = 某线缺口('L-001')
    const r = layoutGaps(gs, 查时间, axis)
    expect(r.clusters).toHaveLength(10)
    expect(r.clusters.map((c) => c.gaps.length)).toEqual([1, 2, 2, 2, 2, 1, 4, 4, 2, 1])
    expect(r.clusters[1].x).toBeCloseTo(48.3636, 2)
    expect(r.clusters[2].x).toBeCloseTo(50.5455, 2)
  })

  it('相邻落点至少隔开 clusterRatio（中心规则下对任意数据成立）', () => {
    for (const ratio of [1.5, (28 / 1200) * 100, (28 / 800) * 100]) {
      const r = layoutGaps(西主线, 西查, 西轴, { clusterRatio: ratio })
      for (let i = 1; i < r.clusters.length; i++) {
        expect(r.clusters[i].x - r.clusters[i - 1].x).toBeGreaterThanOrEqual(ratio)
      }
    }
  })
})

describe('offset 为 null 的线，缺口定不了位（审查 M2）', () => {
  it('《西游记》L-002 offset 置 null：它的 2 个缺口进 orphans，不拿 0 当偏移去定位', () => {
    const 脏 = JSON.parse(JSON.stringify(西游记)) as ThreadsFile
    脏.threads.find((t) => t.id === 'L-002')!.offset = null
    const 轴 = buildAxis(脏.threads.flatMap((t) => threadPoints(t)))!
    const 查 = sceneTimeLookup(脏)
    const l2 = 脏.threads.find((t) => t.id === 'L-002')!
    for (const sid of l2.scenes) expect(查(sid)).toBeNull()
    const gs = 脏.gaps.filter((g) => g.thread === 'L-002')
    expect(gs).toHaveLength(2)
    const r = layoutGaps(gs, 查, 轴)
    expect(r.clusters).toHaveLength(0)
    expect(r.orphans).toHaveLength(2)
  })
})

describe('gapsWithoutThread（审查 S2）', () => {
  it('两本验收书里一个都没有', () => {
    expect(gapsWithoutThread(雪)).toHaveLength(0)
    expect(gapsWithoutThread(西游记 as unknown as ThreadsFile)).toHaveLength(0)
  })

  it('thread 为 null 的挑出来，按线过滤时它们哪条线都不挂', () => {
    const 脏 = JSON.parse(JSON.stringify(雪)) as ThreadsFile
    脏.gaps.push({ id: 'Q-null', world: 'W-01', event: 'e', mentioned_in: [], thread: null, after: null, before: null })
    expect(gapsWithoutThread(脏).map((g) => g.id)).toEqual(['Q-null'])
    const 各线合计 = 脏.threads.reduce((s, t) => s + 脏.gaps.filter((g) => g.thread === t.id).length, 0)
    expect(各线合计 + gapsWithoutThread(脏).length).toBe(脏.gaps.length)
  })
})
