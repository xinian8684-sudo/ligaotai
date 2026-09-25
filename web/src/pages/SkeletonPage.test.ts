import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import SkeletonPage from './SkeletonPage.vue'
import * as api from '@/api/endpoints'
import { ApiError } from '@/api/client'
import type { Skeleton, Job } from '@/api/types'

const stubs = { RouterLink: { template: '<a><slot /></a>', props: ['to'] } }

function 造骨架(over: Partial<Skeleton> = {}): Skeleton {
  return {
    generated: 'x', by: 'program',
    volumes: [{ title: '第一卷', chapters: [
      { title: '开篇', notes: [{ kind: 'undecided', thread: 'L-003' }], items: [
        { type: 'scene', id: 'S-0001', thread: 'L-001' },
        { type: 'hole', id: 'H-001', task: '在 S-0001 与 S-0003 之间补写：大闹天宫 [S-0001]' },
        { type: 'scene', id: 'S-0004', thread: 'L-002', flag: 'cut' }] },
      { title: '龙宫', notes: [{ kind: 'cut_crossing', thread: 'L-004', scene: 'S-0066' }], items: [
        { type: 'scene', id: 'S-0005', thread: 'L-002' }] }] }],
    unplaced: { scenes: [{ id: 'S-0084', thread: 'L-001', why: 'no_time' }], holes: [] },
    ...over,
  }
}

const job: Job = { id: 'j', name: 'skeleton', book: 'x', status: 'queued', done: 0, total: 1, message: '',
  error: '', result: null, started: '', finished: '', cancel_requested: false }

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.restoreAllMocks())

describe('SkeletonPage', () => {
  it('卷章树、条目、备注、未定位', async () => {
    vi.spyOn(api, 'getSkeleton').mockResolvedValue(造骨架())
    const w = mount(SkeletonPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="卷章树"]').text()).toContain('开篇')
    expect(w.find('[data-test="卷章树"]').text()).toContain('龙宫')
    const items = w.find('[data-test="条目"]')
    expect(items.text()).toContain('S-0001')
    expect(items.find('[data-test="空洞-H-001"]').text()).toContain('大闹天宫')
    expect(items.find('[data-test="场景-S-0004"]').classes()).toContain('flagged')
    expect(w.text()).toContain('去留未定：L-003')
    expect(w.find('[data-test="未定位"]').text()).toContain('S-0084')
    expect(w.find('[data-test="未定位"]').text()).toContain('没有时间')
  })

  it('还没有骨架：显示空态和生成按钮', async () => {
    vi.spyOn(api, 'getSkeleton').mockRejectedValue(new ApiError(404, '还没有骨架，先生成一次'))
    const gen = vi.spyOn(api, 'generateSkeleton').mockResolvedValue(job)
    const w = mount(SkeletonPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="空态"]').exists()).toBe(true)
    await w.find('[data-test="生成"]').trigger('click')
    expect(gen).toHaveBeenCalledWith('x')
  })

  it('作者改过时生成要先确认', async () => {
    vi.spyOn(api, 'getSkeleton').mockResolvedValue(造骨架({ by: 'author' }))
    const gen = vi.spyOn(api, 'generateSkeleton').mockResolvedValue(job)
    const w = mount(SkeletonPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="生成"]').trigger('click')
    expect(gen).not.toHaveBeenCalled()
    expect(w.text()).toContain('骨架.bak.json')
    await w.find('[data-test="确认覆盖"]').trigger('click')
    expect(gen).toHaveBeenCalled()
  })

  it('改章名：整份保存', async () => {
    vi.spyOn(api, 'getSkeleton').mockResolvedValue(造骨架())
    const put = vi.spyOn(api, 'putSkeleton').mockImplementation(async (_n, sk) => ({ ...sk, by: 'author' }))
    const w = mount(SkeletonPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="章名-0-0"]').trigger('dblclick')
    const input = w.find('[data-test="章名输入-0-0"]')
    await input.setValue('新章名')
    await input.trigger('keyup.enter')
    await flushPromises()
    expect(put).toHaveBeenCalled()
    expect(put.mock.calls[0][1].volumes[0].chapters[0].title).toBe('新章名')
  })

  it('场景移到下一章、删空洞', async () => {
    vi.spyOn(api, 'getSkeleton').mockResolvedValue(造骨架())
    const put = vi.spyOn(api, 'putSkeleton').mockImplementation(async (_n, sk) => sk)
    const w = mount(SkeletonPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="下移场景-S-0001"]').trigger('click')
    await flushPromises()
    const sk1 = put.mock.calls[0][1]
    expect(sk1.volumes[0].chapters[0].items.map((i) => i.id)).toEqual(['H-001', 'S-0004'])
    expect(sk1.volumes[0].chapters[1].items.map((i) => i.id)).toEqual(['S-0001', 'S-0005'])
    await w.find('[data-test="删空洞-H-001"]').trigger('click')
    await flushPromises()
    expect(put.mock.calls[1][1].volumes[0].chapters[0].items.map((i) => i.id)).toEqual(['S-0004'])
  })

  it('导出：显示结果和下载链接', async () => {
    vi.spyOn(api, 'getSkeleton').mockResolvedValue(造骨架())
    vi.spyOn(api, 'exportBook').mockResolvedValue({ md: '导出/x.md', txt: '导出/x.txt', scenes: 3, holes: 1, missing: 0, chars: 12000, cut: 0 })
    const w = mount(SkeletonPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="导出"]').trigger('click')
    await flushPromises()
    const r = w.find('[data-test="导出结果"]')
    expect(r.text()).toContain('导出/x.md')
    expect(r.find('a[href$="/export/md"]').exists()).toBe(true)
  })

  it('章下移：同卷交换；卷末章下移到下一卷开头', async () => {
    const sk = 造骨架()
    sk.volumes.push({ title: '第二卷', chapters: [{ title: '归来', notes: [], items: [] }] })
    vi.spyOn(api, 'getSkeleton').mockResolvedValue(sk)
    const put = vi.spyOn(api, 'putSkeleton').mockImplementation(async (_n, x) => x)
    const w = mount(SkeletonPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="章下移-0-0"]').trigger('click')
    await flushPromises()
    expect(put.mock.calls[0][1].volumes[0].chapters.map((c) => c.title)).toEqual(['龙宫', '开篇'])
    await w.find('[data-test="章下移-0-1"]').trigger('click')
    await flushPromises()
    const last = put.mock.calls[1][1]
    expect(last.volumes[0].chapters.map((c) => c.title)).toEqual(['龙宫'])
    expect(last.volumes[1].chapters.map((c) => c.title)).toEqual(['开篇', '归来'])
  })

  it('全书第一章不能上移、最后一章不能下移', async () => {
    vi.spyOn(api, 'getSkeleton').mockResolvedValue(造骨架())
    const w = mount(SkeletonPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="章上移-0-0"]').attributes('disabled')).toBeDefined()
    expect(w.find('[data-test="章下移-0-1"]').attributes('disabled')).toBeDefined()
  })
})
