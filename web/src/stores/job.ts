import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { currentJob } from '@/api/endpoints'
import type { Job } from '@/api/types'

const 轮询间隔 = 1000
const 未结束 = new Set<Job['status']>(['queued', 'running'])

export const useJobStore = defineStore('job', () => {
  const current = ref<Job | null>(null)
  const pollError = ref('')
  let timer: ReturnType<typeof setInterval> | null = null
  const 回调组: Array<(job: Job) => void> = []
  /** 已经播报过「结束了」的任务 id，防止重复触发。 */
  const 已播报 = new Set<string>()

  const busy = computed(() => !!current.value && 未结束.has(current.value.status))

  async function refresh(): Promise<void> {
    try {
      const job = await currentJob()
      pollError.value = ''
      const 前一个 = current.value
      current.value = job
      if (job && !未结束.has(job.status) && !已播报.has(job.id)) {
        // 只在「本来在跑、现在不跑了」时播报；一进来就看到已完成的任务不播报
        if (前一个 && 前一个.id === job.id && 未结束.has(前一个.status)) {
          已播报.add(job.id)
          for (const fn of 回调组) fn(job)
        }
      }
    } catch (e) {
      // 连不上后端时保持上次的 busy 状态（不知道到底忙不忙，保守），把错误露出来
      pollError.value = e instanceof Error ? e.message : String(e)
    }
  }

  function onFinish(fn: (job: Job) => void): void {
    回调组.push(fn)
  }

  function start(): void {
    if (timer !== null) return
    void refresh()
    timer = setInterval(() => { void refresh() }, 轮询间隔)
  }

  function stop(): void {
    if (timer === null) return
    clearInterval(timer)
    timer = null
  }

  return { current, pollError, busy, refresh, onFinish, start, stop }
})
