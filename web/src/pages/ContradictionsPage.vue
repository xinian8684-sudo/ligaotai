<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { getContradictions } from '@/api/endpoints'
import type { ContradictionGroup, ContradictionsFile } from '@/api/types'
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
 * 一期只展示不裁决（spec 第 5 章）。默认只展开「严重」，别的桶折叠
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
  const groups = data.value?.groups ?? []
  const map = new Map<桶Key, ContradictionGroup[]>()
  for (const g of groups) {
    const k = 桶归属(g)
    if (!map.has(k)) map.set(k, [])
    map.get(k)!.push(g)
  }
  return 桶顺序.filter((k) => map.has(k)).map((k) => ({ key: k, groups: map.get(k)! }))
})

const 跳过数 = computed(() => data.value?.skipped?.length ?? 0)

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
            <span v-if="g.verdict_stale" class="tag stale" data-test="verdict过期">这条判断是在旧数据上做的</span>
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
</style>
