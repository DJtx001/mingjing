<template>
  <!-- 未登录：只显示登录页；登录后进入工作台布局 -->
  <LoginView v-if="!user" @login-success="onLogin" />
  <div v-else class="layout">
    <!-- 顶栏 -->
    <header class="topbar">
      <div class="brand">
        <span class="brand-name">明镜</span>
        <span class="brand-sub">要素式智能受理系统</span>
      </div>
      <div class="user">
        <span class="user-avatar">{{ (user.name || '?')[0] }}</span>
        {{ user.name }} · {{ user.org }}
      </div>
      <div class="logout" @click="onLogout">退出</div>
    </header>
    <div class="body">
      <!-- 左侧菜单（原型图页⑦），用 currentView 切换主内容区 -->
      <aside class="sidebar">
        <!-- AI 助手入口①：侧边栏菜单（入口②为右下角悬浮球，由组件自带） -->
        <div class="menu-item" @click="openAi"><span class="menu-icon">🤖</span>明镜AI 助手</div>
        <div class="menu-item" :class="{ active: currentView === 'kb' }" @click="currentView = 'kb'"><span class="menu-icon">⚙️</span>知识库与规则</div>
        <!-- 操作日志菜单对所有人可见；非管理员进入后由页面提示权限不足（接口层 require_admin 兜底） -->

        <div class="menu-item" :class="{ active: currentView === 'cases' }" @click="currentView = 'cases'"><span class="menu-icon">📂</span>我的案件 <el-badge class="badge" :value="counts.all" type="primary"></el-badge></div>
        <div class="menu-item" :class="{ active: currentView === 'newcase' }" @click="currentView = 'newcase'"><span class="menu-icon">📝</span>新建受理</div>
        <div class="menu-item" :class="{ active: currentView === 'stats' }" @click="currentView = 'stats'"><span class="menu-icon">📊</span>统计看板</div>
        <div class="menu-item" :class="{ active: currentView === 'logs' }" @click="currentView = 'logs'"><span class="menu-icon">📜</span>操作日志</div>
        <div class="menu-item"><span class="menu-icon">⏳</span>待开发,可使用ai<el-badge class="badge" :value="counts.documents_ready" type="warning"></el-badge></div>
        <div class="menu-item"><span class="menu-icon">🧐</span>待开发,可使用ai<el-badge class="badge" :value="counts.pending_review" type="danger"></el-badge></div>

      </aside>
      <!-- 主内容区：按 currentView 切换页面 -->
      <main class="content">
        <!-- 页头：随当前模块切换标题与说明，撑起板块层次 -->
        <div class="page-head">
          <h2>{{ pageMeta.title }}</h2>
          <p class="page-desc">{{ pageMeta.desc }}</p>
        </div>
        <CaseListView v-if="currentView === 'cases'" :open-case-id="pendingOpenCase"
                      @counts="onCounts" @open-case="onOpenCase" @open-case-ai="onOpenCaseAi" />
        <NewCaseView v-else-if="currentView === 'newcase'" @created="onCaseCreated" />
        <KnowledgeBaseView v-else-if="currentView === 'kb'" />
        <OperationLogView v-else-if="currentView === 'logs'" />
        <StatsView v-else-if="currentView === 'stats'" />
      </main>
    </div>
    <!-- 页⑥ AI 助手为全局组件（悬浮球可拖动入口保留）；案件上下文随「AI 办案」/
         详情打开注入，引用卡片「采纳到本案」据此激活并落该案备注 -->
    <AiAssistantDrawer ref="aiDrawerRef" :case-id="activeCaseId"
                       :case-label="activeCaseLabel" @clear-case="onClearCase" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import CaseListView from './views/CaseListView.vue'
import NewCaseView from './views/NewCaseView.vue'
import KnowledgeBaseView from './views/KnowledgeBaseView.vue'
import OperationLogView from './views/OperationLogView.vue'
import StatsView from './views/StatsView.vue'
import AiAssistantDrawer from './components/AiAssistantDrawer.vue'
import LoginView from './views/LoginView.vue'
import { login as apiLogin, fetchMe, logout as apiLogout, getCachedUser } from './api/auth.js'

// 主内容区当前页面：cases=案件列表（默认），kb=知识库与规则
const currentView = ref('cases')

// 各模块的页头文案
const PAGE_META = {
  cases: { title: '我的案件', desc: '案件受理工作台，支持按受理节点筛选与流转处理' },
  newcase: { title: '新建受理', desc: '录入当事人陈述，AI 即时抽取要素（三层溯源·原文引句）' },
  kb: { title: '知识库与规则', desc: '法条 / 案例文件、核验规则与要素 Schema 管理' },
  logs: { title: '操作日志', desc: '系统操作审计：登录与知识库操作全程留痕' },
  stats: { title: '统计看板', desc: '知识库与 AI 助手运营数据' },
}
const pageMeta = computed(() => PAGE_META[currentView.value] || PAGE_META.cases)

// 新建受理成功后：回到案件列表并自动打开该案件详情
const pendingOpenCase = ref(null)
function onCaseCreated(caseId) {
  pendingOpenCase.value = caseId
  currentView.value = 'cases'
}

// 当前案件上下文：传给 AI 抽屉（AI 案件感知 + 「采纳到本案」激活 + 上下文条展示）
const activeCaseId = ref(null)
const activeCaseLabel = ref('')

function onOpenCase(row) {
  activeCaseId.value = row.case_id
  activeCaseLabel.value = `${row.case_id} · ${row.applicant_name} · ${row.dispute_type}`
}

// 「AI 办案」：携本案上下文唤起抽屉——每次都是全新对话，并自动带出案件要点
function onOpenCaseAi(row) {
  onOpenCase(row)
  aiDrawerRef.value?.openForCase()
}

// 上下文条 ×：退回通用问答（不离开本次会话）
function onClearCase() {
  activeCaseId.value = null
  activeCaseLabel.value = ''
}

// AI 助手抽屉引用：侧边栏菜单点击后调用组件暴露的 open()
const aiDrawerRef = ref(null)
function openAi() {
  aiDrawerRef.value?.open()
}

// 登录态：先用本地缓存快速显示（避免白屏），再用 /auth/me 校验 token 是否还有效
const user = ref(getCachedUser())

// 页面加载时校验 token：有效则恢复用户，失效则清掉本地数据回到登录页
onMounted(async () => {
  if (user.value) {
    const fresh = await fetchMe()
    if (!fresh) {
      // token 失效：http.js 已清 localStorage，这里把 user 置空触发登录页
      user.value = null
    } else {
      user.value = fresh
    }
  }
})

// 登录成功：LoginView 调了 auth.js 的 login，token 和 user 已存 localStorage，
// 这里只需要把响应里的 user 塞给组件状态
function onLogin(data) {
  user.value = data.user
}

// 退出登录：清本地存储 + 置空 user
function onLogout() {
  apiLogout()
  user.value = null
}

const counts = ref({
  all: 0, draft: 0, awaiting_confirmation: 0,
  pending_review: 0, documents_ready: 0, closed: 0,
})

function onCounts(value) {
  counts.value = value
}
</script>
