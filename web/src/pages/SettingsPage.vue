<script setup lang="ts">
import { onMounted } from 'vue'
import { useConfigStore } from '@/stores/config'
import ErrorBox from '@/components/ErrorBox.vue'

const store = useConfigStore()

onMounted(() => {
  void store.load()
})

function 项(r: unknown, key: string): string {
  const v = (r as Record<string, unknown>)[key]
  return v === undefined || v === null ? '' : String(v)
}

function 连上了(r: unknown): boolean {
  return (r as Record<string, unknown>).ok === true
}
</script>

<template>
  <div class="page">
    <!-- 设置页不在 BookLayout 里，没有导航栏；不给这条链接作者只能改地址栏回去（G2） -->
    <RouterLink to="/" class="back" data-test="回书架">← 书架</RouterLink>
    <h1>设置</h1>
    <ErrorBox :message="store.error" />

    <div v-if="store.config" class="form">
      <label>
        书库目录（留空用默认的 <code>{{ store.config.library_path }}</code>）
        <input v-model="store.config.library_dir" placeholder="留空 = 用默认书库目录" />
      </label>

      <label>
        接口地址
        <input v-model="store.config.api_base" />
      </label>

      <label>
        API key（当前：<span class="cur-key">{{ store.config.api_key || '（没配）' }}</span>）
        <input v-model="store.config.api_key" placeholder="留空表示不改" data-test="api_key" />
        <small v-if="store.config.key_from_env" class="hint">当前用的是环境变量里的 key。</small>
        <small v-else-if="!store.config.has_key" class="hint">还没配 key。</small>
      </label>

      <label class="half">
        并发数
        <input v-model.number="store.config.concurrency" type="number" min="1" max="64" />
      </label>
      <label class="half">
        单次调用超时（秒）
        <input v-model.number="store.config.timeout" type="number" min="1" />
      </label>

      <fieldset>
        <legend>批量档（抽场景卡）</legend>
        <label class="half">
          模型
          <input v-model="store.config.batch.model" />
        </label>
        <label class="half">
          max_tokens
          <input v-model.number="store.config.batch.max_tokens" type="number" min="256" />
        </label>
      </fieldset>

      <fieldset>
        <legend>综合档（需要通盘考虑的判断）</legend>
        <label class="half">
          模型
          <input v-model="store.config.synth.model" />
        </label>
        <label class="half">
          max_tokens
          <input v-model.number="store.config.synth.max_tokens" type="number" min="256" />
        </label>
      </fieldset>

      <div class="actions">
        <button type="button" data-test="保存" :disabled="store.saving" @click="store.save()">
          {{ store.saving ? '保存中…' : '保存' }}
        </button>
        <button type="button" data-test="测试连接" :disabled="store.testing" @click="store.test()">
          {{ store.testing ? '测试中…' : '测试连接' }}
        </button>
      </div>

      <ul v-if="store.testResult" class="test-result" data-test="连接结果">
        <li v-for="(r, i) in store.testResult" :key="i">
          <b>{{ 项(r, 'tier') === 'batch' ? '批量档' : 项(r, 'tier') === 'synth' ? '综合档' : 项(r, 'tier') }}</b>
          <span :class="连上了(r) ? 'ok' : 'bad'">
            {{ 连上了(r) ? '连得上' : '连不上' }}
          </span>
          <span v-if="项(r, 'model')" class="model">{{ 项(r, 'model') }}</span>
          <span v-if="项(r, 'seconds')" class="seconds">{{ 项(r, 'seconds') }}s</span>
          <span v-if="项(r, 'error')" class="err-text">{{ 项(r, 'error') }}</span>
        </li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.page{padding:24px;max-width:560px}
.back{font-size:13px;color:var(--ink-2);text-decoration:none}
.back:hover{text-decoration:underline}
h1{font-family:var(--serif);font-size:20px;margin:16px 0}
.form{display:flex;flex-wrap:wrap;gap:14px}
.form label{display:block;font-size:13px;color:var(--ink-2);flex:1 1 100%}
.form label.half{flex:1 1 45%}
.form input{width:100%;margin-top:4px}
.form code{color:var(--ink-3);font-family:var(--mono);font-size:12px}
.hint{display:block;color:var(--ink-3);margin-top:4px}
fieldset{border:1px solid var(--line-2);border-radius:8px;padding:10px 12px;flex:1 1 100%;display:flex;gap:14px;flex-wrap:wrap}
legend{padding:0 6px;color:var(--ink-2);font-size:13px}
.actions{display:flex;gap:8px;flex:1 1 100%}
.test-result{list-style:none;padding:0;margin:0;flex:1 1 100%;display:flex;flex-direction:column;gap:6px}
.test-result li{display:flex;align-items:center;gap:10px;font-size:13px;border-bottom:1px solid var(--line-2);padding:6px 0}
.ok{color:var(--green)}
.bad{color:var(--red)}
.model,.seconds{color:var(--ink-3)}
.err-text{color:var(--red)}
</style>
