import { describe, it, expect } from 'vitest'
import { moveChapter, moveItem, placeUnplaced } from './skeletonMoves'
import type { Skeleton } from '@/api/types'

function 骨架(): Skeleton {
  const s = (id: string) => ({ type: 'scene' as const, id, thread: 'L-001' })
  return {
    generated: 'x', by: 'program',
    volumes: [
      { title: '卷一', chapters: [
        { title: '甲', items: [s('S-0001'), s('S-0002'), s('S-0003')], notes: [] },
        { title: '乙', items: [s('S-0004')], notes: [] },
      ] },
      { title: '卷二', chapters: [
        { title: '丙', items: [s('S-0005'), { type: 'hole', id: 'H-001', task: '补' }], notes: [] },
      ] },
    ],
    unplaced: { scenes: [{ id: 'S-0009', thread: 'L-002', why: 'no_time' }], holes: [] },
  }
}
const 章名 = (sk: Skeleton) => sk.volumes.map((v) => v.chapters.map((c) => c.title))
const 项 = (sk: Skeleton, v: number, c: number) => sk.volumes[v].chapters[c].items.map((x) => x.id)

describe('moveItem', () => {
  it('章内往前挪：放到目标项前面', () => {
    const sk = moveItem(骨架(), { v: 0, c: 0, i: 2 }, { v: 0, c: 0, i: 0 })
    expect(项(sk, 0, 0)).toEqual(['S-0003', 'S-0001', 'S-0002'])
  })

  it('章内往后挪：目标下标按「拿走之前」算，落在原来那一项的前面', () => {
    // 把 S-0001 拖到 S-0003 上 → 放在 S-0003 前面
    const sk = moveItem(骨架(), { v: 0, c: 0, i: 0 }, { v: 0, c: 0, i: 2 })
    expect(项(sk, 0, 0)).toEqual(['S-0002', 'S-0001', 'S-0003'])
  })

  it('拖到章末（i 等于项数）', () => {
    const sk = moveItem(骨架(), { v: 0, c: 0, i: 0 }, { v: 0, c: 0, i: 3 })
    expect(项(sk, 0, 0)).toEqual(['S-0002', 'S-0003', 'S-0001'])
  })

  it('跨卷跨章，空洞也能挪', () => {
    const sk = moveItem(骨架(), { v: 1, c: 0, i: 1 }, { v: 0, c: 1, i: 0 })
    expect(项(sk, 0, 1)).toEqual(['H-001', 'S-0004'])
    expect(项(sk, 1, 0)).toEqual(['S-0005'])
  })

  it('不改原对象', () => {
    const 原 = 骨架()
    moveItem(原, { v: 0, c: 0, i: 0 }, { v: 0, c: 1, i: 0 })
    expect(项(原, 0, 0)).toEqual(['S-0001', 'S-0002', 'S-0003'])
  })
})

describe('moveChapter', () => {
  it('卷内往前：放到目标章前面', () => {
    const sk = moveChapter(骨架(), { v: 0, c: 1 }, { v: 0, c: 0 })
    expect(章名(sk)).toEqual([['乙', '甲'], ['丙']])
  })

  it('跨卷往后：放到目标章前面', () => {
    const sk = moveChapter(骨架(), { v: 0, c: 0 }, { v: 1, c: 0 })
    expect(章名(sk)).toEqual([['乙'], ['甲', '丙']])
  })

  it('拖到卷末（c 等于章数）', () => {
    const sk = moveChapter(骨架(), { v: 0, c: 0 }, { v: 1, c: 1 })
    expect(章名(sk)).toEqual([['乙'], ['丙', '甲']])
  })

  it('卷被拖空就删掉这一卷（导出不留空卷标题）', () => {
    const sk = moveChapter(骨架(), { v: 1, c: 0 }, { v: 0, c: 0 })
    expect(章名(sk)).toEqual([['丙', '甲', '乙']])
    expect(sk.volumes.map((v) => v.title)).toEqual(['卷一'])
  })

  it('同卷往后拖：目标下标按「拿走之前」算', () => {
    const sk = moveChapter(骨架(), { v: 0, c: 0 }, { v: 0, c: 2 })
    expect(章名(sk)).toEqual([['乙', '甲'], ['丙']])
  })
})

describe('placeUnplaced', () => {
  it('未定位的场景放进指定位置，带上线编号，从未定位里拿掉', () => {
    const sk = placeUnplaced(骨架(), 'S-0009', { v: 0, c: 0, i: 1 })
    expect(项(sk, 0, 0)).toEqual(['S-0001', 'S-0009', 'S-0002', 'S-0003'])
    expect(sk.volumes[0].chapters[0].items[1]).toEqual({ type: 'scene', id: 'S-0009', thread: 'L-002' })
    expect(sk.unplaced.scenes).toEqual([])
  })

  it('找不到这个场景就原样返回', () => {
    const sk = placeUnplaced(骨架(), 'S-9999', { v: 0, c: 0, i: 0 })
    expect(项(sk, 0, 0)).toEqual(['S-0001', 'S-0002', 'S-0003'])
  })
})
