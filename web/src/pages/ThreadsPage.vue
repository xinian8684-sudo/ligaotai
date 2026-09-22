<script setup lang="ts">
import { ref, reactive, computed, inject, onMounted, onUnmounted } from 'vue'
import {
  getThreads, moveScenes, rejectPending, renameThread, setMainThread,
} from '@/api/endpoints'
import type { ThreadsFile, Thread, PendingScene, UnassignedScene } from '@/api/types'
import { ApiError } from '@/api/client'
import { useJobStore } from '@/stores/job'
import ErrorBox from '@/components/ErrorBox.vue'

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
      <div v-for="u in unassigned" :key="u.scene" class="unassigned-row">
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
      <table v-if="threads.length > 0" class="threads">
        <thead>
          <tr>
            <th>线名</th><th>世界</th><th>场景数</th><th>完结</th><th>概述</th><th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in threads" :key="t.id">
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
            <td>{{ t.world }}</td>
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
            </td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<style scoped>
.page{padding:24px;max-width:960px}
h1{font-family:var(--serif);font-size:20px;margin:16px 0}
h2{font-size:15px;margin:0 0 8px}
.block{margin-bottom:24px}
.empty{color:var(--ink-3)}
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
.threads th{text-align:left;color:var(--ink-3);font-weight:400;padding:6px 8px;border-bottom:1px solid var(--line)}
.threads td{padding:6px 8px;border-bottom:1px solid var(--line-2)}
.threads .about{color:var(--ink-2);max-width:280px}
.main-badge{color:var(--amber);margin-right:4px}
</style>
