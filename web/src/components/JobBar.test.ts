import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import JobBar from './JobBar.vue'
import { useJobStore } from '@/stores/job'
import type { Job } from '@/api/types'

function 造任务(status: Job['status']): Job {
  return {
    id: 'j1', name: 'dedup', book: 'guixu', status, done: 130, total: 130, message: '',
    error: '', result: null, started: '', finished: '', cancel_requested: false,
  }
}

beforeEach(() => setActivePinia(createPinia()))

describe('JobBar', () => {
  it('任务在跑时显示进度', () => {
    useJobStore().current = 造任务('running')
    const w = mount(JobBar)
    expect(w.text()).toContain('130/130')
  })

  it('任务结束后不再挂着（后端 current 会一直返回上一个任务，可能是别的书的）', () => {
    for (const s of ['done', 'failed', 'cancelled'] as const) {
      useJobStore().current = 造任务(s)
      const w = mount(JobBar)
      expect(w.find('.bar').exists()).toBe(false)
    }
  })
})
