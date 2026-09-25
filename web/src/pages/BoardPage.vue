<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { deleteCard, getBoard, getImpact, putCard, runAdvice, runImpact } from '@/api/endpoints'
import type { AdviceItem, BoardCol, BoardView, ImpactView, Job } from '@/api/types'
import { ApiError } from '@/api/client'
import { useJobStore } from '@/stores/job'
import ErrorBox from '@/components/ErrorBox.vue'

const props = defineProps<{ name: string }>()
const jobStore = useJobStore()

const view = ref<BoardView | null>(null)
const error = ref('')
const 影响 = ref<Record<string, ImpactView | undefined>>({})
const 待选并入 = ref<Record<string, boolean>>({})

const 列: { key: BoardCol; label: string }[] = [
  { key: 'keep', label: '保留' },
  { key: 'merge', label: '合并' },
  { key: 'cut', label: '砍掉' },
  { key: 'undecided', label: '还没想好' },
]
const 建议文字: Record<string, string> = { keep: '建议保留', merge: '建议合并', cut: '建议砍掉', flashback: '建议改成回忆' }

function 报错(e: unknown): void {
  error.value = e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e)
}

async function 加载(): Promise<void> {
  error.value = ''
  try {
    view.value = await getBoard(props.name)
    for (const [tid, c] of Object.entries(view.value.cards)) {
      if (!c.orphan && (c.col === 'cut' || c.col === 'merge')) void 拉影响(tid)
    }
  } catch (e) {
    报错(e)
  }
}

async function 拉影响(tid: string): Promise<void> {
  try {
    影响.value[tid] = await getImpact(props.name, tid)
  } catch (e) {
    报错(e)
  }
}

const 按列 = computed(() => {
  const out: Record<BoardCol, string[]> = { keep: [], merge: [], cut: [], undecided: [] }
  for (const [tid, c] of Object.entries(view.value?.cards ?? {})) out[c.col].push(tid)
  for (const k of Object.keys(out) as BoardCol[]) out[k].sort()
  return out
})

const 活线 = computed(() => Object.entries(view.value?.cards ?? {}).filter(([, c]) => !c.orphan).map(([t]) => t).sort())

function 建议(tid: string): AdviceItem | undefined {
  return view.value?.advice?.items.find((i) => i.thread === tid)
}

function 线名(tid: string): string {
  return view.value?.stats[tid]?.name ?? tid
}

/** 建议 2：并入候选要排除已经砍掉的线（后端 set_card 会 400）——原来只排除了 cut，
 * 没排除 merge：并入一条自己也在合并列的线，后端同样会 400（合并链长只能是 1）。 */
function 并入候选(tid: string): string[] {
  return 活线.value.filter((x) => x !== tid && !['cut', 'merge'].includes(view.value!.cards[x].col))
}

async function 移到(tid: string, col: BoardCol, mergeInto?: string): Promise<void> {
  if (col === 'merge' && !mergeInto) {
    待选并入.value[tid] = true
    return
  }
  error.value = ''
  try {
    await putCard(props.name, tid, col === 'merge' ? { col, merge_into: mergeInto } : { col })
    待选并入.value[tid] = false
    await 加载()
    // 加载() 会按重新拉到的看板扫一遍要拉影响的卡；这里再显式补一次，
    // 免得测试里 getBoard 是静态 mock、看不出这次移动，导致刚移进砍掉/合并的卡拉不到影响。
    if (col === 'cut' || col === 'merge') void 拉影响(tid)
  } catch (e) {
    报错(e)
  }
}

async function 删卡(tid: string): Promise<void> {
  try {
    await deleteCard(props.name, tid)
    await 加载()
  } catch (e) {
    报错(e)
  }
}

async function 要建议(): Promise<void> {
  try {
    jobStore.track(await runAdvice(props.name))
  } catch (e) {
    报错(e)
  }
}

async function 查伏笔(tid: string): Promise<void> {
  try {
    jobStore.track(await runImpact(props.name, tid))
  } catch (e) {
    报错(e)
  }
}

// 拖放：跟「移到」下拉走同一个函数
const 拖着 = ref('')
function 开始拖(e: DragEvent, tid: string): void {
  拖着.value = tid
  // 建议 1：标准 HTML5 拖放要靠 dataTransfer 传数据，drop 事件不设默认会被浏览器拒绝
  // （某些浏览器/场景下 dragover.prevent 都不足以让 drop 生效）。
  e.dataTransfer?.setData('text/plain', tid)
}
function 结束拖(): void {
  // 建议 1：dragend 清掉拖着的卡——没落进任何列（拖到列外面松手、按 Esc 取消）时
  // 状态会一直留着，万一后面又触发一次 drop（哪怕概率很低）会把不相关的那次动作
  // 当成「还在拖同一张卡」，误移一张卡。
  拖着.value = ''
}
function 放下(col: BoardCol): void {
  if (拖着.value) void 移到(拖着.value, col)
  拖着.value = ''
}

/** M4：原来 onFinish 只重新加载，AI 建议 / 影响检查失败（模型欠费、多次不合规）
 * 没有任何提示——作者只会看到页面刷新了一下，以为任务顺利跑完了。 */
function 任务提示(job: Job): string {
  const label = job.name === 'triage_advice' ? 'AI 建议' : '影响检查'
  if (job.status !== 'done') return `${label}${job.status === 'cancelled' ? '被取消' : '失败'}：${job.error || '原因不明'}`
  const r = (job.result ?? {}) as Record<string, unknown>
  if (r.ok === false) return `${label}没有成功：模型没给出可用结果`
  return ''
}

const 退订 = jobStore.onFinish((job) => {
  if (job.name !== 'triage_advice' && job.name !== 'triage_impact') return
  void (async () => {
    await 加载()
    const msg = 任务提示(job)
    if (msg) error.value = msg
  })()
})
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
    <h1>取舍看板 —— 《{{ name }}》</h1>
    <ErrorBox :message="error" />
    <div class="bar">
      <button data-test="AI建议" :disabled="jobStore.busy" @click="要建议">
        {{ view?.advice ? '重新生成建议' : '让 AI 给建议' }}
      </button>
      <span v-if="view?.advice?.stale" class="warn">线变了，建议可能过时</span>
    </div>

    <div v-if="view" class="cols">
      <section v-for="c in 列" :key="c.key" class="col" :data-test="`列-${c.key}`"
               @dragover.prevent @drop="放下(c.key)">
        <h2>{{ c.label }}（{{ 按列[c.key].length }}）</h2>
        <article v-for="tid in 按列[c.key]" :key="tid" class="card" :class="{ orphan: view.cards[tid].orphan }"
                 :data-test="`卡-${tid}`" :draggable="!view.cards[tid].orphan && !jobStore.busy"
                 @dragstart="开始拖($event, tid)" @dragend="结束拖">
          <header>
            <b>{{ view.stats[tid]?.is_main ? '★ ' : '' }}{{ 线名(tid) }}</b>
            <span class="id">{{ tid }}</span>
          </header>
          <p v-if="view.stats[tid]" class="meta">
            {{ view.stats[tid].world }} · {{ view.stats[tid].scenes }} 块 · 约 {{ view.stats[tid].words }} 字 ·
            {{ view.stats[tid].state }} · 缺口 {{ view.stats[tid].gaps }}
          </p>
          <p v-if="view.stats[tid]?.order_failed" class="bad">这条线排序失败，顺序不可信</p>
          <p v-if="view.cards[tid].orphan" class="muted">这条线已经不在了
            <button :data-test="`删卡-${tid}`" :disabled="jobStore.busy" @click="删卡(tid)">删掉这张卡</button>
          </p>
          <p v-if="view.cards[tid].col === 'merge'" class="meta">并入 {{ 线名(view.cards[tid].merge_into ?? '') }}</p>
          <p v-if="view.cards[tid].merge_invalid" class="bad">合并目标失效：并入的线已经被砍或不存在了</p>
          <p v-if="建议(tid)" class="advice">AI：{{ 建议文字[建议(tid)!.advice] }}<template v-if="建议(tid)!.merge_into">（并入 {{ 线名(建议(tid)!.merge_into!) }}）</template>——{{ 建议(tid)!.reason }}</p>

          <div v-if="!view.cards[tid].orphan" class="move">
            <select :data-test="`移到-${tid}`" :disabled="jobStore.busy" :value="view.cards[tid].col"
                    @change="移到(tid, ($event.target as HTMLSelectElement).value as BoardCol)">
              <option v-for="o in 列" :key="o.key" :value="o.key">移到：{{ o.label }}</option>
            </select>
            <select v-if="待选并入[tid] || view.cards[tid].col === 'merge'" :data-test="`并入-${tid}`" :disabled="jobStore.busy"
                    :value="view.cards[tid].col === 'merge' ? (view.cards[tid].merge_into ?? '') : ''"
                    @change="移到(tid, 'merge', ($event.target as HTMLSelectElement).value)">
              <option value="" disabled>并入哪条线？</option>
              <option v-for="o in 并入候选(tid)" :key="o" :value="o">{{ 线名(o) }}</option>
            </select>
          </div>

          <div v-if="影响[tid] && (view.cards[tid].col === 'cut' || view.cards[tid].col === 'merge')"
               class="impact" :data-test="`影响-${tid}`">
            <div class="k">会影响</div>
            <ul>
              <li v-for="x in 影响[tid]!.program.crossings" :key="x.scene + x.main_scene">
                和 {{ 线名(x.other) }} 的交汇点：{{ x.scene }} ↔ {{ x.main_scene }}（{{ x.reason }}）
              </li>
              <li v-for="p in 影响[tid]!.program.only_characters" :key="p.name">
                只在这条线出场的人物：{{ p.name }}（{{ p.scenes.join('、') }}）
              </li>
              <li v-for="r in 影响[tid]!.program.maybe_refs" :key="r.scene + r.text">
                可能：{{ 线名(r.thread) }} 的 {{ r.scene }} 提到「{{ r.text }}」
              </li>
              <li v-for="p in 影响[tid]!.model?.pairs ?? []" :key="p.planted + p.resolved" :class="{ stale: 影响[tid]!.model!.stale }">
                伏笔：{{ p.planted }} 埋 → {{ p.resolved }} 收（{{ p.hook }}）<span v-if="影响[tid]!.model!.stale" class="stale-tag">（已过期）</span>
              </li>
            </ul>
            <p v-if="影响[tid]!.model && !影响[tid]!.model!.stale" class="remedy">{{ 影响[tid]!.model!.remedy }}</p>
            <button v-else :data-test="`检查伏笔-${tid}`" :disabled="jobStore.busy" @click="查伏笔(tid)">
              {{ 影响[tid]!.model ? '输入变了，可能过时，重新检查伏笔影响' : '检查伏笔影响' }}
            </button>
          </div>
        </article>
      </section>
    </div>
  </div>
</template>

<style scoped>
.page{padding:24px}
h1{font-family:var(--serif);font-size:20px;margin:16px 0}
.bar{display:flex;align-items:center;gap:10px;margin-bottom:14px}
.warn{color:var(--amber);font-size:13px}
.cols{display:grid;grid-template-columns:repeat(4,minmax(220px,1fr));gap:12px;align-items:start}
.col{background:var(--sunk);border-radius:8px;padding:10px;min-height:120px}
.col h2{font-size:14px;margin:0 0 8px}
.card{background:var(--panel);border:1px solid var(--line-2);border-radius:8px;padding:10px;margin-bottom:8px;font-size:13px}
.card.orphan{opacity:.6}
.card header{display:flex;justify-content:space-between;gap:6px}
.card .id{color:var(--ink-3);font-size:12px}
.meta{color:var(--ink-2);margin:4px 0}
.bad{color:var(--red);margin:4px 0}
.muted{color:var(--ink-3)}
.advice{color:var(--ink-2);background:var(--accent-soft);border-radius:6px;padding:6px;margin:6px 0}
.move{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
.impact{margin-top:8px;border-top:1px dashed var(--line);padding-top:6px}
.impact .k{font-weight:600;color:var(--red)}
.impact ul{margin:4px 0;padding-left:16px}
.impact li.stale{opacity:.6}
.stale-tag{color:var(--amber)}
.remedy{color:var(--ink-2)}
</style>
