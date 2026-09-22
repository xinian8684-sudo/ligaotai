<script setup lang="ts">
import { computed } from 'vue'
import { useJobStore } from '@/stores/job'
import { cancelJob } from '@/api/endpoints'
import { STEP_LABELS, type StepName } from '@/api/types'

const jobStore = useJobStore()

const 步骤名 = computed(() => {
  const job = jobStore.current
  if (!job) return ''
  return STEP_LABELS[job.name as StepName] ?? job.name
})

const 百分比 = computed(() => {
  const job = jobStore.current
  if (!job || !job.total) return 0
  return Math.min(100, Math.round((job.done / job.total) * 100))
})

async function 暂停(): Promise<void> {
  const job = jobStore.current
  if (!job) return
  await cancelJob(job.id)
  await jobStore.refresh()
}
</script>

<template>
  <div v-if="jobStore.pollError" class="bar err">
    连不上后端：{{ jobStore.pollError }}
  </div>
  <!-- 只在任务没结束时显示：后端 /jobs/current 会一直返回上一个任务（可能是别的书的），
       结束了还挂着就是一条永远 100% 又不说完没完的条。结果看流水线那一行。 -->
  <div v-else-if="jobStore.current && jobStore.busy" class="bar">
    <span class="name">{{ 步骤名 }}</span>
    <div class="track"><div class="fill" :style="{ width: 百分比 + '%' }" /></div>
    <span class="n">{{ jobStore.current.done }}/{{ jobStore.current.total }}</span>
    <span v-if="jobStore.current.message" class="msg">{{ jobStore.current.message }}</span>
    <button
      v-if="jobStore.busy"
      data-test="暂停任务"
      :disabled="jobStore.current.cancel_requested"
      @click="暂停"
    >
      {{ jobStore.current.cancel_requested ? '暂停中…' : '暂停' }}
    </button>
  </div>
</template>

<style scoped>
.bar{
  display:flex;align-items:center;gap:10px;padding:8px 14px;
  background:var(--panel);border-bottom:1px solid var(--line-2);font-size:13px;
}
.bar.err{color:var(--red);background:var(--red-soft)}
.name{font-weight:500}
.track{flex:1;max-width:200px;height:6px;border-radius:3px;background:var(--sunk);overflow:hidden}
.fill{height:100%;background:var(--accent);transition:width .2s}
.n{color:var(--ink-3);font-variant-numeric:tabular-nums}
.msg{color:var(--ink-2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
button{margin-left:auto}
</style>
