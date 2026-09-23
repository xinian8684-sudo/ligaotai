<script setup lang="ts">
import { ref, computed, watch, provide, onMounted, onUnmounted } from 'vue'
import { getBook, getContradictions } from '@/api/endpoints'
import type { BookMeta, StepName } from '@/api/types'
import { ApiError } from '@/api/client'
import { useJobStore } from '@/stores/job'
import AppShell from '@/components/AppShell.vue'
import ErrorBox from '@/components/ErrorBox.vue'

/**
 * 书内所有页面的外壳：左侧导航 + 子路由。
 * 计划③ 建了 AppShell 却没有任何一步把它挂上去，这层就是补这个洞的。
 * 导航角标要跟着书的状态走，所以书在这里拉一次，任务结束再拉；
 * 子页面确认完实体/归线后可以 inject('刷新书') 让角标立刻更新。
 */
const props = defineProps<{ name: string }>()

const jobStore = useJobStore()
const book = ref<BookMeta | null>(null)
const error = ref('')

async function 加载(): Promise<void> {
  error.value = ''
  try {
    book.value = await getBook(props.name)
  } catch (e) {
    error.value = e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e)
  }
  await 数矛盾()
}

provide('刷新书', 加载)

function 数(step: StepName, key: string): number {
  const v = book.value?.steps[step]?.summary?.[key]
  const n = Array.isArray(v) ? v.length : Number(v ?? 0)
  return Number.isFinite(n) ? n : 0
}

// 口径跟 PipelinePage 的「去确认」一致
const 待确认实体 = computed(() => 数('entities', 'draft_groups'))
const 待归线 = computed(() => 数('threads', 'pending'))

/**
 * 计划④起矛盾角标改口径：不再是矛盾组总数（steps.archive.summary.contradictions），
 * 是「未裁决的严重矛盾数」——裁决了或者不是严重的都不算（spec 第 10 节）。
 * 现算，不进 数()：数据来自 矛盾.json 本身，不是步骤 summary。
 */
const 未裁决严重 = ref(0)

async function 数矛盾(): Promise<void> {
  try {
    const f = await getContradictions(props.name)
    未裁决严重.value = f.groups.filter((g) => g.status === '真矛盾' && g.level === '严重' && g.verdict === null).length
  } catch {
    未裁决严重.value = 0 // 还没跑步骤 7：角标不显示，不当错误
  }
}

const 退订 = jobStore.onFinish(() => { void 加载() })
watch(() => props.name, () => { void 加载() })

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
  <AppShell
    :book-name="name"
    :book-title="book?.title ?? name"
    :pending-entities="待确认实体"
    :pending-threads="待归线"
    :contradictions="未裁决严重"
  >
    <ErrorBox :message="error" />
    <RouterView />
  </AppShell>
</template>
