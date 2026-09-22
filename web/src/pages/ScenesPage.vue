<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { listScenes, getScene, listCards, getCard, getVersions, setMainVersion } from '@/api/endpoints'
import type { SceneMeta, SceneDetail, CardRow, CardRecord, VersionGroup } from '@/api/types'
import { ApiError } from '@/api/client'
import { useJobStore } from '@/stores/job'
import ErrorBox from '@/components/ErrorBox.vue'

const props = defineProps<{ name: string }>()

const jobStore = useJobStore()

const scenes = ref<SceneMeta[]>([])
const cards = ref<CardRow[]>([])
const versions = ref<VersionGroup[]>([])
const error = ref('')

const 搜索词 = ref('')
/** 「同时搜原文」是可选项：默认只搜标题/编号/卡片摘要（都是已经拉到的轻量数据），
 * 原文没有列表级接口（GET /scenes 不带正文，逐条拉 268/133 个场景的正文本身没问题，
 * 但不该在每次打开这页时就默默做一遍）——勾了这个才去按需把还没拉过的原文都拉一遍，
 * 拉过一次之后缓存住，后面搜索不用再拉。 */
const 搜原文 = ref(false)
const 原文缓存 = ref<Record<string, string>>({})
const 搜原文加载中 = ref(false)

const 选中id = ref<string | null>(null)
const 选中原文 = ref<SceneDetail | null>(null)
const 选中卡片 = ref<CardRecord | null>(null)
const 卡片状态 = ref<'ok' | 'none' | ''>('')
const 详情错误 = ref('')

const 卡片摘要表 = computed<Record<string, CardRow>>(() => {
  const out: Record<string, CardRow> = {}
  for (const c of cards.value) out[c.id] = c
  return out
})

async function 报错(e: unknown): Promise<void> {
  error.value = e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e)
}

async function 加载(): Promise<void> {
  error.value = ''
  try {
    scenes.value = await listScenes(props.name)
  } catch (e) {
    await 报错(e)
    return
  }
  try {
    cards.value = await listCards(props.name)
  } catch (e) {
    await 报错(e)
  }
  try {
    const v = await getVersions(props.name)
    versions.value = v.groups
  } catch (e) {
    await 报错(e)
  }
}

/** 勾了「搜原文」时，把还没拉过正文的场景补齐（已拉过的不重拉）。 */
async function 补齐原文缓存(): Promise<void> {
  const 缺 = scenes.value.filter((s) => !(s.id in 原文缓存.value))
  if (缺.length === 0) return
  搜原文加载中.value = true
  try {
    const 结果 = await Promise.all(
      缺.map(async (s) => {
        try {
          const d = await getScene(props.name, s.id)
          return [s.id, d.text] as const
        } catch {
          return [s.id, ''] as const
        }
      }),
    )
    const next = { ...原文缓存.value }
    for (const [id, text] of 结果) next[id] = text
    原文缓存.value = next
  } finally {
    搜原文加载中.value = false
  }
}

async function 切换搜原文(): Promise<void> {
  搜原文.value = !搜原文.value
  if (搜原文.value) await 补齐原文缓存()
}

const 过滤后场景 = computed<SceneMeta[]>(() => {
  const kw = 搜索词.value.trim()
  const 有效场景 = scenes.value.filter((s) => !s.removed)
  if (!kw) return 有效场景
  return 有效场景.filter((s) => {
    if (s.id.includes(kw) || s.heading.includes(kw)) return true
    const card = 卡片摘要表.value[s.id]
    if (card && card.summary.includes(kw)) return true
    if (搜原文.value && (原文缓存.value[s.id] ?? '').includes(kw)) return true
    return false
  })
})

/** 场景 id → 它所在的版本组（不在任何组里就是 undefined）。 */
const 场景所在组 = computed<Record<string, VersionGroup>>(() => {
  const out: Record<string, VersionGroup> = {}
  for (const g of versions.value) for (const m of g.members) out[m] = g
  return out
})

async function 选中(sid: string): Promise<void> {
  选中id.value = sid
  详情错误.value = ''
  选中原文.value = null
  选中卡片.value = null
  卡片状态.value = ''
  try {
    选中原文.value = await getScene(props.name, sid)
  } catch (e) {
    详情错误.value = e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e)
    return
  }
  try {
    选中卡片.value = await getCard(props.name, sid)
    卡片状态.value = 'ok'
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      卡片状态.value = 'none'
    } else {
      详情错误.value = e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e)
    }
  }
}

async function 设主版本(gid: string, sid: string): Promise<void> {
  error.value = ''
  try {
    await setMainVersion(props.name, gid, sid)
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
    <h1>场景浏览 —— 《{{ name }}》</h1>
    <ErrorBox :message="error" />

    <section v-if="versions.length > 0" class="block" data-test="版本组区">
      <details>
        <summary>版本组（{{ versions.length }}）——查重找到的相似场景，选一个当主版本</summary>
        <div v-for="g in versions" :key="g.id" class="vgroup" :data-test="`版本组-${g.id}`">
          <b class="gid">{{ g.id }}</b>
          <div class="members">
            <div v-for="m in g.members" :key="m" class="member" :class="{ main: m === g.main }">
              <span class="mid">{{ m }}</span>
              <span v-if="m === g.main" class="main-tag">主版本（{{ g.main_by === 'author' ? '作者定的' : '自动选的' }}）</span>
              <button
                v-else
                :data-test="`设为主版本-${g.id}-${m}`"
                :disabled="jobStore.busy"
                @click="设主版本(g.id, m)"
              >
                设为主版本
              </button>
            </div>
          </div>
        </div>
      </details>
    </section>

    <div class="layout">
      <aside class="list-pane">
        <div class="search-row">
          <input v-model="搜索词" data-test="搜索" placeholder="搜编号 / 标题 / 卡片摘要" />
          <label class="toggle">
            <input type="checkbox" :checked="搜原文" data-test="搜原文开关" @change="切换搜原文" />
            也搜原文{{ 搜原文加载中 ? '（加载中…）' : '' }}
          </label>
        </div>
        <p class="count">共 {{ 过滤后场景.length }} / {{ scenes.filter((s) => !s.removed).length }} 个场景</p>
        <ul class="scenes" data-test="场景列表">
          <li
            v-for="s in 过滤后场景"
            :key="s.id"
            class="scene-row"
            :class="{ active: s.id === 选中id }"
            :data-test="`场景-${s.id}`"
            @click="选中(s.id)"
          >
            <span class="sid">{{ s.id }}</span>
            <span v-if="s.heading" class="heading">{{ s.heading }}</span>
            <span v-if="s.stale" class="tag stale" title="原文变了，场景卡该重做了">待重做</span>
            <span v-if="场景所在组[s.id]" class="tag ver" :title="`版本组 ${场景所在组[s.id].id}`">多版本</span>
            <span class="summary">{{ 卡片摘要表[s.id]?.summary ?? '' }}</span>
          </li>
        </ul>
      </aside>

      <section v-if="选中id" class="detail-pane">
        <ErrorBox :message="详情错误" />
        <div class="two-col">
          <div class="col" data-test="原文栏">
            <h2>原文 —— {{ 选中id }}</h2>
            <pre v-if="选中原文" class="text">{{ 选中原文.text }}</pre>
          </div>
          <div class="col" data-test="卡片栏">
            <h2>场景卡</h2>
            <p v-if="卡片状态 === 'none'" class="empty">这个场景还没有场景卡。</p>
            <div v-else-if="选中卡片" class="card">
              <p class="csummary">{{ 选中卡片.card.summary }}</p>
              <p v-if="选中卡片.card.characters.length > 0" class="row">
                <b>人物：</b>{{ 选中卡片.card.characters.map((c) => `${c.name}（${c.role}）`).join('、') }}
              </p>
              <p v-if="选中卡片.card.locations.length > 0" class="row">
                <b>地点：</b>{{ 选中卡片.card.locations.join('、') }}
              </p>
              <div v-if="选中卡片.card.facts.length > 0" class="row facts">
                <b>事实：</b>
                <ul>
                  <li v-for="(f, i) in 选中卡片.card.facts" :key="i">
                    {{ f.subject }}·{{ f.attribute }}：{{ f.value }}（{{ f.quote }}）
                  </li>
                </ul>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.page{padding:24px;max-width:1200px}
h1{font-family:var(--serif);font-size:20px;margin:16px 0}
h2{font-size:15px;margin:0 0 8px}
.block{margin-bottom:16px}
.vgroup{border:1px solid var(--line-2);border-radius:8px;padding:8px 10px;margin:8px 0;font-size:13px}
.gid{color:var(--ink-3);margin-right:8px}
.members{display:flex;flex-direction:column;gap:4px;margin-top:4px}
.member{display:flex;align-items:center;gap:8px}
.member.main .mid{font-weight:600}
.main-tag{color:var(--green);font-size:12px}
.layout{display:flex;gap:16px;align-items:flex-start}
.list-pane{width:340px;flex:none}
.search-row{display:flex;flex-direction:column;gap:6px;margin-bottom:8px}
.search-row input[type="text"],.search-row input:not([type]){width:100%;box-sizing:border-box}
.toggle{font-size:12px;color:var(--ink-3);display:flex;align-items:center;gap:4px}
.count{color:var(--ink-3);font-size:12px;margin:4px 0}
.scenes{list-style:none;padding:0;margin:0;max-height:70vh;overflow:auto;border:1px solid var(--line-2);border-radius:8px}
.scene-row{
  display:flex;align-items:center;gap:8px;padding:6px 8px;border-bottom:1px solid var(--line-2);
  font-size:13px;cursor:pointer;
}
.scene-row:hover{background:var(--sunk)}
.scene-row.active{background:var(--accent-soft)}
.sid{color:var(--ink-3);flex:none}
.heading{flex:none;max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.summary{flex:1;color:var(--ink-2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.tag{flex:none;font-size:11px;padding:1px 5px;border-radius:999px}
.tag.stale{background:var(--amber-soft);color:var(--amber)}
.tag.ver{background:var(--accent-soft);color:var(--accent)}
.detail-pane{flex:1;min-width:0}
.two-col{display:flex;gap:16px}
.col{flex:1;min-width:0}
.text{white-space:pre-wrap;font-family:var(--serif);font-size:14px;line-height:1.8;max-height:70vh;overflow:auto}
.card{font-size:13px}
.csummary{color:var(--ink);margin:0 0 8px}
.row{margin:6px 0;color:var(--ink-2)}
.facts ul{margin:4px 0 0;padding-left:18px}
.empty{color:var(--ink-3)}
</style>
