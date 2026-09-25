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
    // M2：textarea 改成 :value 绑定（不再是子节点插值），要读 DOM 的 value 属性，
    // 不能再用 .text()（这是改「怎么读值」，不是改期望值——期望的文字内容没变）。
    expect((items.find('[data-test="空洞输入-H-001"]').element as HTMLTextAreaElement).value).toContain('大闹天宫')
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
    // M3：保存成功后会 await 加载()（重新 GET），不再直接拿 PUT 的回包当新状态——
    // getSkeleton 的 mock 要跟着 putSkeleton 存的东西走，不然第二次操作会读到没更新的旧数据。
    let 当前 = 造骨架()
    vi.spyOn(api, 'getSkeleton').mockImplementation(async () => 当前)
    const put = vi.spyOn(api, 'putSkeleton').mockImplementation(async (_n, sk) => {
      当前 = sk
      return sk
    })
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

  it('导出：cut 是「砍掉的线仍被导出」的块数，不能说成没收进书', async () => {
    vi.spyOn(api, 'getSkeleton').mockResolvedValue(造骨架())
    vi.spyOn(api, 'exportBook').mockResolvedValue({ md: '导出/x.md', txt: '导出/x.txt', scenes: 3, holes: 1, missing: 0, chars: 12000, cut: 2 })
    const w = mount(SkeletonPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="导出"]').trigger('click')
    await flushPromises()
    const t = w.find('[data-test="导出结果"]').text()
    expect(t).toContain('2 块所属的线已经在看板上砍掉了')
    expect(t).toContain('照样导出了')
    expect(t).not.toContain('没收进')
  })

  it('章下移：同卷交换；卷末章下移到下一卷开头', async () => {
    const sk = 造骨架()
    sk.volumes.push({ title: '第二卷', chapters: [{ title: '归来', notes: [], items: [] }] })
    let 当前 = sk
    vi.spyOn(api, 'getSkeleton').mockImplementation(async () => 当前)
    const put = vi.spyOn(api, 'putSkeleton').mockImplementation(async (_n, x) => {
      当前 = x
      return x
    })
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

  it('M1/补测：保存失败时错误提示不会被吞，且会重新拉一次最新状态', async () => {
    const get = vi.spyOn(api, 'getSkeleton').mockResolvedValue(造骨架())
    vi.spyOn(api, 'putSkeleton').mockRejectedValue(new ApiError(409, '骨架已经被改过，请刷新后重试'))
    const w = mount(SkeletonPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    expect(get).toHaveBeenCalledTimes(1)
    await w.find('[data-test="章名-0-0"]').trigger('dblclick')
    await w.find('[data-test="章名输入-0-0"]').setValue('新章名')
    await w.find('[data-test="章名输入-0-0"]').trigger('keyup.enter')
    await flushPromises()
    // 保存失败：加载()会先跑一遍（重新拉最新状态，不留着失败前的半成品），报错要留在最后，
    // 不能被加载()清空——不然作者会以为保存成功了。
    expect(get).toHaveBeenCalledTimes(2)
    expect(w.text()).toContain('骨架已经被改过，请刷新后重试')
  })

  it('M3：保存前去掉 absent，保存后重新加载让 flag/absent 恢复', async () => {
    const 原 = 造骨架({ absent: ['S-0099'] })
    const get = vi.spyOn(api, 'getSkeleton').mockResolvedValue(原)
    const put = vi.spyOn(api, 'putSkeleton').mockResolvedValue({ ...造骨架(), by: 'author' })
    const w = mount(SkeletonPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    expect(w.text()).toContain('S-0099')
    await w.find('[data-test="章名-0-0"]').trigger('dblclick')
    await w.find('[data-test="章名输入-0-0"]').setValue('新章名')
    await w.find('[data-test="章名输入-0-0"]').trigger('keyup.enter')
    await flushPromises()
    expect(put.mock.calls[0][1]).not.toHaveProperty('absent')
    expect(get).toHaveBeenCalledTimes(2)
    expect(w.text()).toContain('S-0099')   // 重新 GET 过，absent 提醒没有因为 PUT 的回包丢掉
  })

  it('M4：任务失败时提示，不再只是默默刷新', async () => {
    vi.useFakeTimers()
    vi.spyOn(api, 'getSkeleton').mockResolvedValue(造骨架())
    vi.spyOn(api, 'currentJob')
      .mockResolvedValueOnce({ ...job, status: 'queued' })
      .mockResolvedValueOnce({ ...job, status: 'failed', error: '模型欠费' })
    const w = mount(SkeletonPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    expect(w.text()).toContain('模型欠费')
    vi.useRealTimers()
  })

  it('M4：input_changed 时提示重新生成', async () => {
    vi.useFakeTimers()
    vi.spyOn(api, 'getSkeleton').mockResolvedValue(造骨架())
    vi.spyOn(api, 'currentJob')
      .mockResolvedValueOnce({ ...job, status: 'queued' })
      .mockResolvedValueOnce({ ...job, status: 'done',
        result: { written: false, input_changed: true, failed: [] } })
    const w = mount(SkeletonPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    expect(w.text()).toContain('输入变了，请重新生成')
    vi.useRealTimers()
  })

  it('M4：failed 非空但写入成功时说明用了兜底', async () => {
    vi.useFakeTimers()
    vi.spyOn(api, 'getSkeleton').mockResolvedValue(造骨架())
    vi.spyOn(api, 'currentJob')
      .mockResolvedValueOnce({ ...job, status: 'queued' })
      .mockResolvedValueOnce({ ...job, status: 'done',
        result: { written: true, input_changed: false, failed: [{ call: 'chapters/0', error: 'x' }] } })
    const w = mount(SkeletonPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    expect(w.text()).toContain('用了程序兜底')
    vi.useRealTimers()
  })

  it('S2：场景行显示摘要和线名', async () => {
    const sk = 造骨架()
    const it0 = sk.volumes[0].chapters[0].items[0] as unknown as Record<string, unknown>
    it0.summary = '悟空大闹天宫的开端'
    it0.thread_name = '取经'
    vi.spyOn(api, 'getSkeleton').mockResolvedValue(sk)
    const w = mount(SkeletonPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    const scene = w.find('[data-test="场景-S-0001"]')
    expect(scene.text()).toContain('悟空大闹天宫的开端')
    expect(scene.text()).toContain('取经')
  })

  it('S3：章节备注带线名，查不到名字就退回编号', async () => {
    const sk = 造骨架()
    const it0 = sk.volumes[0].chapters[1].items[0] as unknown as Record<string, unknown>
    it0.thread = 'L-003'
    it0.thread_name = '奇怪的世界'
    vi.spyOn(api, 'getSkeleton').mockResolvedValue(sk)
    const w = mount(SkeletonPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    expect(w.text()).toContain('去留未定：奇怪的世界')   // 章0的备注，线名从章1里的场景项查到
    await w.find('[data-test="章名-0-1"]').trigger('click')   // 切到章1看它自己的备注
    expect(w.text()).toContain('此处原与被砍的 L-004 交汇')   // L-004 全书没有场景项带名字，退回编号
  })

  it('建议5：移章把卷移空了删掉空卷，选中跟着移动的章走', async () => {
    const sk = 造骨架()
    sk.volumes[0].chapters = [sk.volumes[0].chapters[0]]
    sk.volumes.push({ title: '第二卷', chapters: [{ title: '归来', notes: [], items: [] }] })
    let 当前 = sk
    vi.spyOn(api, 'getSkeleton').mockImplementation(async () => 当前)
    const put = vi.spyOn(api, 'putSkeleton').mockImplementation(async (_n, x) => {
      当前 = x
      return x
    })
    const w = mount(SkeletonPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="章下移-0-0"]').trigger('click')
    await flushPromises()
    const saved = put.mock.calls[0][1]
    expect(saved.volumes.length).toBe(1)
    expect(saved.volumes[0].chapters.map((c) => c.title)).toEqual(['开篇', '归来'])
    expect(w.find('[data-test="条目"] h2').text()).toBe('开篇')
  })

  it('建议6：空洞也能移到上一章/下一章，跟场景同一套函数', async () => {
    vi.spyOn(api, 'getSkeleton').mockResolvedValue(造骨架())
    const put = vi.spyOn(api, 'putSkeleton').mockImplementation(async (_n, sk) => sk)
    const w = mount(SkeletonPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="下移空洞-H-001"]').trigger('click')
    await flushPromises()
    const saved = put.mock.calls[0][1]
    expect(saved.volumes[0].chapters[0].items.map((i) => i.id)).toEqual(['S-0001', 'S-0004'])
    expect(saved.volumes[0].chapters[1].items.map((i) => i.id)).toEqual(['H-001', 'S-0005'])
  })

  it('建议7：404但不是「还没有骨架」时按普通错误显示，不当空态', async () => {
    vi.spyOn(api, 'getSkeleton').mockRejectedValue(new ApiError(404, '还没有归线结果，先跑步骤 6'))
    const w = mount(SkeletonPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="空态"]').exists()).toBe(false)
    expect(w.text()).toContain('还没有归线结果，先跑步骤 6')
  })

  it('补测：跨卷上移插到上一卷末尾，不是卷首', async () => {
    const sk = 造骨架()
    sk.volumes.unshift({ title: '第零卷', chapters: [{ title: '楔子', notes: [], items: [] }] })
    let 当前 = sk
    vi.spyOn(api, 'getSkeleton').mockImplementation(async () => 当前)
    const put = vi.spyOn(api, 'putSkeleton').mockImplementation(async (_n, x) => {
      当前 = x
      return x
    })
    const w = mount(SkeletonPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="章上移-1-0"]').trigger('click')
    await flushPromises()
    const saved = put.mock.calls[0][1]
    expect(saved.volumes[0].chapters.map((c) => c.title)).toEqual(['楔子', '开篇'])
  })

  it('补测：场景移到上一章插在章尾，不是章首', async () => {
    vi.spyOn(api, 'getSkeleton').mockResolvedValue(造骨架())
    const put = vi.spyOn(api, 'putSkeleton').mockImplementation(async (_n, sk) => sk)
    const w = mount(SkeletonPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="章名-0-1"]').trigger('click')
    const btn = w.find('[data-test="场景-S-0005"] button')
    await btn.trigger('click')
    await flushPromises()
    const saved = put.mock.calls[0][1]
    expect(saved.volumes[0].chapters[0].items.map((i) => i.id)).toEqual(['S-0001', 'H-001', 'S-0004', 'S-0005'])
  })

  it('补测：absent 提醒正常显示', async () => {
    vi.spyOn(api, 'getSkeleton').mockResolvedValue(造骨架({ absent: ['S-0099'] }))
    const w = mount(SkeletonPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    expect(w.text()).toContain('本该在书里')
    expect(w.text()).toContain('S-0099')
  })

  it('补测：not_main 提示文案正常显示', async () => {
    const sk = 造骨架()
    const it0 = sk.volumes[0].chapters[0].items[0] as unknown as Record<string, unknown>
    it0.flag = 'not_main'
    vi.spyOn(api, 'getSkeleton').mockResolvedValue(sk)
    const w = mount(SkeletonPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    expect(w.find('[data-test="场景-S-0001"]').text()).toContain('这个版本已经不是主版本了')
  })

  it('补测：没有选中章节时「放进当前章」按钮禁用', async () => {
    const sk = 造骨架()
    sk.volumes[0].chapters = []
    vi.spyOn(api, 'getSkeleton').mockResolvedValue(sk)
    const w = mount(SkeletonPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    const btn = w.find('[data-test="未定位"] button')
    expect(btn.attributes('disabled')).toBeDefined()
  })

  it('补测：任务进行中时空洞说明输入框禁用', async () => {
    vi.spyOn(api, 'getSkeleton').mockResolvedValue(造骨架())
    vi.spyOn(api, 'generateSkeleton').mockResolvedValue(job)
    const w = mount(SkeletonPage, { props: { name: 'x' }, global: { stubs } })
    await flushPromises()
    await w.find('[data-test="生成"]').trigger('click')
    await flushPromises()
    const ta = w.find('[data-test="空洞输入-H-001"]')
    expect(ta.attributes('disabled')).toBeDefined()
  })
})
