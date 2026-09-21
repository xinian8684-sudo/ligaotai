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
 * 一条线的全局时间点，升序。
 * `t` 为 null 的场景直接排除——**不插值**，插值等于编造位置（spec 4.5）。
 */
export function threadPoints(thread: Thread): number[] {
  const off = thread.offset ?? 0
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
    const 中 = (x0 + x1) / 2
    x0 = Math.max(blk.x0, 中 - 单点宽 / 2)
    x1 = Math.min(blk.x1, x0 + 单点宽)
  }
  return { x0, x1 }
}
