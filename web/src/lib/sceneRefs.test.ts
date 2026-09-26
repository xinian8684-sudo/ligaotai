import { describe, it, expect } from 'vitest'
import { mount, RouterLinkStub } from '@vue/test-utils'
import { splitRefs } from './sceneRefs'
import SceneRefs from '@/components/SceneRefs.vue'

describe('splitRefs', () => {
  it('编号和文字交替切开，方括号留在文字里', () => {
    expect(splitRefs('他救了人 [S-0001][S-0030]。')).toEqual([
      { text: '他救了人 [' }, { id: 'S-0001' }, { text: '][' }, { id: 'S-0030' }, { text: ']。' },
    ])
  })
  it('没有编号 / 空串 / 开头结尾就是编号', () => {
    expect(splitRefs('没有编号')).toEqual([{ text: '没有编号' }])
    expect(splitRefs('')).toEqual([])
    expect(splitRefs('S-0001')).toEqual([{ id: 'S-0001' }])
  })
  it('只认四位以上数字（S-12 不算，S-12345 算）', () => {
    expect(splitRefs('S-12 和 S-12345')).toEqual([{ text: 'S-12 和 ' }, { id: 'S-12345' }])
  })
})

describe('SceneRefs', () => {
  it('编号渲染成去场景浏览的链接，带 ?s=编号', () => {
    const w = mount(SceneRefs, { props: { text: '见 [S-0030]', book: 'guixu' }, global: { stubs: { RouterLink: RouterLinkStub } } })
    const link = w.findComponent(RouterLinkStub)
    expect(link.props('to')).toEqual({ name: 'scenes', params: { name: 'guixu' }, query: { s: 'S-0030' } })
    expect(w.text()).toBe('见 [S-0030]')
  })
})
