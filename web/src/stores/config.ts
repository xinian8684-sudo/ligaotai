import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getConfig, putConfig, testConfig } from '@/api/endpoints'
import type { PublicConfig } from '@/api/types'
import { ApiError } from '@/api/client'

/**
 * PUT /api/config 是整份替换：后端 AppConfig 只认 library_dir/api_base/api_key/
 * concurrency/timeout/price_input/price_output/batch/synth 这几个字段，漏了任何一个
 * 都会被后端的默认值冲掉（尤其是界面不显示的 price_input/price_output）。
 * 这里的策略是：把 GET 拿到的整份对象原样存进 config，界面表单直接双向绑定这个对象
 * 的字段，提交时只是把它（去掉三个只读的展示字段）发回去——没被界面碰过的字段
 * 原样带着，不会丢。
 */
export const useConfigStore = defineStore('config', () => {
  const config = ref<PublicConfig | null>(null)
  const error = ref('')
  const saving = ref(false)
  const testing = ref(false)
  const testResult = ref<unknown[] | null>(null)

  function 报错(e: unknown): void {
    error.value = e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e)
  }

  async function load(): Promise<void> {
    error.value = ''
    try {
      config.value = await getConfig()
    } catch (e) {
      报错(e)
    }
  }

  async function save(): Promise<void> {
    if (!config.value) return
    error.value = ''
    saving.value = true
    try {
      // has_key / key_from_env / library_path 是后端算给界面看的，AppConfig 里没有这几个
      // 字段，PUT 时去掉，免得万一后端哪天改成 extra="forbid" 就炸掉。
      const { has_key: _h, key_from_env: _k, library_path: _l, ...body } = config.value
      config.value = await putConfig(body)
    } catch (e) {
      报错(e)
    } finally {
      saving.value = false
    }
  }

  async function test(): Promise<void> {
    error.value = ''
    testing.value = true
    try {
      testResult.value = await testConfig()
    } catch (e) {
      报错(e)
    } finally {
      testing.value = false
    }
  }

  return { config, error, saving, testing, testResult, load, save, test }
})
