<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { getArchiveIndex, getArchiveBody, getArchiveMap, getThreads, rerunArchive } from '@/api/endpoints'
import type { ArchiveIndex, ArchiveEntry } from '@/api/types'
import { ApiError } from '@/api/client'
import { useJobStore } from '@/stores/job'
import ErrorBox from '@/components/ErrorBox.vue'

const props = defineProps<{ name: string }>()

const jobStore = useJobStore()

const index = ref<ArchiveIndex | null>(null)
const error = ref('')
/** 编号 → 名字。档案索引里只有编号；线名读不到（还没跑步骤 6）就退回只显示编号，不当错误。 */
const 名字 = ref<Record<string, string>>({})

type Kind = 'thread' | 'world' | 'map'
interface Row { kind: Kind; id: string; label: string; entry: ArchiveEntry }

async function 报错(e: unknown): Promise<void> {
  error.value = e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e)
}

async function 加载(): Promise<void> {
  error.value = ''
  try {
    index.value = await getArchiveIndex(props.name)
  } catch (e) {
    await 报错(e)
  }
  try {
    const t = await getThreads(props.name)
    const m: Record<string, string> = {}
    for (const w of t.worlds) m[w.id] = w.name
    for (const th of t.threads) m[th.id] = th.name
    名字.value = m
  } catch {
    名字.value = {}
  }
}

function 标签(id: string): string {
  const n = 名字.value[id]
  return n ? `${id} · ${n}` : id
}

const 支线行 = computed<Row[]>(() => {
  const t = index.value?.threads ?? {}
  return Object.keys(t).sort().map((id) => ({ kind: 'thread' as const, id, label: 标签(id), entry: t[id] }))
})
const 世界行 = computed<Row[]>(() => {
  const w = index.value?.worlds ?? {}
  return Object.keys(w).sort().map((id) => ({ kind: 'world' as const, id, label: 标签(id), entry: w[id] }))
})
const 地图行 = computed<Row | null>(() => {
  const m = index.value?.map
  return m ? { kind: 'map' as const, id: 'map', label: '全书地图', entry: m } : null
})

function 换模型(row: Row): boolean {
  const cur = index.value?.current_model
  return !!row.entry.model && !!cur && row.entry.model !== cur
}

const 选中 = ref<Row | null>(null)
const 正文 = ref('')
const 正文错误 = ref('')

async function 选(row: Row): Promise<void> {
  选中.value = row
  正文.value = ''
  正文错误.value = ''
  try {
    const r = row.kind === 'map' ? await getArchiveMap(props.name) : await getArchiveBody(props.name, row.kind, row.id)
    正文.value = r.body
  } catch (e) {
    正文错误.value = e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e)
  }
}

async function 标过期(row: Row): Promise<void> {
  error.value = ''
  const body = { threads: row.kind === 'thread' ? [row.id] : [], worlds: row.kind === 'world' ? [row.id] : [],
    map: row.kind === 'map' }
  try {
    // rerunArchive 只是把 index.json 里的条目标 outdated，不是任务（不经 JobRunner），
    // 不走 jobStore.track；下次真的跑步骤 7 才是任务。
    await rerunArchive(props.name, body)
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
    <h1>设定库 —— 《{{ name }}》</h1>
    <ErrorBox :message="error" />

    <div class="layout">
      <aside class="list-pane">
        <section class="block">
          <h2>支线档案（{{ 支线行.length }}）</h2>
          <p v-if="支线行.length === 0" class="empty">还没有支线档案，跑一次步骤 7 试试。</p>
          <div v-for="row in 支线行" :key="row.id" class="entry" :class="{ active: 选中?.id === row.id && 选中.kind === row.kind }">
            <div class="row1" :data-test="`条目-${row.id}`" @click="选(row)">
              <b>{{ row.label }}</b>
              <span v-if="row.entry.outdated" class="tag outdated">过期</span>
              <span v-if="row.entry.model" class="model">{{ row.entry.model }}</span>
            </div>
            <div v-if="换模型(row)" class="hint" data-test="换模型提示">
              这份是 {{ row.entry.model }} 模型写的，当前配置是 {{ index?.current_model }}，要重跑吗？
              <button :data-test="`标过期-${row.id}`" :disabled="jobStore.busy" @click.stop="标过期(row)">
                标记为需要重跑（下次跑步骤 7 时才会真跑）
              </button>
            </div>
          </div>
        </section>

        <section class="block">
          <h2>世界设定集（{{ 世界行.length }}）</h2>
          <p v-if="世界行.length === 0" class="empty">还没有世界设定集。</p>
          <div v-for="row in 世界行" :key="row.id" class="entry" :class="{ active: 选中?.id === row.id && 选中.kind === row.kind }">
            <div class="row1" :data-test="`条目-${row.id}`" @click="选(row)">
              <b>{{ row.label }}</b>
              <span v-if="row.entry.outdated" class="tag outdated">过期</span>
              <span v-if="row.entry.model" class="model">{{ row.entry.model }}</span>
            </div>
            <div v-if="换模型(row)" class="hint" data-test="换模型提示">
              这份是 {{ row.entry.model }} 模型写的，当前配置是 {{ index?.current_model }}，要重跑吗？
              <button :data-test="`标过期-${row.id}`" :disabled="jobStore.busy" @click.stop="标过期(row)">
                标记为需要重跑（下次跑步骤 7 时才会真跑）
              </button>
            </div>
          </div>
        </section>

        <section v-if="地图行" class="block">
          <h2>全书地图</h2>
          <div class="entry" :class="{ active: 选中?.kind === 'map' }">
            <div class="row1" data-test="条目-map" @click="选(地图行)">
              <b>{{ 地图行.label }}</b>
              <span v-if="地图行.entry.outdated" class="tag outdated">过期</span>
              <span v-if="地图行.entry.model" class="model">{{ 地图行.entry.model }}</span>
            </div>
            <div v-if="换模型(地图行)" class="hint" data-test="换模型提示">
              这份是 {{ 地图行.entry.model }} 模型写的，当前配置是 {{ index?.current_model }}，要重跑吗？
              <button data-test="标过期-map" :disabled="jobStore.busy" @click.stop="标过期(地图行)">
                标记为需要重跑（下次跑步骤 7 时才会真跑）
              </button>
            </div>
          </div>
        </section>
      </aside>

      <section v-if="选中" class="body-pane">
        <h2>{{ 选中.label }}</h2>
        <ErrorBox :message="正文错误" />
        <pre v-if="正文" class="body">{{ 正文 }}</pre>
      </section>
    </div>
  </div>
</template>

<style scoped>
.page{padding:24px;max-width:1100px}
h1{font-family:var(--serif);font-size:20px;margin:16px 0}
h2{font-size:15px;margin:0 0 8px}
.block{margin-bottom:20px}
.empty{color:var(--ink-3);font-size:13px}
.layout{display:flex;gap:16px;align-items:flex-start}
.list-pane{width:360px;flex:none}
.entry{border:1px solid var(--line-2);border-radius:8px;padding:8px 10px;margin-bottom:8px;font-size:13px}
.entry.active{border-color:var(--accent)}
.row1{display:flex;align-items:center;gap:8px;cursor:pointer}
.tag.outdated{background:var(--amber-soft);color:var(--amber);font-size:11px;padding:1px 6px;border-radius:999px}
.model{margin-left:auto;color:var(--ink-3);font-size:12px}
.hint{margin-top:6px;padding:8px;background:var(--accent-soft);color:var(--ink-2);border-radius:6px;font-size:12px}
.hint button{margin-top:6px}
.body-pane{flex:1;min-width:0}
.body{white-space:pre-wrap;font-family:var(--mono);font-size:13px;line-height:1.7;max-height:80vh;overflow:auto}
</style>
