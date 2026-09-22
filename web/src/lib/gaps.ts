/** 缺口的落点与两层聚合。spec 4.4。 */

import type { Axis } from './axis'
import { isAligned } from './segments'
import type { Gap, ThreadsFile } from '@/api/types'

export interface GapCluster {
  /** 百分比位置 */
  x: number
  gaps: Gap[]
}

export interface GapLayout {
  clusters: GapCluster[]
  /** 两端都定不了位的。挂到线尾标签里，**不能静默丢掉**。 */
  orphans: Gap[]
}

export interface GapOptions {
  /** 相邻簇的 x 距离小于它就合并。默认 1.5（百分比）。0 表示只做第一层。 */
  clusterRatio?: number
}

/**
 * 建一张「场景编号 → 全局时间」的表。t 为 null 的场景查出来是 null。
 * 没对齐到主线的线（`offset` 为 null）的场景也查不到——它们的全局位置未知，
 * 挂在这些场景上的缺口会进 orphans，**不能拿 0 当偏移去定位**（审查 M2）。
 */
export function sceneTimeLookup(data: ThreadsFile): (sid: string) => number | null {
  const table = new Map<string, number>()
  for (const t of data.threads) {
    if (!isAligned(t)) continue
    const off = t.offset as number
    for (const [sid, v] of Object.entries(t.times ?? {})) {
      if (v && v.t !== null && v.t !== undefined) table.set(sid, off + v.t)
    }
  }
  return (sid: string) => (table.has(sid) ? table.get(sid)! : null)
}

/**
 * `thread` 为 null 的缺口（`clean_gaps` 发现线号不合格时把 thread/after/before 全置 null）。
 * 按线过滤时它们哪条线都不挂，全景页要把它们挂到世界级的「N 处没归到线」，**不能静默丢掉**（审查 S2）。
 */
export function gapsWithoutThread(data: ThreadsFile): Gap[] {
  return data.gaps.filter((g) => g.thread === null || g.thread === undefined || g.thread === '')
}

export function layoutGaps(
  gaps: Gap[],
  sceneTime: (sid: string) => number | null,
  axis: Axis,
  opts: GapOptions = {},
): GapLayout {
  const clusterRatio = opts.clusterRatio ?? 1.5

  // 定位：有 before 用 before，否则退到 after，都取不到就是 orphan
  const anchored: Array<{ x: number; gap: Gap }> = []
  const orphans: Gap[] = []
  for (const g of gaps) {
    const t = (g.before ? sceneTime(g.before) : null) ?? (g.after ? sceneTime(g.after) : null)
    if (t === null || t === undefined) orphans.push(g)
    else anchored.push({ x: axis.x(t), gap: g })
  }
  anchored.sort((a, b) => a.x - b.x)

  // 第一层：x 完全相同的合并
  const 第一层: GapCluster[] = []
  for (const a of anchored) {
    const last = 第一层[第一层.length - 1]
    if (last && Math.abs(last.x - a.x) < 1e-9) last.gaps.push(a.gap)
    else 第一层.push({ x: a.x, gaps: [a.gap] })
  }
  if (clusterRatio <= 0) return { clusters: 第一层, orphans }

  // 第二层（9-22 作者拍板改规则，见 review_A1toC.md M3）：按 x 升序扫，
  // **当前簇的中心**跟下一个第一层落点的距离 < clusterRatio 才并进来，不连锁。
  // 原先的单链（跟「前一个成员」比）链长没上限，西游记主线 @1200px 会把散布在 71%–93% 的
  // 30 个缺口压成一个三角。
  // 簇中心 = 簇内首尾两个第一层落点的中点（不是加权平均：位置要落在这串缺口的正中间；
  // 跟审查者 indep.py 的 cluster_center 同一个定义）。
  // 一遍扫完就是稳定的：某个点没并进当前簇时，当前簇的中心从此不再变，而下一簇的中心 ≥ 它的首点，
  // 所以相邻落点的距离 ≥ clusterRatio，不会出现「并完又跟邻簇靠近」。
  const clusters: GapCluster[] = []
  let 首x = 0
  let 尾x = 0
  for (const c of 第一层) {
    const cur = clusters[clusters.length - 1]
    if (cur && c.x - cur.x < clusterRatio) {
      尾x = c.x
      cur.gaps.push(...c.gaps)
      cur.x = (首x + 尾x) / 2
    } else {
      首x = c.x
      尾x = c.x
      clusters.push({ x: c.x, gaps: [...c.gaps] })
    }
  }

  return { clusters, orphans }
}
