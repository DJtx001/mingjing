// 组件冒烟测试：真实挂载，捕获 setup/render 运行时错误
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import AiAssistantDrawer from '../src/components/AiAssistantDrawer.vue'
import CaseListView from '../src/views/CaseListView.vue'
import NewCaseView from '../src/views/NewCaseView.vue'
import StatsView from '../src/views/StatsView.vue'

describe('组件冒烟', () => {
  it('AiAssistantDrawer 挂载与首屏渲染不抛错', () => {
    const wrapper = mount(AiAssistantDrawer, { props: { caseId: null } })
    expect(wrapper.exists()).toBe(true)
  })

  it('CaseListView 挂载不抛错', () => {
    const wrapper = mount(CaseListView)
    expect(wrapper.exists()).toBe(true)
  })

  it('NewCaseView 挂载不抛错', () => {
    const wrapper = mount(NewCaseView)
    expect(wrapper.exists()).toBe(true)
  })

  it('StatsView 挂载不抛错（未登录时走权限提示分支）', () => {
    const wrapper = mount(StatsView)
    expect(wrapper.exists()).toBe(true)
  })
})
