// 组件冒烟测试：真实挂载，捕获 setup/render 运行时错误
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import AiAssistantDrawer from '../src/components/AiAssistantDrawer.vue'
import CaseListView from '../src/views/CaseListView.vue'
import NewCaseView from '../src/views/NewCaseView.vue'
import StatsView from '../src/views/StatsView.vue'
import DocumentPanel from '../src/components/DocumentPanel.vue'
import DocumentView from '../src/views/DocumentView.vue'
import ReviewView from '../src/views/ReviewView.vue'
import MediationPanel from '../src/components/MediationPanel.vue'
import LoginView from '../src/views/LoginView.vue'

// LoginView 的登录接口打桩：让一键登录按钮的调用链路可断言
vi.mock('../src/api/auth.js', () => ({ login: vi.fn() }))

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

  it('DocumentView 挂载不抛错（无后端时请求失败被捕获）', () => {
    const wrapper = mount(DocumentView)
    expect(wrapper.exists()).toBe(true)
  })

  it('DocumentPanel 挂载不抛错', () => {
    const wrapper = mount(DocumentPanel, { props: { caseId: 'AJ2026-10086' } })
    expect(wrapper.exists()).toBe(true)
  })

  it('ReviewView 挂载不抛错（未登录走权限提示分支）', () => {
    const wrapper = mount(ReviewView)
    expect(wrapper.exists()).toBe(true)
  })

  it('MediationPanel 挂载不抛错', () => {
    const wrapper = mount(MediationPanel, { props: { caseId: 'AJ2026-10086' } })
    expect(wrapper.exists()).toBe(true)
  })

  it('LoginView 一键登录：点击后以 lisi/123456 调登录接口并 emit 登录成功', async () => {
    const { login } = await import('../src/api/auth.js')
    login.mockResolvedValue({ user: { name: '李四' }, access_token: 'fake-token' })
    const wrapper = mount(LoginView)
    const quickBtn = wrapper.findAll('button').find(b => b.text().includes('一键登录'))
    expect(quickBtn).toBeTruthy()
    await quickBtn.trigger('click')
    expect(login).toHaveBeenCalledWith({ username: 'lisi', password: '123456' })
    expect(wrapper.emitted('login-success')).toBeTruthy()
    // 表单被自动回填，视觉上可见
    expect(wrapper.vm.form.username).toBe('lisi')
  })
})
