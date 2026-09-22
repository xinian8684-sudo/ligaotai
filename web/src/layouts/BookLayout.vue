<script setup lang="ts">
import { ref, computed, watch, provide, onMounted, onUnmounted } from 'vue'
import { getBook } from '@/api/endpoints'
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
const 矛盾 = computed(() => 数('archive', 'contradictions'))

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
    :contradictions="矛盾"
  >
    <ErrorBox :message="error" />
    <RouterView />
  </AppShell>
</template>
