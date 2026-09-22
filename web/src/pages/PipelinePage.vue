<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { getBook, runStep } from '@/api/endpoints'
import { STEPS, STEP_LABELS } from '@/api/types'
import type { BookMeta, StepName, StepStatus } from '@/api/types'
import { ApiError } from '@/api/client'
import { useJobStore } from '@/stores/job'
import ErrorBox from '@/components/ErrorBox.vue'
import JobBar from '@/components/JobBar.vue'

const props = defineProps<{ name: string }>()

const jobStore = useJobStore()
const book = ref<BookMeta | null>(null)
const error = ref('')

const STATUS_LABELS: Record<StepStatus, string> = {
  todo: '待开始', running: '运行中', done: '已完成', failed: '失败', outdated: '过期',
}

async function 加载(): Promise<void> {
  error.value = ''
  try {
    book.value = await getBook(props.name)
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : String(e)
  }
}

/** 跟后端 require_upstream 一致：这一步之前的每一步都要是 done。 */
function 上游是否就绪(step: StepName): boolean {
  const b = book.value
  if (!b) return false
  const idx = STEPS.indexOf(step)
  return STEPS.slice(0, idx).every((s) => b.steps[s].status === 'done')
}

/**
 * 每步「一句话结果」的白名单字段。**故意白名单取字段**，不把整个 summary 倒出来——
 * 那样 cost_usd / calls 会漏出去（spec 7.3：界面一个费用数字都不显示）。
 */
type 字段 = readonly [key: string, label: string]
const FIELD_MAP: Record<StepName, 字段[]> = {
  import: [['added', '新增'], ['changed', '改动'], ['unchanged', '未变'], ['total_files', '累计文件']],
  split: [['scenes', '场景'], ['fragments', '碎片'], ['added', '新增'], ['changed', '改动'], ['removed', '移除']],
  dedup: [['scenes', '参与查重'], ['pairs', '候选对'], ['groups', '重复组']],
  cards: [['written', '写了'], ['with_problems', '有问题'], ['missing_count', '缺卡']],
  entities: [['entities', '实体数'], ['draft_groups', '待确认'], ['conflicts', '冲突组']],
  threads: [['worlds', '世界'], ['threads', '支线'], ['gaps', '缺口'], ['pending', '待归线']],
  archive: [['contradictions', '矛盾组'], ['严重', '严重矛盾'], ['skipped', '跳过']],
}

function 一句话(step: StepName, summary: Record<string, unknown>): string {
  const parts: string[] = []
  for (const [key, label] of FIELD_MAP[step] ?? []) {
    const v = summary[key]
    if (v === undefined || v === null) continue
    const n = Array.isArray(v) ? v.length : v
    parts.push(`${label} ${n}`)
  }
  return parts.join('、')
}

/** 第 5、6 步做完后，如果有待确认项，给一个「去确认」的链接。 */
function 待确认数(step: StepName): number {
  const s = book.value?.steps[step]?.summary
  if (!s) return 0
  if (step === 'entities') return Number(s.draft_groups ?? 0)
  if (step === 'threads') return Number(s.pending ?? 0)
  return 0
}

async function 跑(step: StepName): Promise<void> {
  error.value = ''
  try {
    jobStore.track(await runStep(props.name, step))
    await jobStore.refresh()
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : String(e)
  }
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
    <JobBar />
    <h1>理稿流水线 —— 《{{ book?.title ?? name }}》</h1>
    <ErrorBox :message="error" />

    <ol v-if="book" class="steps">
      <li v-for="(step, i) in STEPS" :key="step" class="row">
        <span class="idx">{{ i + 1 }}</span>
        <span class="label">{{ STEP_LABELS[step] }}</span>
        <span class="badge" :class="`s-${book.steps[step].status}`">
          {{ STATUS_LABELS[book.steps[step].status] }}
        </span>

        <span class="summary">
          <template v-if="book.steps[step].status === 'failed'">
            {{ String(book.steps[step].summary.error ?? '') }}
          </template>
          <template v-else-if="book.steps[step].status === 'outdated'">
            上游变了，这一步的结果已过期
          </template>
          <template v-else>{{ 一句话(step, book.steps[step].summary) }}</template>
        </span>

        <RouterLink
          v-if="待确认数(step) > 0"
          class="confirm"
          :to="`/b/${name}/pipeline/${step}`"
        >
          去确认（{{ 待确认数(step) }}）
        </RouterLink>

        <RouterLink v-if="step === 'import'" class="run" to="/">导入</RouterLink>
        <button
          v-else
          class="run"
          :data-test="`跑-${step}`"
          :disabled="!上游是否就绪(step) || jobStore.busy"
          @click="跑(step)"
        >
          跑
        </button>
      </li>
    </ol>
  </div>
</template>

<style scoped>
.page{padding:24px;max-width:880px}
h1{font-family:var(--serif);font-size:20px;margin:16px 0}
.steps{list-style:none;padding:0;margin:0}
.row{
  display:flex;align-items:center;gap:12px;padding:12px 0;
  border-bottom:1px solid var(--line-2);
}
.idx{color:var(--ink-3);width:18px;text-align:right;font-variant-numeric:tabular-nums}
.label{width:110px;flex:none}
.badge{
  padding:2px 8px;border-radius:999px;font-size:12px;flex:none;
  background:var(--sunk);color:var(--ink-3);
}
.badge.s-running{background:var(--accent-soft);color:var(--accent)}
.badge.s-done{background:var(--green-soft);color:var(--green)}
.badge.s-failed{background:var(--red-soft);color:var(--red)}
.badge.s-outdated{background:var(--amber-soft);color:var(--amber)}
.summary{flex:1;color:var(--ink-2);font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.confirm{flex:none;color:var(--accent);font-size:13px}
.run{flex:none}
</style>
