<script setup lang="ts">
/**
 * 全景页。spec 第 4 章，全计划最难的一块。页面自己不算任何坐标——LaneChart 已经把
 * 断轴/段/缺口两层聚合全包了，这里只管拉数据、量容器宽度、维护右侧详情面板的选中状态。
 * 不显示任何费用数字（spec 7.3）。
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { getThreads, getVersions } from '@/api/endpoints'
import type { Gap, Thread, ThreadsFile, VersionsFile } from '@/api/types'
import { ApiError } from '@/api/client'
import LaneChart from '@/components/LaneChart.vue'
import ErrorBox from '@/components/ErrorBox.vue'

const props = defineProps<{ name: string }>()

const data = ref<ThreadsFile | null>(null)
const versions = ref<VersionsFile | null>(null)
const error = ref('')

async function 报错(e: unknown): Promise<void> {
  error.value = e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e)
}

async function 加载(): Promise<void> {
  error.value = ''
  try {
    const [t, v] = await Promise.all([getThreads(props.name), getVersions(props.name)])
    data.value = t
    versions.value = v
  } catch (e) {
    await 报错(e)
  }
}

// ---------- 右侧详情：选中一条线，或者选中一簇 / 一批 orphan 缺口 ----------
type Detail =
  | { kind: 'thread'; thread: Thread }
  | { kind: 'gaps'; threadId: string; gaps: Gap[] }
  | null

const detail = ref<Detail>(null)

function 选线(threadId: string): void {
  const t = data.value?.threads.find((x) => x.id === threadId)
  detail.value = t ? { kind: 'thread', thread: t } : null
}
function 选缺口(payload: { threadId: string; gaps: Gap[] }): void {
  detail.value = { kind: 'gaps', threadId: payload.threadId, gaps: payload.gaps }
}

function 世界名(wid: string): string {
  return data.value?.worlds.find((w) => w.id === wid)?.name ?? wid
}
function 线名(tid: string): string {
  return data.value?.threads.find((t) => t.id === tid)?.name ?? tid
}

function 该线缺口数(threadId: string): number {
  return data.value?.gaps.filter((g) => g.thread === threadId).length ?? 0
}

// ---------- 顶部统计：不含任何费用（spec 7.3） ----------
const stats = computed(() => {
  const d = data.value
  if (!d) return null
  return {
    scenes: d.threads.reduce((s, t) => s + t.scenes.length, 0),
    threads: d.threads.length,
    worlds: d.worlds.length,
    finished: d.threads.filter((t) => t.end?.state === '完结').length,
    pending: d.threads.filter((t) => t.end?.state === '待定').length,
    versionGroups: versions.value?.groups.length ?? 0,
    gaps: d.gaps.length,
  }
})

// ---------- 容器宽度：ResizeObserver 量实际像素，传给 LaneChart 算 clusterRatio ----------
const chartBox = ref<HTMLElement | null>(null)
const chartWidth = ref(1200)
let ro: ResizeObserver | null = null

onMounted(() => {
  void 加载()
})
// 图框在 v-if="data" 里，数据到了才出现——onMounted 时它还是 null，所以盯着 ref 挂观察器，
// 不然宽度永远卡在默认 1200，窄屏上缺口该并的都不并。
// jsdom 测试环境没有 ResizeObserver，量不了就用默认宽度，不是错误。
watch(chartBox, (el) => {
  ro?.disconnect()
  ro = null
  if (!el || typeof ResizeObserver === 'undefined') return
  ro = new ResizeObserver((entries) => {
    const w = entries[0]?.contentRect.width
    if (w && w > 0) chartWidth.value = w
  })
  ro.observe(el)
})
onUnmounted(() => {
  ro?.disconnect()
  ro = null
})
</script>

<template>
  <div class="page">
    <h1>全景 —— 《{{ name }}》</h1>
    <ErrorBox :message="error" />

    <div v-if="stats" class="strip">
      <div><span class="v">{{ stats.scenes }}</span><span class="k">场景</span></div>
      <div><span class="v">{{ stats.threads }}</span><span class="k">线</span></div>
      <div><span class="v">{{ stats.worlds }}</span><span class="k">世界</span></div>
      <div><span class="v">{{ stats.finished }} · {{ stats.pending }}</span><span class="k">完结 · 待定</span></div>
      <div><span class="v">{{ stats.versionGroups }}</span><span class="k">组多版本场景</span></div>
      <div><span class="v">{{ stats.gaps }}</span><span class="k">处缺口</span></div>
    </div>

    <div v-if="data" class="pano">
      <div ref="chartBox" class="chart">
        <LaneChart
          :data="data"
          :versions="versions?.groups ?? []"
          :width="chartWidth"
          :selected-thread="detail?.kind === 'thread' ? detail.thread.id : null"
          @select-thread="选线"
          @select-cluster="选缺口"
          @select-orphans="选缺口"
        />
      </div>

      <aside class="detail" data-test="详情">
        <template v-if="detail?.kind === 'thread'">
          <p class="w">{{ 世界名(detail.thread.world) }}</p>
          <h3>{{ detail.thread.name }}</h3>
          <dl class="kv">
            <dt>状态</dt><dd>{{ detail.thread.end?.state ?? '待定' }}</dd>
            <dt>场景</dt><dd>{{ detail.thread.scenes.length }} 块</dd>
            <dt>缺口</dt><dd>{{ 该线缺口数(detail.thread.id) }} 处</dd>
          </dl>
          <p class="about">{{ detail.thread.about }}</p>
          <div v-if="detail.thread.end?.note" class="note"><b>写到哪</b>{{ detail.thread.end.note }}</div>
          <p v-if="detail.thread.order_failed" class="fail">这条线排序失败，顺序不可信。</p>
        </template>

        <template v-else-if="detail?.kind === 'gaps'">
          <h3>{{ 线名(detail.threadId) }} 的缺口（{{ detail.gaps.length }}）</h3>
          <ul class="gap-list">
            <li v-for="g in detail.gaps" :key="g.id">
              <p class="event">{{ g.event }}</p>
              <p class="mentioned">提到：{{ g.mentioned_in.join('、') || '（没有记录出处）' }}</p>
            </li>
          </ul>
        </template>

        <p v-else class="empty">点一条线，或点一个缺口簇看详情。</p>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.page{padding:24px;max-width:1200px}
h1{font-family:var(--serif);font-size:20px;margin:16px 0}
.strip{display:flex;flex-wrap:wrap;gap:6px 22px;padding:12px 16px;background:var(--panel);border:1px solid var(--line);border-radius:8px;margin-bottom:16px}
.strip .v{display:block;font-size:18px;font-family:var(--mono)}
.strip .k{display:block;font-size:11px;color:var(--ink-3)}
.pano{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:16px;align-items:start}
.chart{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px 16px;overflow-x:auto}
.detail{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:16px;font-size:13px}
.detail .w{font-size:12px;color:var(--ink-3)}
.detail h3{font-family:var(--serif);font-size:18px;margin:2px 0 10px}
.detail .empty{color:var(--ink-3)}
.kv{display:grid;grid-template-columns:auto 1fr;gap:4px 12px;font-size:13px;margin-bottom:12px}
.about{color:var(--ink-2);margin-bottom:10px}
.note{margin-bottom:10px}
.note b{display:block;color:var(--ink-3);font-size:11px;margin-bottom:2px}
.fail{color:var(--amber)} /* 朱红只给断口/缺口/严重矛盾（spec 7.2），排序失败用琥珀 */
.gap-list{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:10px}
.gap-list .event{margin:0}
.gap-list .mentioned{margin:2px 0 0;color:var(--ink-3);font-size:11px}
/* 窄窗口：详情面板挪到图下面，别把泳道挤成要横着滚 */
@media (max-width: 1200px){.pano{grid-template-columns:minmax(0,1fr)}}
</style>
