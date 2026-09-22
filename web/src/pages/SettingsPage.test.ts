import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import SettingsPage from './SettingsPage.vue'
import * as api from '@/api/endpoints'

const routerLinkStub = { template: '<a><slot /></a>', props: ['to'] }
const stubs = { RouterLink: routerLinkStub }

const 配置 = {
  library_dir: '', api_base: 'https://api.deepseek.com', api_key: 'sk-…3f2a',
  concurrency: 8, timeout: 120, price_input: 0.3, price_output: 1.2,
  batch: { model: 'deepseek-flash', max_tokens: 8192 },
  synth: { model: 'deepseek-flash', max_tokens: 32768 },
  has_key: true, key_from_env: false, library_path: 'D:\\ligaotai\\书库',
}

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.restoreAllMocks())

describe('SettingsPage', () => {
  it('不显示单价字段', async () => {
    vi.spyOn(api, 'getConfig').mockResolvedValue(配置 as never)
    const w = mount(SettingsPage, { global: { stubs } })
    await flushPromises()
    expect(w.text()).not.toContain('单价')
    expect(w.text()).not.toContain('0.3')
    expect(w.text()).not.toContain('1.2')
    expect(w.find('[data-test="price_input"]').exists()).toBe(false)
  })

  it('提交时把单价原样带回去，不能丢', async () => {
    // PUT /api/config 是整份替换，漏字段会把后端的单价冲成默认值，
    // 而 tools/eval_* 还在用它。
    vi.spyOn(api, 'getConfig').mockResolvedValue(配置 as never)
    const put = vi.spyOn(api, 'putConfig').mockResolvedValue(配置 as never)
    const w = mount(SettingsPage, { global: { stubs } })
    await flushPromises()
    await w.find('[data-test="保存"]').trigger('click')
    await flushPromises()
    expect(put.mock.calls[0][0]).toMatchObject({ price_input: 0.3, price_output: 1.2 })
  })

  it('key 打过码，不回填明文，留空表示不改', async () => {
    vi.spyOn(api, 'getConfig').mockResolvedValue(配置 as never)
    const w = mount(SettingsPage, { global: { stubs } })
    await flushPromises()
    expect(w.text()).toContain('sk-…3f2a')
  })

  it('key 来自环境变量时说清楚', async () => {
    vi.spyOn(api, 'getConfig').mockResolvedValue({ ...配置, key_from_env: true } as never)
    const w = mount(SettingsPage, { global: { stubs } })
    await flushPromises()
    expect(w.text()).toContain('环境变量')
  })

  it('测试连接把后端返回的结果显示出来', async () => {
    vi.spyOn(api, 'getConfig').mockResolvedValue(配置 as never)
    vi.spyOn(api, 'testConfig').mockResolvedValue([{ tier: 'batch', ok: true }] as never)
    const w = mount(SettingsPage, { global: { stubs } })
    await flushPromises()
    await w.find('[data-test="测试连接"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-test="连接结果"]').exists()).toBe(true)
  })

  it('保存不会把 has_key / key_from_env / library_path 这三个展示字段发回去', async () => {
    vi.spyOn(api, 'getConfig').mockResolvedValue(配置 as never)
    const put = vi.spyOn(api, 'putConfig').mockResolvedValue(配置 as never)
    const w = mount(SettingsPage, { global: { stubs } })
    await flushPromises()
    await w.find('[data-test="保存"]').trigger('click')
    await flushPromises()
    const body = put.mock.calls[0][0] as Record<string, unknown>
    expect(body.has_key).toBeUndefined()
    expect(body.key_from_env).toBeUndefined()
    expect(body.library_path).toBeUndefined()
  })

  it('改了并发数和批量档模型再保存，改动要带上', async () => {
    vi.spyOn(api, 'getConfig').mockResolvedValue(配置 as never)
    const put = vi.spyOn(api, 'putConfig').mockResolvedValue(配置 as never)
    const w = mount(SettingsPage, { global: { stubs } })
    await flushPromises()
    const inputs = w.findAll('input')
    const 并发输入 = inputs.find((i) => i.attributes('min') === '1' && i.attributes('max') === '64')
    await 并发输入!.setValue(16)
    await w.find('[data-test="保存"]').trigger('click')
    await flushPromises()
    expect(put.mock.calls[0][0]).toMatchObject({ concurrency: 16 })
  })
})
