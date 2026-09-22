/** 断轴成轴：把「一个场景都没有的长空白」压成固定宽度的断口。spec 4.2。 */

export interface AxisBlock {
  /** 这一块覆盖的时间范围 */
  t0: number
  t1: number
  /** 对应的百分比范围 [0,100] */
  x0: number
  x1: number
}

export interface AxisBreak {
  /** 这个断口跨掉了多少年（要显示给作者，不然他以为两段是挨着的） */
  years: number
  x0: number
  x1: number
}

export interface Axis {
  lo: number
  hi: number
  blocks: AxisBlock[]
  breaks: AxisBreak[]
  /** 时间 → 百分比 */
  x: (t: number) => number
  /** 区块太碎放不下、退回了等比例轴 */
  degraded: boolean
}

export interface AxisOptions {
  /** 间隙超过「全局跨度 × 它」才算断口。默认 0.05 */
  breakRatio?: number
  /** 每个断口占的百分比。默认 3 */
  breakWidth?: number
  /** 每个区块的保底百分比。默认 1 */
  minBlock?: number
}

const 默认 = { breakRatio: 0.05, breakWidth: 3, minBlock: 1 }

/** 时间点为空时返回 null——调用方据此出空态，不要画一张空图。 */
export function buildAxis(points: number[], opts: AxisOptions = {}): Axis | null {
  const { breakRatio, breakWidth, minBlock } = { ...默认, ...opts }
  const pts = [...new Set(points)].sort((a, b) => a - b)
  if (pts.length === 0) return null

  const lo = pts[0]
  const hi = pts[pts.length - 1]
  const span = hi - lo

  // 全部点重合：一个区块占满，点画在正中间（spec 4.2「单区块居中」）。
  // 计划原先的测试钉的是 0——那样段画满 [0,100]、标记却全挤在最左边；spec 与计划冲突，以 spec 为准（审查 S7）。
  if (span === 0) {
    const blocks: AxisBlock[] = [{ t0: lo, t1: hi, x0: 0, x1: 100 }]
    return { lo, hi, blocks, breaks: [], x: () => 50, degraded: false }
  }

  // 切区块：间隙「严格大于」阈值才断
  const 阈值 = span * breakRatio
  const ranges: Array<[number, number]> = []
  const 间隙: number[] = []
  let start = pts[0]
  for (let i = 1; i < pts.length; i++) {
    const d = pts[i] - pts[i - 1]
    if (d > 阈值) {
      ranges.push([start, pts[i - 1]])
      间隙.push(d)
      start = pts[i]
    }
  }
  ranges.push([start, hi])

  // 宽度分配：先扣断口和保底，剩下的按各区块跨度比例分
  let bw = breakWidth
  const 固定 = () => 间隙.length * bw + ranges.length * minBlock
  if (固定() >= 100) {
    // 断口按比例压窄，最小不低于 1%
    const 可给断口 = Math.max(0, 100 - ranges.length * minBlock)
    bw = 间隙.length > 0 ? Math.max(1, (可给断口 * 0.4) / 间隙.length) : 0
  }
  if (固定() >= 100) {
    // 还是放不下：退回等比例轴
    const blocks: AxisBlock[] = [{ t0: lo, t1: hi, x0: 0, x1: 100 }]
    return {
      lo,
      hi,
      blocks,
      breaks: [],
      degraded: true,
      x: (t: number) => clamp(((t - lo) / span) * 100),
    }
  }

  const 余 = 100 - 固定()
  const 总跨度 = ranges.reduce((s, [a, b]) => s + (b - a), 0)
  const blocks: AxisBlock[] = []
  const breaks: AxisBreak[] = []
  let x = 0
  ranges.forEach(([a, b], i) => {
    const share = 总跨度 > 0 ? ((b - a) / 总跨度) * 余 : 余 / ranges.length
    const w = minBlock + share
    blocks.push({ t0: a, t1: b, x0: x, x1: x + w })
    x += w
    if (i < 间隙.length) {
      breaks.push({ years: 间隙[i], x0: x, x1: x + bw })
      x += bw
    }
  })
  // 浮点累计误差：把最后一块钉到 100
  if (blocks.length > 0) blocks[blocks.length - 1].x1 = 100

  function x映射(t: number): number {
    if (t <= lo) return 0
    if (t >= hi) return 100
    for (const blk of blocks) {
      if (t >= blk.t0 && t <= blk.t1) {
        // 单点区块：段画满整块，这个时刻的标记落在块的中点，不贴左沿（审查 S7）。
        // 两端的 lo/hi 在上面已经钉成 0/100，这一支只管中间的单点区块。
        if (blk.t1 === blk.t0) return (blk.x0 + blk.x1) / 2
        return clamp(blk.x0 + ((t - blk.t0) / (blk.t1 - blk.t0)) * (blk.x1 - blk.x0))
      }
    }
    // 落进断口——按定义不该发生（断口内部没有点）。防御：吸附到最近的区块边界。
    let best = blocks[0]
    let bestD = Infinity
    for (const blk of blocks) {
      const d = t < blk.t0 ? blk.t0 - t : t - blk.t1
      if (d < bestD) {
        bestD = d
        best = blk
      }
    }
    return clamp(t < best.t0 ? best.x0 : best.x1)
  }

  return { lo, hi, blocks, breaks, x: x映射, degraded: false }
}

function clamp(v: number): number {
  return Math.min(100, Math.max(0, v))
}
