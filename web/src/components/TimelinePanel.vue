<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { getTimeline, putTimelineVerdict, runTimeline } from '@/api/endpoints'
import type { TimelineConflict, TimelineFile, TimelineVerdictKind } from '@/api/types'
import { ApiError } from '@/api/client'
import { useJobStore } from '@/stores/job'
import ErrorBox from '@/components/ErrorBox.vue'
import SceneRefs from '@/components/SceneRefs.vue'

const props = defineProps<{ name: string }>()
const jobStore = useJobStore()
const data = ref<TimelineFile | null>(null)
const error = ref('')
const 看全部 = ref(false)

const 类型名: Record<string, string> = { A: '人死了又出场', C: '提前知道后面的事' }
const 裁决名: Record<TimelineVerdictKind, string> = { author_error: '确实写错了', order_error: '是顺序排错了', ignore: '没问题，忽略' }
const 裁决顺序: TimelineVerdictKind[] = ['author_error', 'order_error', 'ignore']

function 报错(e: unknown): void {
  error.value = e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e)
}

async function 加载(): Promise<void> {
  error.value = ''
  try {
    data.value = await getTimeline(props.name)
  } catch (e) {
    报错(e)
  }
}

async function 检查(): Promise<void> {
  try {
    jobStore.track(await runTimeline(props.name))
  } catch (e) {
    报错(e)
  }
}

async function 裁决(c: TimelineConflict, kind: TimelineVerdictKind | null): Promise<void> {
  try {
    await putTimelineVerdict(props.name, c.id, kind)
    await 加载()
  } catch (e) {
    报错(e)
  }
}

const 统计 = computed(() => {
  const cs = data.value?.conflicts ?? []
  const n = (k: TimelineVerdictKind) => cs.filter((c) => c.verdict?.kind === k).length
  return { 待看: cs.filter((c) => !c.verdict).length, 写错: n('author_error'), 排错: n('order_error'), 忽略: n('ignore') }
})

const 显示的 = computed(() => (data.value?.conflicts ?? []).filter((c) => 看全部.value || !c.verdict))

const 退订 = jobStore.onFinish((job) => {
  if (job.name !== 'timeline') return
  void (async () => {
    await 加载()
    if (job.status !== 'done') error.value = `时间线检查${job.status === 'cancelled' ? '被取消' : '失败'}：${job.error || '原因不明'}`
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
  <section class="timeline">
    <ErrorBox :message="error" />
    <div class="bar">
      <button data-test="检查时间线" :disabled="jobStore.busy" @click="检查">{{ data?.never_run ? '检查时间线' : '重新检查' }}</button>
    </div>
    <p v-if="data?.never_run" class="empty" data-test="时间线空态">
      还没检查过。会找两类问题：某人前面已经死了、后面又活着出场；某场提到的事，按故事顺序要到后面才发生。
      要先跑完归线（步骤 6）。查出来的不一定是写错了，也可能是故事顺序排错了，每条你来定。
    </p>
    <template v-else-if="data">
      <p v-if="data.stale" class="warn" data-test="时间线过期">
        顺序或场景卡变了，下面的结果可能过时，建议重新检查。
        <template v-if="data.stale_reason">（{{ data.stale_reason }}）</template>
      </p>
      <p v-if="data.failed?.length" class="warn">有 {{ data.failed.length }} 批模型没给出结果，那些嫌疑按「说不准」列出来了。</p>
      <p class="stats" data-test="时间线统计">
        待看 {{ 统计.待看 }} · 写错了 {{ 统计.写错 }} · 排错了 {{ 统计.排错 }} · 已忽略 {{ 统计.忽略 }}
        <template v-if="data.stats?.unplaced">（另有 {{ data.stats.unplaced }} 块没有故事位置，没查）</template>
        <template v-if="data.stats?.a_capped">（另有 {{ data.stats.a_capped }} 条因每人只查死后 5 场被截掉）</template>
        <template v-if="data.stats?.refs_no_candidate">（{{ data.stats.refs_no_candidate }} 条回指找不到候选）</template>
      </p>
      <div class="filters">
        <button :class="{ on: !看全部 }" data-test="只看待看" @click="看全部 = false">只看待看</button>
        <button :class="{ on: 看全部 }" data-test="看全部" @click="看全部 = true">全部</button>
      </div>
      <p v-if="(data.conflicts?.length ?? 0) === 0" class="empty" data-test="结果为空">没有查出冲突。</p>
      <p v-else-if="显示的.length === 0" class="empty" data-test="结果为空">没有待看的了。</p>
      <div v-for="c in 显示的" :key="c.id" class="card" :data-test="`冲突-${c.id}`">
        <div class="head">
          <span class="kind" :class="c.kind">{{ 类型名[c.kind] }}</span>
          <b>{{ c.kind === 'A' ? c.who : `「${c.ref}」` }}</b>
          <span v-if="c.status === '说不准'" class="unsure">模型拿不准</span>
          <span class="id">{{ c.id }}</span>
        </div>
        <div class="pair">
          <div><SceneRefs :text="c.scenes[0]" :book="name" /> <span class="pos">故事顺序第 {{ c.pos[0] + 1 }} 位</span>
            <q>{{ c.quotes[0] }}</q></div>
          <div><SceneRefs :text="c.scenes[1]" :book="name" /> <span class="pos">故事顺序第 {{ c.pos[1] + 1 }} 位</span>
            <q>{{ c.quotes[1] }}</q></div>
        </div>
        <p class="reason"><SceneRefs :text="c.reason" :book="name" /></p>
        <div class="ops">
          <button v-for="k in 裁决顺序" :key="k" :data-test="`裁决-${c.id}-${k}`" :class="{ on: c.verdict?.kind === k }"
                  :disabled="jobStore.busy" @click="裁决(c, k)">{{ 裁决名[k] }}</button>
          <button v-if="c.verdict" :data-test="`撤销-${c.id}`" :disabled="jobStore.busy" @click="裁决(c, null)">撤销</button>
          <RouterLink v-if="c.verdict?.kind === 'order_error'" data-test="去归线页" :to="`/b/${encodeURIComponent(name)}/pipeline/threads`">去归线页调顺序</RouterLink>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.bar{margin-bottom:10px}
.empty{color:var(--ink-3)}
.warn{color:var(--amber);font-size:13px}
.stats{font-size:13px;color:var(--ink-2)}
.filters{display:flex;gap:6px;margin:8px 0}
.filters .on{background:var(--accent-soft);color:var(--accent)}
.card{border:1px solid var(--line-2);border-radius:8px;padding:10px 12px;margin-bottom:10px;background:var(--panel)}
.head{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.kind{font-size:11px;padding:1px 6px;border-radius:999px;background:var(--red-soft);color:var(--red)}
.kind.C{background:var(--amber-soft);color:var(--amber)}
.unsure{font-size:11px;color:var(--ink-3)}
.id{margin-left:auto;font-family:var(--mono);font-size:12px;color:var(--ink-3)}
.pair{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:8px 0;font-size:13px}
.pair q{display:block;color:var(--ink-2);margin-top:4px}
.pos{color:var(--ink-3);font-size:12px}
.reason{font-size:13px;color:var(--ink-2);margin:4px 0}
.ops{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.ops .on{background:var(--accent-soft);color:var(--accent)}
@media (max-width: 900px){.pair{grid-template-columns:1fr}}
</style>
