/** 缺口的落点与两层聚合。spec 4.4。 */

import type { Axis } from './axis'
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

/** 建一张「场景编号 → 全局时间」的表。t 为 null 的场景查出来是 null。 */
export function sceneTimeLookup(data: ThreadsFile): (sid: string) => number | null {
  const table = new Map<string, number>()
  for (const t of data.threads) {
    const off = t.offset ?? 0
    for (const [sid, v] of Object.entries(t.times ?? {})) {
      if (v && v.t !== null && v.t !== undefined) table.set(sid, off + v.t)
    }
  }
  return (sid: string) => (table.has(sid) ? table.get(sid)! : null)
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

  // 第二层：挨得太近的连成一串（单链）——跟「前一个成员」比，不是跟串首比，
  // 所以并完还挨着的会继续并下去，一遍就收敛，不用反复扫。
  // 落点取串首和串尾的中点（不是加权平均：位置要落在这串缺口的正中间）。
  const clusters: GapCluster[] = []
  let 串: GapCluster[] = []
  const 收串 = () => {
    if (串.length === 0) return
    const 首 = 串[0]
    const 尾 = 串[串.length - 1]
    clusters.push({
      x: (首.x + 尾.x) / 2,
      gaps: 串.flatMap((c) => c.gaps),
    })
    串 = []
  }
  for (const c of 第一层) {
    const 上一个 = 串[串.length - 1]
    if (上一个 && c.x - 上一个.x >= clusterRatio) 收串()
    串.push(c)
  }
  收串()

  return { clusters, orphans }
}
