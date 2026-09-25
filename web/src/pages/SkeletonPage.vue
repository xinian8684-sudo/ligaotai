<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { exportBook, exportUrl, generateSkeleton, getSkeleton, putSkeleton } from '@/api/endpoints'
import type { ExportResult, SkChapter, SkHole, SkItem, SkNote, Skeleton } from '@/api/types'
import { ApiError } from '@/api/client'
import { useJobStore } from '@/stores/job'
import ErrorBox from '@/components/ErrorBox.vue'

const props = defineProps<{ name: string }>()
const jobStore = useJobStore()

const sk = ref<Skeleton | null>(null)
const 没有 = ref(false)
const error = ref('')
const 选中 = ref<[number, number]>([0, 0])
const 确认中 = ref(false)
const 导出结果 = ref<ExportResult | null>(null)
const 改名 = ref<Record<string, string | undefined>>({})

const 原因: Record<string, string> = { no_time: '没有时间', unaligned_thread: '这条线没对齐主线', unassigned: '没归到任何线', no_anchor: '前后都没有锚点' }
const flag文字: Record<string, string> = { missing: '原稿里已经没有这一块了', cut: '这条线已经在看板上砍掉了', not_main: '这个版本已经不是主版本了' }

function 报错(e: unknown): void {
  error.value = e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e)
}

function 是404(e: unknown): boolean {
  return e instanceof ApiError && e.status === 404
}

async function 加载(): Promise<void> {
  error.value = ''
  try {
    sk.value = await getSkeleton(props.name)
    没有.value = false
  } catch (e) {
    if (是404(e)) {
      没有.value = true
      sk.value = null
    } else 报错(e)
  }
}

const 当前章 = computed<SkChapter | null>(() => {
  const [v, c] = 选中.value
  return sk.value?.volumes[v]?.chapters[c] ?? null
})

/** 全书章节按顺序摊平，给「上一章 / 下一章」用。 */
const 章序 = computed<[number, number][]>(() =>
  (sk.value?.volumes ?? []).flatMap((v, vi) => v.chapters.map((_, ci) => [vi, ci] as [number, number])))

function 章位置(v: number, c: number): number {
  return 章序.value.findIndex(([a, b]) => a === v && b === c)
}

async function 保存(next: Skeleton): Promise<void> {
  error.value = ''
  try {
    sk.value = await putSkeleton(props.name, next)
  } catch (e) {
    报错(e)
    await 加载()
  }
}

function 副本(): Skeleton {
  return JSON.parse(JSON.stringify(sk.value)) as Skeleton
}

async function 生成(强制 = false): Promise<void> {
  if (sk.value?.by === 'author' && !强制) {
    确认中.value = true
    return
  }
  确认中.value = false
  try {
    jobStore.track(await generateSkeleton(props.name))
  } catch (e) {
    报错(e)
  }
}

async function 导出(): Promise<void> {
  try {
    导出结果.value = await exportBook(props.name)
  } catch (e) {
    报错(e)
  }
}

function key(kind: string, v: number, c = -1): string {
  return `${kind}-${v}-${c}`
}

async function 存名字(kind: 'vol' | 'ch', v: number, c = -1): Promise<void> {
  const k = key(kind, v, c)
  const name = (改名.value[k] ?? '').trim()
  改名.value[k] = undefined
  if (!name || !sk.value) return
  const next = 副本()
  if (kind === 'vol') next.volumes[v].title = name
  else next.volumes[v].chapters[c].title = name
  await 保存(next)
}

/** 同卷内跟相邻章交换；卷首章上移挪到上一卷末尾，卷末章下移挪到下一卷开头。
 *  全书第一章 / 最后一章的按钮已经禁用，所以跨卷时相邻卷一定存在。 */
async function 移章(v: number, c: number, dir: -1 | 1): Promise<void> {
  const next = 副本()
  const vols = next.volumes
  const [ch] = vols[v].chapters.splice(c, 1)
  if (dir === -1) {
    if (c > 0) vols[v].chapters.splice(c - 1, 0, ch)
    else vols[v - 1].chapters.push(ch)
  } else if (c < vols[v].chapters.length) {
    vols[v].chapters.splice(c + 1, 0, ch)
  } else {
    vols[v + 1].chapters.unshift(ch)
  }
  await 保存(next)
}

async function 移场景(item: SkItem, dir: -1 | 1): Promise<void> {
  const [v, c] = 选中.value
  const pos = 章位置(v, c)
  const target = 章序.value[pos + dir]
  if (!target) return
  const next = 副本()
  const from = next.volumes[v].chapters[c].items
  const i = from.findIndex((x) => x.type === item.type && x.id === item.id)
  const [moved] = from.splice(i, 1)
  const to = next.volumes[target[0]].chapters[target[1]].items
  if (dir === 1) to.unshift(moved)
  else to.push(moved)
  await 保存(next)
}

async function 删空洞(h: SkHole): Promise<void> {
  const [v, c] = 选中.value
  const next = 副本()
  const items = next.volumes[v].chapters[c].items
  items.splice(items.findIndex((x) => x.type === 'hole' && x.id === h.id), 1)
  await 保存(next)
}

async function 加空洞(): Promise<void> {
  const [v, c] = 选中.value
  const next = 副本()
  const used = new Set<string>()
  for (const vol of next.volumes) for (const ch of vol.chapters) for (const it of ch.items) if (it.type === 'hole') used.add(it.id)
  for (const h of next.unplaced.holes) used.add(h.id)
  let n = used.size + 1
  while (used.has(`H-${String(n).padStart(3, '0')}`)) n++
  next.volumes[v].chapters[c].items.push({ type: 'hole', id: `H-${String(n).padStart(3, '0')}`, task: '（作者新增的空洞，写下要补什么）' })
  await 保存(next)
}

async function 改说明(h: SkHole, task: string): Promise<void> {
  const [v, c] = 选中.value
  const next = 副本()
  const it = next.volumes[v].chapters[c].items.find((x) => x.type === 'hole' && x.id === h.id) as SkHole
  it.task = task
  await 保存(next)
}

async function 放进当前章(sid: string): Promise<void> {
  const [v, c] = 选中.value
  const next = 副本()
  const i = next.unplaced.scenes.findIndex((s) => s.id === sid)
  const [s] = next.unplaced.scenes.splice(i, 1)
  next.volumes[v].chapters[c].items.push({ type: 'scene', id: s.id, thread: s.thread })
  await 保存(next)
}

function 备注(n: SkNote): string {
  if (n.kind === 'undecided') return `去留未定：${n.thread}`
  if (n.kind === 'merge') return `待并入 ${n.into} 改写：${n.thread}`
  return `此处原与被砍的 ${n.thread} 交汇`
}

const 退订 = jobStore.onFinish(() => { void 加载() })
onMounted(() => {
  jobStore.start()
  void 加载()
})
onUnmounted(() => {
  退订()
  jobStore.stop()
})
</script>

<template>
  <div class="page">
    <h1>成书骨架 —— 《{{ name }}》</h1>
    <ErrorBox :message="error" />
    <div class="bar">
      <button data-test="生成" :disabled="jobStore.busy" @click="生成()">{{ sk ? '重新生成骨架' : '生成骨架' }}</button>
      <button v-if="sk" data-test="导出" :disabled="jobStore.busy" @click="导出">导出 md / txt</button>
    </div>
    <div v-if="确认中" class="confirm">
      你改过这份骨架，重新生成会覆盖你的手改（旧版本会备份成 骨架.bak.json）。
      <button data-test="确认覆盖" :disabled="jobStore.busy" @click="生成(true)">照样重新生成</button>
      <button @click="确认中 = false">算了</button>
    </div>
    <p v-if="sk?.fallback_chapters" class="warn">模型分章没成功，用了按字数的兜底切法，章名是临时的。</p>
    <p v-if="sk?.absent && sk.absent.length" class="warn">
      {{ sk.absent.length }} 个场景按现在的线本该在书里，骨架中却找不到：{{ sk.absent.join('、') }}。重新生成骨架会补上。
    </p>
    <div v-if="导出结果" class="export" data-test="导出结果">
      已导出 {{ 导出结果.md }}、{{ 导出结果.txt }}：{{ 导出结果.chars }} 字、{{ 导出结果.scenes }} 块场景、{{ 导出结果.holes }} 个空洞<template v-if="导出结果.missing">、{{ 导出结果.missing }} 块缺失</template><template v-if="导出结果.cut">、{{ 导出结果.cut }} 块因为线被砍掉没收进书里</template>。
      <a :href="exportUrl(name, 'md')">下载 md</a> · <a :href="exportUrl(name, 'txt')">下载 txt</a>
    </div>

    <p v-if="没有" class="empty" data-test="空态">还没有骨架。先在取舍看板上定好去留（没想好的线也会先排进来），再生成。</p>

    <div v-if="sk" class="layout">
      <nav class="tree" data-test="卷章树">
        <div v-for="(v, vi) in sk.volumes" :key="vi" class="vol">
          <input v-if="改名[key('vol', vi)] !== undefined" v-model="改名[key('vol', vi)]"
                 @keyup.enter="存名字('vol', vi)" @blur="存名字('vol', vi)" />
          <b v-else @dblclick="改名[key('vol', vi)] = v.title">{{ v.title }}</b>
          <div v-for="(ch, ci) in v.chapters" :key="ci" class="ch" :class="{ on: 选中[0] === vi && 选中[1] === ci }">
            <input v-if="改名[key('ch', vi, ci)] !== undefined" v-model="改名[key('ch', vi, ci)]"
                   :data-test="`章名输入-${vi}-${ci}`" @keyup.enter="存名字('ch', vi, ci)" @blur="存名字('ch', vi, ci)" />
            <span v-else :data-test="`章名-${vi}-${ci}`" @click="选中 = [vi, ci]" @dblclick="改名[key('ch', vi, ci)] = ch.title">{{ ch.title }}</span>
            <span class="ops">
              <button :data-test="`章上移-${vi}-${ci}`" :disabled="jobStore.busy || 章位置(vi, ci) === 0" title="上移" @click="移章(vi, ci, -1)">↑</button>
              <button :data-test="`章下移-${vi}-${ci}`" :disabled="jobStore.busy || 章位置(vi, ci) === 章序.length - 1" title="下移" @click="移章(vi, ci, 1)">↓</button>
            </span>
          </div>
        </div>
      </nav>

      <section v-if="当前章" class="items" data-test="条目">
        <h2>{{ 当前章.title }}</h2>
        <div class="notes">
          <span v-for="(n, i) in 当前章.notes" :key="i" class="tag" :class="n.kind">{{ 备注(n) }}</span>
        </div>
        <template v-for="it in 当前章.items" :key="it.type + it.id">
          <div v-if="it.type === 'scene'" class="scene" :class="{ flagged: it.flag }" :data-test="`场景-${it.id}`">
            <span class="sid">{{ it.id }}</span>
            <span class="thread">{{ it.thread }}</span>
            <span v-if="it.flag" class="why">{{ flag文字[it.flag] ?? it.flag }}</span>
            <span class="ops">
              <button :disabled="jobStore.busy || 章位置(选中[0], 选中[1]) === 0" @click="移场景(it, -1)">移到上一章</button>
              <button :data-test="`下移场景-${it.id}`" :disabled="jobStore.busy || 章位置(选中[0], 选中[1]) === 章序.length - 1" @click="移场景(it, 1)">移到下一章</button>
            </span>
          </div>
          <details v-else class="hole" :data-test="`空洞-${it.id}`" open>
            <summary>空洞 {{ it.id }}</summary>
            <textarea :disabled="jobStore.busy" @change="改说明(it, ($event.target as HTMLTextAreaElement).value)">{{ it.task }}</textarea>
            <button :data-test="`删空洞-${it.id}`" :disabled="jobStore.busy" @click="删空洞(it)">删掉这个空洞</button>
          </details>
        </template>
        <button :disabled="jobStore.busy" @click="加空洞">在这里加空洞</button>
      </section>
    </div>

    <section v-if="sk && (sk.unplaced.scenes.length || sk.unplaced.holes.length)" class="unplaced" data-test="未定位">
      <h2>未定位</h2>
      <div v-for="s in sk.unplaced.scenes" :key="s.id" class="scene">
        <span class="sid">{{ s.id }}</span><span class="thread">{{ s.thread ?? '' }}</span>
        <span class="why">{{ 原因[s.why] ?? s.why }}</span>
        <button :disabled="jobStore.busy || !当前章" @click="放进当前章(s.id)">放进当前章</button>
      </div>
      <div v-for="h in sk.unplaced.holes" :key="h.id" class="hole-line">空洞 {{ h.id }}：{{ h.task }}</div>
    </section>
  </div>
</template>

<style scoped>
.page{padding:24px}
h1{font-family:var(--serif);font-size:20px;margin:16px 0}
.bar{display:flex;gap:8px;margin-bottom:10px}
.confirm{background:var(--amber-soft);color:var(--ink);padding:8px 10px;border-radius:6px;margin-bottom:10px;display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.warn{color:var(--amber);font-size:13px}
.export{background:var(--green-soft);padding:8px 10px;border-radius:6px;margin-bottom:10px;font-size:13px}
.empty{color:var(--ink-3)}
.layout{display:grid;grid-template-columns:260px minmax(0,1fr);gap:16px;align-items:start}
.tree{background:var(--panel);border:1px solid var(--line-2);border-radius:8px;padding:10px;font-size:13px}
.vol{margin-bottom:10px}
.vol b{font-family:var(--serif)}
.ch{display:flex;justify-content:space-between;align-items:center;padding:3px 6px;border-radius:4px;cursor:pointer}
.ch.on{background:var(--accent-soft);color:var(--accent)}
.ch .ops button{padding:0 6px}
.items h2{font-size:16px;margin:0 0 6px}
.notes{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}
.tag{font-size:11px;padding:1px 6px;border-radius:999px;background:var(--sunk);color:var(--ink-2)}
.tag.cut_crossing{background:var(--red-soft);color:var(--red)}
.tag.merge{background:var(--accent-soft);color:var(--accent)}
.scene{display:flex;flex-wrap:wrap;align-items:center;gap:8px;padding:6px 8px;border-bottom:1px solid var(--line-2);font-size:13px}
.scene.flagged{opacity:.55}
.sid{font-family:var(--mono)}
.thread{color:var(--accent)}
.why{color:var(--ink-3)}
.scene .ops{margin-left:auto;display:flex;gap:4px}
.hole{border:1px solid var(--red);border-radius:6px;padding:6px 8px;margin:6px 0;font-size:13px}
.hole summary{color:var(--red);cursor:pointer}
.hole textarea{width:100%;min-height:60px;margin:6px 0}
.unplaced{margin-top:18px}
.unplaced h2{font-size:15px}
.hole-line{font-size:13px;color:var(--ink-2);padding:4px 0}
</style>
