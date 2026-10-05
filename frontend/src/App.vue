<template>
  <!-- 未登录：只显示登录页；登录后进入工作台布局 -->
  <LoginView v-if="!user" @login-success="onLogin" />
  <div v-else class="layout">
    <!-- 顶栏 -->
    <header class="topbar">
      <div class="brand">⚖ 要素式受理 Agent</div>
      <div class="user">{{ user.name }} · {{ user.org }}</div>
      <div class="logout" @click="onLogout">退出</div>
    </header>
    <div class="body">
      <!-- 左侧菜单（原型图页⑦），第二个页面出现后改用 vue-router -->
      <aside class="sidebar">
        <div class="menu-item active">📂 我的案件 <el-badge class="badge" :value="counts.all" type="primary"></el-badge></div>
        <div class="menu-item">📝 新建受理</div>
        <div class="menu-item">⏳ 待签发文书 <el-badge class="badge" :value="counts.documents_ready" type="warning"></el-badge></div>
        <div class="menu-item">🧐 复核队列 <el-badge class="badge" :value="counts.pending_review" type="danger"></el-badge></div>
        <div class="menu-item">📊 统计看板</div>
        <div class="menu-item">⚙️ 知识库与规则</div>
      </aside>
      <!-- 主内容区：当前仅有案件列表；接入 vue-router 后替换为 <RouterView/> -->
      <main class="content">
        <CaseListView @counts="onCounts" />
      </main>
    </div>
    <!-- 页⑥ AI 助手为全局组件，挂在布局最外层 -->
    <AiAssistantDrawer />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import CaseListView from './views/CaseListView.vue'
import AiAssistantDrawer from './components/AiAssistantDrawer.vue'
import LoginView from './views/LoginView.vue'
import { login as apiLogin, fetchMe, logout as apiLogout, getCachedUser } from './api/auth.js'

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
  pending_review: 0, documents_ready: 0, completed: 0,
})

function onCounts(value) {
  counts.value = value
}
</script>
