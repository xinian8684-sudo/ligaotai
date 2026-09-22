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

  /**
   * 每次 track() 加一。track 之前发出、之后才回来的那次轮询带的是旧任务，
   * 丢掉它，免得把刚塞进来的 queued 任务又盖回旧的、错过 queued→done 的跳变。
   */
  let 代 = 0

  async function refresh(): Promise<void> {
    const 发出时 = 代
    try {
      const job = await currentJob()
      if (发出时 !== 代) return
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

  /**
   * 页面 POST 拿到刚提交的任务（queued）后调它，塞进 current。
   * 不然两次轮询之间就跑完的快任务（小书上切场景/查重 <1 秒很常见）下一次轮询直接看到
   * done，跟上一次看到的旧任务 id 对不上，onFinish 一次都不触发、页面不刷新（审查 S3）。
   */
  function track(job: Job): void {
    代 += 1
    current.value = job
  }

  /** 返回退订函数；组件卸载时要调，否则每进一次页面就多挂一个回调。 */
  function onFinish(fn: (job: Job) => void): () => void {
    回调组.push(fn)
    return () => {
      const i = 回调组.indexOf(fn)
      if (i >= 0) 回调组.splice(i, 1)
    }
  }

  /** 引用计数：书内布局和页面可能同时 start，最后一个 stop 才真停。 */
  let 使用者 = 0

  function start(): void {
    使用者 += 1
    if (timer !== null) return
    void refresh()
    timer = setInterval(() => { void refresh() }, 轮询间隔)
  }

  function stop(): void {
    if (使用者 > 0) 使用者 -= 1
    if (使用者 > 0 || timer === null) return
    clearInterval(timer)
    timer = null
  }

  return { current, pollError, busy, refresh, track, onFinish, start, stop }
})
