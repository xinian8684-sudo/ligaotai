/** 骨架拖拽用的挪动。都返回新对象，不改传进来的骨架。
 * 目标位置一律按「拿走之前」的下标算：拖到第 i 项上就是放到它前面，i 等于项数就是放到末尾。 */
import type { Skeleton } from '@/api/types'

export interface ItemPos { v: number; c: number; i: number }
export interface ChapterPos { v: number; c: number }

function 副本(sk: Skeleton): Skeleton {
  return JSON.parse(JSON.stringify(sk)) as Skeleton
}

export function moveItem(sk: Skeleton, from: ItemPos, to: ItemPos): Skeleton {
  const next = 副本(sk)
  const src = next.volumes[from.v].chapters[from.c].items
  const dst = next.volumes[to.v].chapters[to.c].items
  const [moved] = src.splice(from.i, 1)
  let i = to.i
  if (src === dst && from.i < to.i) i -= 1 // 同一章往后拖：前面少了一项
  dst.splice(i, 0, moved)
  return next
}

/** 拖空的卷删掉（导出不该带一个没有章节的卷标题）。 */
export function moveChapter(sk: Skeleton, from: ChapterPos, to: ChapterPos): Skeleton {
  const next = 副本(sk)
  const vols = next.volumes
  const target = vols[to.v]
  const [ch] = vols[from.v].chapters.splice(from.c, 1)
  let c = to.c
  if (from.v === to.v && from.c < to.c) c -= 1
  target.chapters.splice(c, 0, ch)
  next.volumes = vols.filter((v) => v.chapters.length > 0)
  return next
}

export function placeUnplaced(sk: Skeleton, sid: string, to: ItemPos): Skeleton {
  const next = 副本(sk)
  const k = next.unplaced.scenes.findIndex((s) => s.id === sid)
  if (k < 0) return next
  const [s] = next.unplaced.scenes.splice(k, 1)
  next.volumes[to.v].chapters[to.c].items.splice(to.i, 0, { type: 'scene', id: s.id, thread: s.thread })
  return next
}
