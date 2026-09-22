/** 一条线的「段」。真数据只有每场景一个时间点，段由断轴区块推出来。spec 4.3。 */

import type { Axis, AxisBlock } from './axis'
import type { Thread } from '@/api/types'

export interface Segment {
  t0: number
  t1: number
  x0: number
  x1: number
}

/**
 * 单点段的最小宽度（百分比）。比 axis 的 minBlock（1）小一点是故意的——
 * 段画在区块里面，跟区块一样宽会顶满边界看不出这是个「点」。
 */
const 单点宽 = 0.6

/**
 * 这条线对齐到主线了没有。`offset` 为 null（对齐失败 / 超预算跳过 / 模型没给）时
 * 它的线内时间跟全局轴没有换算关系——**不能当成 0**，当成 0 会把它画进主线的时间里，
 * 还会把全局轴撑歪（审查 M2：西游记 L-002 置 null 后轴从 -871.8~14 变成 -19~372.1）。
 * 调用方据此在线尾标「这条线没对齐到主线，时间位置未知」。
 */
export function isAligned(thread: Thread): boolean {
  return typeof thread.offset === 'number' && Number.isFinite(thread.offset)
}

/**
 * 一条线里「没有时间」的场景编号：`times` 里 t 为 null 的，**加上 `times` 里干脆缺键的**
 * （`thread_from_dict` 对脏时间值直接丢键）。线尾标签「N 个场景没有时间」用它数（审查 S2）。
 */
export function scenesWithoutTime(thread: Thread): string[] {
  const times = thread.times ?? {}
  return (thread.scenes ?? []).filter((sid) => times[sid]?.t == null)
}

/**
 * 一条线的全局时间点，升序。
 * `t` 为 null 的场景直接排除——**不插值**，插值等于编造位置（spec 4.5）。
 * 没对齐到主线的线（`offset` 为 null）一个点都不给：不进全局点集、不画段。
 */
export function threadPoints(thread: Thread): number[] {
  if (!isAligned(thread)) return []
  const off = thread.offset as number
  const out: number[] = []
  for (const v of Object.values(thread.times ?? {})) {
    if (v && v.t !== null && v.t !== undefined) out.push(off + v.t)
  }
  return out.sort((a, b) => a - b)
}

/** 把一条线的时间点按断轴区块切成段。 */
export function buildSegments(points: number[], axis: Axis): Segment[] {
  if (points.length === 0) return []
  const pts = [...points].sort((a, b) => a - b)
  const segs: Segment[] = []

  for (const blk of axis.blocks) {
    const 块内 = pts.filter((p) => p >= blk.t0 && p <= blk.t1)
    if (块内.length === 0) continue
    const t0 = 块内[0]
    const t1 = 块内[块内.length - 1]
    segs.push({ t0, t1, ...段范围(t0, t1, blk, axis) })
  }
  return segs
}

/**
 * 段的百分比范围。
 *
 * 区块本身就是一个时刻（`t0 === t1`，全书只在这一年有过这条线的场景）时，
 * 整块就是为这个时刻留的，段直接占满它——**这里不能用 单点宽**：
 * 那样画出来的段只有区块的一大半，看着像「块里还有别的东西」。
 * 《雪月梅》L-002 在 -10 年的那一段走的就是这一支（x = [0, 1]）。
 */
function 段范围(t0: number, t1: number, blk: AxisBlock, axis: Axis): { x0: number; x1: number } {
  if (blk.t1 === blk.t0) return { x0: blk.x0, x1: blk.x1 }
  let x0 = axis.x(t0)
  let x1 = axis.x(t1)
  if (x1 - x0 < 单点宽) {
    // 单个点或几乎重合：给一点宽度，不然画出来什么都看不见
    // 先把 x0 夹进区块、给右边留出 单点宽，再推 x1——只夹 x1 的话贴在右沿的点只剩一半宽
    // （审查 S6：单块 [0..10] 里的 10 原先是 [99.7,100]）。区块宽 ≥ minBlock(1) > 单点宽，放得下。
    const 中 = (x0 + x1) / 2
    x0 = Math.min(Math.max(blk.x0, 中 - 单点宽 / 2), blk.x1 - 单点宽)
    x1 = x0 + 单点宽
  }
  return { x0, x1 }
}
