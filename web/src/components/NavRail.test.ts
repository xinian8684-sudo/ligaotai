import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import NavRail from './NavRail.vue'

const 基本 = { bookName: 'test', bookTitle: '归墟', pendingEntities: 0, pendingThreads: 0, contradictions: 0 }

// vue-test-utils 的 `true` 自动桩不会渲染默认插槽内容（实测：整个 <nav> 里的文字全部消失）。
// 用会渲染插槽的桩替代，这样才能测到 NavRail 真正塞进 RouterLink 里的文字。
const routerLinkStub = { template: '<a><slot /></a>', props: ['to'] }

describe('NavRail', () => {
  it('四个常驻项总是在', () => {
    const w = mount(NavRail, { props: 基本, global: { stubs: { RouterLink: routerLinkStub } } })
    const t = w.text()
    for (const 项 of ['理稿流水线', '全景', '场景浏览', '设定库', '矛盾']) {
      expect(t).toContain(项)
    }
  })

  it('没有待确认项时实体确认收起；归线确认常驻（改名/设主线平时要用）但不带角标', () => {
    const w = mount(NavRail, { props: 基本, global: { stubs: { RouterLink: routerLinkStub } } })
    expect(w.text()).not.toContain('实体确认')
    expect(w.text()).toContain('归线确认')
    expect(w.find('[data-test="归线角标"]').exists()).toBe(false)
  })

  it('有待确认项时子路由出现并带数字', () => {
    const w = mount(NavRail, {
      props: { ...基本, pendingEntities: 4, pendingThreads: 2 },
      global: { stubs: { RouterLink: routerLinkStub } },
    })
    expect(w.text()).toContain('实体确认')
    expect(w.text()).toContain('4')
    expect(w.text()).toContain('归线确认')
    expect(w.text()).toContain('2')
  })

  it('矛盾数为 0 时不显示角标', () => {
    const w = mount(NavRail, { props: 基本, global: { stubs: { RouterLink: routerLinkStub } } })
    expect(w.find('[data-test="矛盾角标"]').exists()).toBe(false)
  })

  it('二期页面不出现在导航里', () => {
    const w = mount(NavRail, { props: 基本, global: { stubs: { RouterLink: routerLinkStub } } })
    expect(w.text()).not.toContain('取舍')
    expect(w.text()).not.toContain('骨架')
    expect(w.text()).not.toContain('补写')
  })
})
