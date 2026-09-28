<script setup lang="ts">
import { ref, reactive, computed, inject, onMounted, onUnmounted } from 'vue'
import {
  getThreads, listCards, mergeThreads, moveScenes, rejectPending, renameThread, setMainThread, splitThread,
} from '@/api/endpoints'
import type { ThreadsFile, Thread, PendingScene, UnassignedScene } from '@/api/types'
import { ApiError } from '@/api/client'
import { useJobStore } from '@/stores/job'
import ErrorBox from '@/components/ErrorBox.vue'
import SceneRefs from '@/components/SceneRefs.vue'

const props = defineProps<{ name: string }>()

const jobStore = useJobStore()
const 刷新书 = inject<() => Promise<void>>('刷新书')

const data = ref<ThreadsFile | null>(null)
const error = ref('')

/** 归入用的选线状态，key 是场景 id（unassigned 的块用）。 */
const 选线 = reactive<Record<string, string>>({})

async function 报错(e: unknown): Promise<void> {
  error.value = e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e)
}

async function 加载(): Promise<void> {
  error.value = ''
  try {
    data.value = await getThreads(props.name)
  } catch (e) {
    await 报错(e)
  }
}

const 排序失败的线 = computed<Thread[]>(() => data.value?.threads.filter((t) => t.order_failed) ?? [])
const pending = computed<PendingScene[]>(() => data.value?.pending ?? [])
const unassigned = computed<UnassignedScene[]>(() => data.value?.unassigned ?? [])
const threads = computed<Thread[]>(() => data.value?.threads ?? [])

function 线名(tid: string | null): string {
  if (!tid) return '（未知线）'
  return threads.value.find((t) => t.id === tid)?.name ?? tid
}

async function 接受待归(p: PendingScene): Promise<void> {
  error.value = ''
  try {
    await moveScenes(props.name, p.thread, { ids: [p.scene] })
    delete 选线[p.scene]
    await 加载()
    await 刷新书?.()
  } catch (e) {
    await 报错(e)
  }
}

/**
 * 拒绝要落盘（F1 G1）：以前只在前端把这行换成选线控件，后端没存，刷新后 pending 又回来——
 * 界面像是拒绝了、其实没有，是本项目最忌讳的假确认。现在调 POST /threads/reject 把块从
 * pending 挪进 unassigned，成功后重拉；被拒的块自然出现在下面「未分配的块」里，那里本来就能选线归入。
 */
async function 拒绝(p: PendingScene): Promise<void> {
  error.value = ''
  try {
    await rejectPending(props.name, [p.scene])
    await 加载()
    await 刷新书?.()
  } catch (e) {
    await 报错(e)
  }
}

/** 拖拽归入：未分配的块拖到线列表的某一行上＝归入那条线。下拉框 + 按钮照旧能用。 */
const 拖块 = ref('')
const 悬停线 = ref('')

function 开始拖块(e: DragEvent, sid: string): void {
  if (jobStore.busy) {
    e.preventDefault()
    return
  }
  拖块.value = sid
  e.dataTransfer?.setData('text/plain', sid) // Firefox 不 setData 不让拖
}

function 结束拖块(): void {
  拖块.value = ''
  悬停线.value = ''
}

function 经过线(e: DragEvent, tid: string): void {
  if (!拖块.value) return // 别的东西（比如选中的文字）拖过来不接
  e.preventDefault()
  悬停线.value = tid
}

async function 放到线(tid: string): Promise<void> {
  const sid = 拖块.value
  结束拖块()
  if (!sid) return
  选线[sid] = tid
  await 归入(sid)
}

async function 归入(sid: string): Promise<void> {
  const tid = 选线[sid]
  if (!tid) {
    error.value = '先选一条线'
    return
  }
  error.value = ''
  try {
    await moveScenes(props.name, tid, { ids: [sid] })
    delete 选线[sid]
    await 加载()
    await 刷新书?.()
  } catch (e) {
    await 报错(e)
  }
}

const 改名草稿 = reactive<Record<string, string>>({})

/** 世界列原来只显示 W-01，这里换成世界名（查不到名字的只显示编号，编号放 title 里）。 */
const 世界名 = computed<Record<string, string>>(() =>
  Object.fromEntries((data.value?.worlds ?? []).filter((w) => w.name).map((w) => [w.id, w.name])))
function 开始改名(t: Thread): void {
  改名草稿[t.id] = t.name
}
async function 保存改名(t: Thread): Promise<void> {
  const name = (改名草稿[t.id] ?? '').trim()
  if (!name || name === t.name) {
    delete 改名草稿[t.id]
    return
  }
  error.value = ''
  try {
    await renameThread(props.name, t.id, { name })
    delete 改名草稿[t.id]
    await 加载()
  } catch (e) {
    await 报错(e)
  }
}

async function 设为主线(t: Thread): Promise<void> {
  error.value = ''
  try {
    await setMainThread(props.name, { thread: t.id })
    await 加载()
  } catch (e) {
    await 报错(e)
  }
}

/** 合并：后端 merge_threads 保留 ids[0]，其余线的块并进来、时间估计丢掉。勾了主线就一律保留主线
 *  （主线被并进别的线，主线全部块都会没有时间、在骨架里掉进未定位）；没勾主线就保留先勾的那条。 */
const 合并选中 = ref<string[]>([])
const 合并确认中 = ref(false)
const 合并顺序 = computed<string[]>(() => {
  const main = data.value?.main_thread
  return main && 合并选中.value.includes(main) ? [main, ...合并选中.value.filter((x) => x !== main)] : 合并选中.value
})
const 保留的线 = computed<Thread | null>(() => threads.value.find((t) => t.id === 合并顺序.value[0]) ?? null)

async function 合并(): Promise<void> {
  error.value = ''
  try {
    await mergeThreads(props.name, { ids: 合并顺序.value })
    合并选中.value = []
    合并确认中.value = false
    await 加载()
    await 刷新书?.()
  } catch (e) {
    await 报错(e)
  }
}

/** 拆分：展开一条线的场景列表，从某一块起（含）拆成新线。摘要按需拉一次卡片列表。 */
const 拆分中 = ref<string | null>(null)
const 摘要 = ref<Record<string, string>>({})
const 拆分的线 = computed<Thread | null>(() => threads.value.find((t) => t.id === 拆分中.value) ?? null)

async function 开始拆分(t: Thread): Promise<void> {
  拆分中.value = 拆分中.value === t.id ? null : t.id
  if (拆分中.value && Object.keys(摘要.value).length === 0) {
    try {
      摘要.value = Object.fromEntries((await listCards(props.name)).map((r) => [r.id, r.summary]))
    } catch {
      摘要.value = {}
    }
  }
}

async function 从这里拆(t: Thread, sid: string): Promise<void> {
  error.value = ''
  try {
    await splitThread(props.name, t.id, { from_scene: sid })
    拆分中.value = null
    await 加载()
    await 刷新书?.()
  } catch (e) {
    await 报错(e)
  }
}

onMounted(() => {
  jobStore.start()
  void 加载()
})
onUnmounted(() => {
  jobStore.stop()
})
</script>

<template>
  <div class="page">
    <h1>归线排序 —— 《{{ name }}》</h1>
    <ErrorBox :message="error" />

    <section v-if="排序失败的线.length > 0" class="block" data-test="排序失败">
      <div v-for="t in 排序失败的线" :key="t.id" class="fail-row">
        <b>{{ t.name }}（{{ t.id }}）</b>
        <span>这条线排序失败，顺序不可信。可以手动调，或者重跑步骤 6。</span>
      </div>
    </section>

    <section class="block">
      <h2>待确认的块（{{ pending.length }}）</h2>
      <p v-if="pending.length === 0" class="empty">没有模型建议的归入。</p>
      <div v-for="p in pending" :key="p.scene" class="pending-row">
        <span class="scene">{{ p.scene }}</span>
        <span class="arrow">→</span>
        <span class="target">{{ p.thread }} {{ 线名(p.thread) }}（{{ p.reason || '模型建议' }}）</span>
        <button :data-test="`接受-${p.scene}`" :disabled="jobStore.busy" @click="接受待归(p)">接受</button>
        <button :data-test="`拒绝-${p.scene}`" :disabled="jobStore.busy" @click="拒绝(p)">拒绝</button>
      </div>
    </section>

    <section class="block">
      <h2>未分配的块（{{ unassigned.length }}）</h2>
      <p v-if="unassigned.length === 0" class="empty">没有未分配的块。</p>
      <p v-if="unassigned.length > 0" class="hint">可以把块直接拖到下面线列表的某一行上归入。</p>
      <div v-for="u in unassigned" :key="u.scene" class="unassigned-row" :data-test="`未分配-${u.scene}`"
           :draggable="!jobStore.busy" @dragstart="开始拖块($event, u.scene)" @dragend="结束拖块">
        <span class="grip" title="拖动">⠿</span>
        <span class="scene">{{ u.scene }}</span>
        <span class="reason">{{ u.reason }}</span>
        <select v-model="选线[u.scene]">
          <option value="">选一条线…</option>
          <option v-for="t in threads" :key="t.id" :value="t.id">{{ t.name }}（{{ t.id }}）</option>
        </select>
        <button :data-test="`归入-${u.scene}`" :disabled="jobStore.busy || !选线[u.scene]" @click="归入(u.scene)">
          归入
        </button>
      </div>
    </section>

    <section class="block">
      <h2>线列表（{{ threads.length }}）</h2>
      <div v-if="合并选中.length >= 2" class="merge-bar" data-test="合并条">
        合并 {{ 合并选中.length }} 条线，保留「{{ 保留的线?.name }}」（{{ 保留的线?.id === data?.main_thread ? '主线' : '先勾的那条' }}），其余的块并进来。
        <template v-if="!合并确认中">
          <button data-test="合并" :disabled="jobStore.busy" @click="合并确认中 = true">合并…</button>
        </template>
        <template v-else>
          <span class="warn">并进来的线原来的时间估计会丢掉，要重新跑归线排序才有。</span>
          <button data-test="确定合并" :disabled="jobStore.busy" @click="合并">确定合并</button>
          <button @click="合并确认中 = false">算了</button>
        </template>
      </div>
      <table v-if="threads.length > 0" class="threads">
        <thead>
          <tr>
            <th></th><th>线名</th><th>世界</th><th>场景数</th><th>完结</th><th>概述</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in threads" :key="t.id" :data-test="`线行-${t.id}`" :class="{ 'drop-on': 悬停线 === t.id }"
              @dragover="经过线($event, t.id)" @dragleave="悬停线 = ''" @drop.prevent="放到线(t.id)">
            <td><input v-model="合并选中" type="checkbox" :value="t.id" :data-test="`合并勾选-${t.id}`" title="勾两条以上可以合并" @change="合并确认中 = false" /></td>
            <td>
              <span v-if="data?.main_thread === t.id" class="main-badge" title="主线">★</span>
              <input
                v-if="改名草稿[t.id] !== undefined"
                v-model="改名草稿[t.id]"
                :data-test="`改名输入-${t.id}`"
                @keyup.enter="保存改名(t)"
                @blur="保存改名(t)"
              />
              <span v-else @dblclick="开始改名(t)">{{ t.name }}</span>
            </td>
            <td :title="t.world" :data-test="`世界-${t.id}`">{{ 世界名[t.world] ?? t.world }}</td>
            <td>{{ t.scenes.length }}</td>
            <td>{{ t.end?.state ?? '待定' }}</td>
            <td class="about">{{ t.about }}</td>
            <td>
              <button
                v-if="data?.main_thread !== t.id"
                :data-test="`设为主线-${t.id}`"
                :disabled="jobStore.busy"
                @click="设为主线(t)"
              >
                设为主线
              </button>
              <button
                v-if="t.scenes.length > 1"
                :data-test="`拆分-${t.id}`"
                :disabled="jobStore.busy"
                @click="开始拆分(t)"
              >
                {{ 拆分中 === t.id ? '收起' : '拆分' }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-if="拆分的线" class="split" data-test="拆分面板">
        <p>从哪一块起拆出新线？这一块和它后面的都拆出去，新线叫「{{ 拆分的线.name }}（拆出）」，双击线名可以改。</p>
        <div v-for="(sid, i) in 拆分的线.scenes" :key="sid" class="split-row">
          <span class="sid"><SceneRefs :text="sid" :book="name" /></span>
          <span class="sum">{{ 摘要[sid] ?? '' }}</span>
          <button v-if="i > 0" :data-test="`从这里拆-${sid}`" :disabled="jobStore.busy" @click="从这里拆(拆分的线, sid)">从这里拆</button>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.page{padding:24px;max-width:960px}
h1{font-family:var(--serif);font-size:20px;margin:16px 0}
h2{font-size:15px;margin:0 0 8px}
.block{margin-bottom:24px}
.empty{color:var(--ink-3)}
.hint{font-size:12px;color:var(--ink-3);margin:0 0 6px}
.grip{color:var(--ink-3);cursor:grab;user-select:none}
[draggable="true"]{cursor:grab}
.drop-on{outline:2px dashed var(--accent);outline-offset:-2px;background:var(--accent-soft)}
.fail-row{
  display:flex;flex-direction:column;gap:4px;background:var(--red-soft);color:var(--red);
  border-radius:8px;padding:10px 12px;margin-bottom:8px;
}
.pending-row,.unassigned-row{
  display:flex;align-items:center;gap:10px;padding:8px 0;border-bottom:1px solid var(--line-2);font-size:13px;
}
.arrow{color:var(--ink-3)}
.target{flex:1;color:var(--ink-2)}
.reason{flex:1;color:var(--ink-3)}
.threads{width:100%;border-collapse:collapse;font-size:13px}
.merge-bar{display:flex;flex-wrap:wrap;align-items:center;gap:8px;background:var(--accent-soft);border-radius:6px;padding:8px 10px;margin-bottom:8px;font-size:13px}
.merge-bar .warn{color:var(--amber)}
.split{margin-top:12px;border:1px solid var(--line-2);border-radius:8px;padding:10px;font-size:13px}
.split-row{display:flex;align-items:center;gap:8px;padding:4px 0;border-bottom:1px solid var(--line-2)}
.split-row .sum{flex:1;color:var(--ink-2)}
.threads th{text-align:left;color:var(--ink-3);font-weight:400;padding:6px 8px;border-bottom:1px solid var(--line)}
.threads td{padding:6px 8px;border-bottom:1px solid var(--line-2)}
.threads .about{color:var(--ink-2);max-width:280px}
.main-badge{color:var(--amber);margin-right:4px}
</style>
