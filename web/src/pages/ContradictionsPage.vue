<script setup lang="ts">
import { computed, inject, onMounted, onUnmounted, ref } from 'vue'
import { getContradictions, getFollowups, putVerdict } from '@/api/endpoints'
import type { ContradictionGroup, ContradictionsFile, Followups, VerdictReq } from '@/api/types'
import { ApiError } from '@/api/client'
import { useJobStore } from '@/stores/job'
import ErrorBox from '@/components/ErrorBox.vue'

const props = defineProps<{ name: string }>()

const jobStore = useJobStore()

const data = ref<ContradictionsFile | null>(null)
const error = ref('')

async function 加载(): Promise<void> {
  error.value = ''
  try {
    data.value = await getContradictions(props.name)
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e)
  }
}

/**
 * 默认只展开「严重」，别的桶折叠
 * （②c 设计决定：矛盾宁可多报，界面默认只亮严重的）。真矛盾里非严重的
 * （中等/轻微）不在 spec 点名的两个折叠桶里，但既然点名的只有「严重」
 * 展开，别的一律按折叠处理最安全——不会把中等/轻微悄悄跟严重混在一起
 * 展开出来。
 */
type 桶Key = '严重' | '中等' | '轻微' | '合理变化' | '无法判断'
const 桶顺序: 桶Key[] = ['严重', '中等', '轻微', '合理变化', '无法判断']

function 桶归属(g: ContradictionGroup): 桶Key {
  if (g.status === '真矛盾') {
    if (g.level === '严重') return '严重'
    if (g.level === '中等') return '中等'
    return '轻微'
  }
  return g.status
}

const 桶列表 = computed<Array<{ key: 桶Key; groups: ContradictionGroup[] }>>(() => {
  const groups = (data.value?.groups ?? []).filter(留下)
  const map = new Map<桶Key, ContradictionGroup[]>()
  for (const g of groups) {
    const k = 桶归属(g)
    if (!map.has(k)) map.set(k, [])
    map.get(k)!.push(g)
  }
  return 桶顺序.filter((k) => map.has(k)).map((k) => ({ key: k, groups: map.get(k)! }))
})

const 跳过数 = computed(() => data.value?.skipped?.length ?? 0)

type 筛选 = '全部' | '未裁决' | '需重看'
const 筛选项: 筛选[] = ['全部', '未裁决', '需重看']
const 当前筛选 = ref<筛选>('全部')

function 留下(g: ContradictionGroup): boolean {
  if (当前筛选.value === '未裁决') return g.verdict === null
  if (当前筛选.value === '需重看') return g.verdict_stale
  return true
}

const 自己写开着 = ref<Record<string, boolean>>({})
const 自己写草稿 = ref<Record<string, string>>({})
const 跟着改 = ref<Record<string, Followups | undefined>>({})

/** BookLayout provide 的重新拉书；裁决改变了未裁决严重矛盾数，角标要立刻跟着变。 */
const 刷新书 = inject<() => Promise<void>>('刷新书', async () => {})

async function 裁决(g: ContradictionGroup, body: VerdictReq): Promise<void> {
  error.value = ''
  try {
    await putVerdict(props.name, g.id, body)
    自己写开着.value[g.id] = false
    跟着改.value[g.id] = undefined
    await 加载()
    await 刷新书()
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e)
  }
}

async function 看跟着改(g: ContradictionGroup): Promise<void> {
  try {
    跟着改.value[g.id] = await getFollowups(props.name, g.id)
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e)
  }
}

function 结论(g: ContradictionGroup): string {
  const v = g.verdict
  if (!v) return ''
  if (v.kind === 'later') return '先放着'
  return `定为：${v.value}${v.kind === 'own' ? '（作者自己写的）' : ''}`
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
    <h1>矛盾 —— 《{{ name }}》</h1>
    <ErrorBox :message="error" />

    <p v-if="data && data.groups.length === 0" class="empty" data-test="空态">
      还没有矛盾扫描结果，跑一次步骤 7（档案+矛盾+地图）试试。
    </p>

    <template v-else-if="data">
      <p v-if="跳过数 > 0" class="skip-note">另有 {{ 跳过数 }} 组因超过规模上限没有送进模型判断，没有丢弃，只是还没判断。</p>

      <div class="filters">
        <button v-for="f in 筛选项" :key="f" :class="{ on: 当前筛选 === f }" :data-test="`筛选-${f}`" @click="当前筛选 = f">{{ f }}</button>
      </div>

      <details
        v-for="桶 in 桶列表"
        :key="桶.key"
        class="bucket"
        :open="桶.key === '严重'"
        :data-test="`桶-${桶.key}`"
      >
        <summary>
          <span class="bucket-label" :class="{ severe: 桶.key === '严重' }">{{ 桶.key }}</span>
          （{{ 桶.groups.length }} 组）
        </summary>

        <div v-for="g in 桶.groups" :key="g.id" class="group" data-test="矛盾组">
          <div class="ghead">
            <b class="subject">{{ g.subject }}</b>
            <span class="dot">·</span>
            <span class="attr">{{ g.attribute }}</span>
            <span class="tag category">{{ g.category }}</span>
            <span v-if="g.verdict_stale" class="tag stale" data-test="verdict过期">值变了，请重看</span>
          </div>
          <p class="reason">{{ g.reason || '（模型没给理由）' }}</p>
          <div v-for="(v, i) in g.values" :key="i" class="value">
            <div class="vhead">值「{{ v.value }}」出现在：</div>
            <ul class="scenes">
              <li v-for="s in v.scenes" :key="s.id">
                <span class="sid">[{{ s.id }}]</span>
                <span v-if="s.thread" class="thread">{{ s.thread }}</span>
                <span v-if="s.t !== null" class="t">故事时间约 {{ s.t }}{{ s.conf ? `（把握${s.conf}）` : '' }}</span>
                <span v-else class="t">故事时间未知</span>
                <span class="quote">{{ s.quote }}</span>
              </li>
            </ul>
          </div>

          <div class="verdict">
            <template v-if="g.verdict">
              <span class="conclusion" :data-test="`结论-${g.id}`">{{ 结论(g) }}</span>
              <button :data-test="`撤销-${g.id}`" :disabled="jobStore.busy" @click="裁决(g, { kind: null })">撤销</button>
              <button v-if="g.verdict.kind !== 'later'" class="link" :data-test="`跟着改-${g.id}`" @click="看跟着改(g)">另一边要跟着改的地方</button>
              <ul v-if="跟着改[g.id]" class="followups">
                <li v-for="s in 跟着改[g.id]!.scenes" :key="s.id + s.value"><span class="sid">[{{ s.id }}]</span> {{ s.quote }}（写的是「{{ s.value }}」）</li>
                <li v-if="跟着改[g.id]!.scenes.length === 0" class="none">没有要跟着改的地方</li>
              </ul>
            </template>
            <template v-if="!g.verdict || g.verdict_stale">
              <button v-for="(v, i) in g.values" :key="i" :data-test="`以此为准-${g.id}-${i}`" :disabled="jobStore.busy"
                      @click="裁决(g, { kind: 'pick', value: v.value })">以「{{ v.value }}」为准</button>
              <button :data-test="`自己写-${g.id}`" :disabled="jobStore.busy" @click="自己写开着[g.id] = true">都不对，我自己写</button>
              <button :data-test="`先放着-${g.id}`" :disabled="jobStore.busy" @click="裁决(g, { kind: 'later' })">先放着</button>
              <span v-if="自己写开着[g.id]" class="own">
                <input v-model="自己写草稿[g.id]" :data-test="`自己写输入-${g.id}`" placeholder="写下正确的说法" />
                <button :data-test="`自己写确定-${g.id}`" :disabled="jobStore.busy || !(自己写草稿[g.id] ?? '').trim()"
                        @click="裁决(g, { kind: 'own', value: (自己写草稿[g.id] ?? '').trim() })">确定</button>
              </span>
            </template>
          </div>
        </div>
      </details>
    </template>
  </div>
</template>

<style scoped>
.page{padding:24px;max-width:920px}
h1{font-family:var(--serif);font-size:20px;margin:16px 0}
.empty{color:var(--ink-3)}
.skip-note{color:var(--ink-3);font-size:13px;margin-bottom:12px}
.bucket{margin-bottom:14px;border:1px solid var(--line-2);border-radius:8px;padding:8px 12px}
.bucket summary{cursor:pointer;font-size:14px;color:var(--ink-2)}
.bucket-label{font-weight:600;color:var(--ink)}
.bucket-label.severe{color:var(--red)}
.group{border-top:1px solid var(--line-2);padding:10px 0;margin-top:8px}
.group:first-of-type{border-top:none;margin-top:4px}
.ghead{display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.subject{font-family:var(--serif);font-size:15px}
.dot{color:var(--ink-3)}
.attr{color:var(--ink-2)}
.tag{font-size:11px;padding:1px 6px;border-radius:999px;background:var(--sunk);color:var(--ink-3)}
.tag.stale{background:var(--amber-soft);color:var(--amber)}
.reason{color:var(--ink-2);font-size:13px;margin:6px 0}
.value{margin:6px 0;font-size:13px}
.vhead{color:var(--ink);margin-bottom:2px}
.scenes{list-style:none;margin:0;padding:0}
.scenes li{display:flex;flex-wrap:wrap;gap:8px;padding:3px 0;color:var(--ink-2)}
.sid{color:var(--ink-3);flex:none}
.thread{flex:none;color:var(--accent)}
.t{flex:none;color:var(--ink-3)}
.quote{color:var(--ink)}
.filters{display:flex;gap:6px;margin-bottom:12px}
.filters .on{border-color:var(--accent);color:var(--accent)}
.verdict{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin-top:8px}
.conclusion{font-weight:600;color:var(--green)}
.link{border:none;background:none;color:var(--accent);padding:0;text-decoration:underline}
.followups{width:100%;margin:4px 0 0;padding-left:16px;font-size:13px;color:var(--ink-2)}
.followups .none{color:var(--ink-3);list-style:none}
.own{display:inline-flex;gap:6px}
</style>
