import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import App from './App.vue'

describe('脚手架', () => {
  it('App 挂得起来', () => {
    const w = mount(App)
    expect(w.text()).toContain('理稿台')
  })
})
