<script setup lang="ts">
import { ref, reactive, computed, inject, onMounted, onUnmounted } from 'vue'
import { getBook, getEntities, confirmEntities, mergeEntities, splitEntity } from '@/api/endpoints'
import type { BookMeta, Entity, EntityConflict } from '@/api/types'
import { ApiError } from '@/api/client'
import { useJobStore } from '@/stores/job'
import ErrorBox from '@/components/ErrorBox.vue'

const props = defineProps<{ name: string }>()

const jobStore = useJobStore()
const 刷新书 = inject<() => Promise<void>>('刷新书')

const book = ref<BookMeta | null>(null)
const next_id = ref(0)
const entities = ref<Entity[]>([])
const error = ref('')
const 搜索词 = ref('')

/** 每组待拆分要勾出去的叫法，key 是实体 id。 */
const 拆分选择 = reactive<Record<string, string[]>>({})

/** 冲突手动合并：key 是冲突在数组里的下标，值是勾了要合并的实体 id。 */
const 合并选择 = ref<Record<number, string[]>>({})

const TYPE_LABELS: Record<string, string> = { person: '人物', location: '地点', organization: '组织' }

async function 报错(e: unknown): Promise<void> {
  error.value = e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e)
}

async function 加载(): Promise<void> {
  error.value = ''
  try {
    book.value = await getBook(props.name)
  } catch (e) {
    await 报错(e)
  }
  try {
    const f = await getEntities(props.name)
    next_id.value = f.next_id
    entities.value = f.entities
  } catch (e) {
    await 报错(e)
  }
}

/** conflicts **不在** 实体.json 里，只在步骤跑完的 summary 里（spec 第 5 章）。 */
const conflicts = computed<EntityConflict[]>(() => {
  const s = book.value?.steps.entities.summary
  const c = s?.conflicts
  return Array.isArray(c) ? (c as EntityConflict[]) : []
})

const 待确认组 = computed(() => entities.value.filter((e) => e.status === 'draft'))
const 其他组 = computed(() => entities.value.filter((e) => e.status !== 'draft'))
const 搜索后的其他组 = computed(() => {
  const kw = 搜索词.value.trim()
  if (!kw) return 其他组.value
  return 其他组.value.filter((e) => e.canonical.includes(kw) || e.names.some((n) => n.includes(kw)))
})

/** 冲突里报的叫法，当前分别落在哪些实体里——手动合并的候选就是这些实体。 */
function 冲突候选(c: EntityConflict): Entity[] {
  return entities.value.filter((e) => e.type === c.type && e.names.some((n) => c.names.includes(n)))
}

function 已勾选(eid: string, name: string): boolean {
  return (拆分选择[eid] ?? []).includes(name)
}
function 切换勾选(eid: string, name: string): void {
  const cur = 拆分选择[eid] ?? []
  拆分选择[eid] = cur.includes(name) ? cur.filter((n) => n !== name) : [...cur, name]
}

async function 接受(ids: string[]): Promise<void> {
  error.value = ''
  try {
    await confirmEntities(props.name, ids)
    await 加载()
    await 刷新书?.()
  } catch (e) {
    await 报错(e)
  }
}

async function 全部接受(): Promise<void> {
  await 接受(待确认组.value.map((e) => e.id))
}

async function 拆开(e: Entity): Promise<void> {
  const names = 拆分选择[e.id] ?? []
  if (names.length === 0) {
    error.value = '先勾出要拆走的叫法'
    return
  }
  error.value = ''
  try {
    await splitEntity(props.name, e.id, { names })
    拆分选择[e.id] = []
    await 加载()
    await 刷新书?.()
  } catch (err) {
    await 报错(err)
  }
}

function 切换合并勾选(i: number, eid: string): void {
  const cur = 合并选择.value[i] ?? []
  合并选择.value[i] = cur.includes(eid) ? cur.filter((x) => x !== eid) : [...cur, eid]
}

async function 手动合并(i: number): Promise<void> {
  const ids = 合并选择.value[i] ?? []
  if (ids.length < 2) {
    error.value = '至少勾两个才能合并'
    return
  }
  error.value = ''
  try {
    await mergeEntities(props.name, ids)
    合并选择.value[i] = []
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
    <h1>实体合并 —— 《{{ book?.title ?? name }}》</h1>
    <ErrorBox :message="error" />

    <section class="block">
      <div class="head">
        <h2>待确认的合并组（{{ 待确认组.length }}）</h2>
        <button
          v-if="待确认组.length > 0"
          data-test="全部接受"
          :disabled="jobStore.busy"
          @click="全部接受"
        >
          全部接受
        </button>
      </div>
      <p v-if="待确认组.length === 0" class="empty">没有待确认的合并组。</p>
      <div v-for="e in 待确认组" :key="e.id" class="group" data-test="待确认组">
        <div class="row1">
          <b>{{ TYPE_LABELS[e.type] ?? e.type }}</b>
          <span class="canonical">{{ e.canonical }}</span>
          <span class="scenes">涉及 {{ e.scenes.length }} 个场景</span>
        </div>
        <p class="reason">{{ e.reason || '（模型没给理由）' }}</p>
        <div class="names">
          <label v-for="n in e.names" :key="n" class="name">
            <input type="checkbox" :checked="已勾选(e.id, n)" @change="切换勾选(e.id, n)" />
            {{ n }}
          </label>
        </div>
        <div class="actions">
          <button :data-test="`接受-${e.id}`" :disabled="jobStore.busy" @click="接受([e.id])">接受</button>
          <button :data-test="`拆开-${e.id}`" :disabled="jobStore.busy" @click="拆开(e)">拆开</button>
        </div>
      </div>
    </section>

    <section v-if="conflicts.length > 0" class="block" data-test="冲突区">
      <h2>跨批冲突（{{ conflicts.length }}）</h2>
      <p class="hint">这几个叫法在不同批里被分到了不同组，程序不敢自动合。要合的话在下面选中要合并的组，点「手动合并」。</p>
      <div v-for="(c, i) in conflicts" :key="i" class="conflict">
        <div class="row1">
          <b>{{ TYPE_LABELS[c.type] ?? c.type }}</b>
          <span class="names-line">{{ c.names.join('、') }}</span>
        </div>
        <div class="candidates">
          <label v-for="cand in 冲突候选(c)" :key="cand.id" class="cand">
            <input
              type="checkbox"
              :checked="(合并选择[i] ?? []).includes(cand.id)"
              @change="切换合并勾选(i, cand.id)"
            />
            {{ cand.canonical }}（{{ cand.names.join('、') }}）
          </label>
        </div>
        <button :data-test="`手动合并-${i}`" :disabled="jobStore.busy" @click="手动合并(i)">手动合并</button>
      </div>
    </section>

    <section class="block">
      <details>
        <summary>已确认 / 独立（{{ 其他组.length }}）</summary>
        <input v-model="搜索词" placeholder="搜规范名或别名" data-test="搜索" />
        <ul class="flat">
          <li v-for="e in 搜索后的其他组" :key="e.id">
            <b>{{ e.canonical }}</b>
            <span v-if="e.names.length > 1" class="alt">（{{ e.names.filter((n) => n !== e.canonical).join('、') }}）</span>
            <span class="status">{{ e.status === 'confirmed' ? '已确认' : '独立' }}</span>
          </li>
        </ul>
      </details>
    </section>
  </div>
</template>

<style scoped>
.page{padding:24px;max-width:880px}
h1{font-family:var(--serif);font-size:20px;margin:16px 0}
h2{font-size:15px;margin:0 0 8px}
.block{margin-bottom:24px}
.head{display:flex;align-items:center;justify-content:space-between}
.empty{color:var(--ink-3)}
.group,.conflict{border:1px solid var(--line-2);border-radius:8px;padding:12px;margin-bottom:10px}
.row1{display:flex;align-items:center;gap:10px}
.canonical{font-family:var(--serif);font-size:15px}
.scenes{margin-left:auto;color:var(--ink-3);font-size:12px}
.reason{color:var(--ink-2);font-size:13px;margin:6px 0}
.names{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0}
.name{font-size:13px;color:var(--ink-2)}
.actions{display:flex;gap:8px}
.hint{color:var(--ink-2);font-size:13px}
.names-line{color:var(--ink)}
.candidates{display:flex;flex-direction:column;gap:4px;margin:8px 0;font-size:13px}
.flat{list-style:none;padding:0;margin:8px 0}
.flat li{padding:4px 0;border-bottom:1px solid var(--line-2);font-size:13px}
.alt{color:var(--ink-3)}
.status{margin-left:8px;color:var(--ink-3);font-size:12px}
</style>
