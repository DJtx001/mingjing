<template>
  <!-- 页⑥ AI 助手：右下角悬浮胶囊按钮 + 抽屉（可拖动，位置记忆；全局组件，无独立路由） -->
  <div class="ai-fab" :style="fabStyle" @click="onFabClick" @pointerdown="onFabDown">
    <span class="fab-spark"></span>
    <div class="fab-btn">
      <svg viewBox="0 0 24 24" width="26" height="26" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
        <rect x="3" y="10" width="18" height="11" rx="3"/>
        <path d="M12 3v3"/>
        <circle cx="12" cy="3" r="1.2" fill="currentColor" stroke="none"/>
        <circle cx="9" cy="15" r="1.3" fill="currentColor" stroke="none"/>
        <circle cx="15" cy="15" r="1.3" fill="currentColor" stroke="none"/>
        <path d="M9 18h6"/>
      </svg>
      <span class="fab-text">AI 助手</span>
    </div>
  </div>

  <el-drawer v-model="drawer" size="860px" :with-header="false">
    <div class="drawer-wrap">
      <!-- 顶部栏 -->
      <div class="drawer-header">
        <div class="drawer-title">
          <div class="title-icon">
            <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
              <rect x="3" y="10" width="18" height="11" rx="3"/>
              <path d="M12 3v3"/>
              <circle cx="12" cy="3" r="1.2" fill="currentColor" stroke="none"/>
              <circle cx="9" cy="15" r="1.3" fill="currentColor" stroke="none"/>
              <circle cx="15" cy="15" r="1.3" fill="currentColor" stroke="none"/>
              <path d="M9 18h6"/>
            </svg>
          </div>
          <div class="title-text">
            <span class="title-name">明镜 AI 助手</span>
            <span class="title-sub">
              <i class="status-dot"></i>
              在线 · 知识库驱动
            </span>
          </div>
          <!-- 案件上下文条：可见可清除（×退回通用问答），让"AI 已了解本案"一目了然 -->
          <el-tag v-if="caseId" size="small" type="success" effect="light" round closable
                  class="case-chip" @close="emit('clear-case')">
            📂 {{ caseLabel || caseId }}
          </el-tag>
        </div>
      </div>

      <div class="drawer-body">
        <!-- 左侧：会话列表 -->
        <div class="session-panel">
          <button class="new-session-btn" @click="newSession">
            <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
            新建会话
          </button>
          <div class="panel-label">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
            历史会话
          </div>
          <div class="session-list">
            <div v-if="!sessions.length" class="empty-hint">暂无会话</div>
            <div
              v-for="s in sessions"
              :key="s.session_id"
              class="session-item"
              :class="{ active: s.session_id === sessionId }"
              @click="selectSession(s.session_id)"
            >
              <div class="session-avatar">
                <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
              </div>
              <div class="session-info">
                <div class="session-title">{{ s.title || '新对话' }}</div>
                <div class="session-time">{{ formatTime(s.updated_at) }}</div>
              </div>
              <el-popconfirm
                title="删除该会话？"
                confirm-button-text="删除"
                cancel-button-text="取消"
                confirm-button-type="danger"
                width="160"
                @confirm="removeSession(s.session_id)"
              >
                <template #reference>
                  <button class="del-btn" title="删除">
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-2 14a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2L5 6"/></svg>
                  </button>
                </template>
              </el-popconfirm>
            </div>
          </div>
        </div>

        <!-- 右侧：聊天区 -->
        <div class="chat-panel">
          <div class="tip-bar">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>
            基于案件要素与知识库检索回答，所有引用可溯源；不构成法律意见，以受理员判断为准。
          </div>
          <div ref="chatList" class="chat-list">
            <div v-if="!messages.length" class="empty-chat">
              <div class="empty-icon">
                <svg viewBox="0 0 24 24" width="36" height="36" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
                  <rect x="3" y="10" width="18" height="11" rx="3"/>
                  <path d="M12 3v3"/>
                  <circle cx="12" cy="3" r="1.2" fill="currentColor" stroke="none"/>
                  <circle cx="9" cy="15" r="1.3" fill="currentColor" stroke="none"/>
                  <circle cx="15" cy="15" r="1.3" fill="currentColor" stroke="none"/>
                  <path d="M9 18h6"/>
                </svg>
              </div>
              <p class="empty-title">你好，我是明镜 AI 助手</p>
              <span>基于案件要素与知识库随问随答，未覆盖时会明确告知「暂无依据」</span>
            </div>
            <div v-for="(m, i) in messages" :key="i" class="msg-row" :class="m.role">
              <div v-if="m.role === 'assistant'" class="msg-avatar avatar-ai">
                <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
                  <rect x="3" y="10" width="18" height="11" rx="3"/>
                  <path d="M12 3v3"/>
                  <circle cx="12" cy="3" r="1.2" fill="currentColor" stroke="none"/>
                  <circle cx="9" cy="15" r="1.3" fill="currentColor" stroke="none"/>
                  <circle cx="15" cy="15" r="1.3" fill="currentColor" stroke="none"/>
                  <path d="M9 18h6"/>
                </svg>
              </div>
              <div v-else class="msg-avatar avatar-user">
                <svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
              </div>
              <div class="msg-main">
                <div class="bubble" :class="{ streaming: m.streaming, 'md-body': m.role === 'assistant' }"
                     v-html="m.role === 'assistant' ? renderMd(m.content) : escapeText(m.content)"></div>
                <div v-for="(c, j) in m.citations" :key="j" class="cite-card" :class="c.citation_type">
                  <div class="cite-head">
                    <span class="cite-badge">{{ c.citation_type === 'law' ? '法条' : '案例' }}</span>
                    <span class="cite-title">{{ c.title }}</span>
                  </div>
                  <div class="cite-actions">
                    <el-button v-if="c.ref_id" link type="primary" size="small"
                               @click="onViewCitation(c)">查看原文 ↗</el-button>
                    <el-button v-if="caseId" link type="success" size="small" @click="adopt(m, c)">采纳到本案</el-button>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div class="quick-qs">
            <span v-for="q in quickQuestions" :key="q" class="quick-tag" @click="input = q">{{ q }}</span>
          </div>
          <div class="input-bar">
            <el-input
              ref="inputRef"
              v-model="input"
              placeholder="输入问题，Enter 发送"
              @keyup.enter="send"
              :disabled="sending"
            ></el-input>
            <el-button class="send-btn" type="primary" @click="send" :loading="sending">
              <svg v-if="!sending" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
              发送
            </el-button>
          </div>
        </div>
      </div>
    </div>
  </el-drawer>

  <!-- 引用原文弹窗（「查看原文」）：法条全文 / 案例四段，Markdown 渲染 -->
  <el-dialog v-model="citeVisible" :title="citeData.title" width="680px" top="6vh" append-to-body>
    <div v-loading="citeLoading" class="cite-full">
      <div v-if="citeData.meta" class="cite-full-meta">{{ citeData.meta }}</div>
      <div class="md-body" v-html="renderMd(citeData.content)"></div>
    </div>
  </el-dialog>
</template>

<script setup>
import { ref, computed, nextTick, reactive } from 'vue'
import MarkdownIt from 'markdown-it'
import { chatStream, adoptCitation, listSessions, getSessionMessages, deleteSession, fetchCitation } from '../api/assist.js'

// AI 回答按 Markdown 渲染（LLM 输出 ## / ** / 列表等；html:false 转义原始标签防 XSS）
const md = new MarkdownIt({ html: false, breaks: true, linkify: true })
function renderMd(text) { return md.render(text || '') }

// 用户消息走纯文本（转义后原样显示，保留换行）
function escapeText(text) {
  return (text || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

// ---------- 悬浮入口拖动 ----------
const FAB_POS_KEY = 'mj_ai_fab_pos'
const savedPos = (() => {
  try { return JSON.parse(localStorage.getItem(FAB_POS_KEY)) || null } catch { return null }
})()
const fabPos = ref(savedPos) // null=默认右下角；{x,y}=拖动后的左上角坐标
const fabStyle = computed(() =>
  fabPos.value
    ? { left: fabPos.value.x + 'px', top: fabPos.value.y + 'px', right: 'auto', bottom: 'auto' }
    : {},
)

let drag = null       // 拖动过程状态
let suppress = false  // 拖动结束后抑制下一次 click，避免误开抽屉

function onFabDown(e) {
  // 仅响应主键（鼠标左键 / 触摸 / 笔）
  if (e.button != null && e.button !== 0) return
  const rect = e.currentTarget.getBoundingClientRect()
  drag = {
    startX: e.clientX, startY: e.clientY,
    origLeft: rect.left, origTop: rect.top,
    w: rect.width, h: rect.height,
    moved: false,
  }
  window.addEventListener('pointermove', onFabMove)
  window.addEventListener('pointerup', onFabUp, { once: true })
}

function onFabMove(e) {
  if (!drag) return
  const dx = e.clientX - drag.startX
  const dy = e.clientY - drag.startY
  if (!drag.moved && Math.hypot(dx, dy) < 5) return // 5px 内视为点击
  drag.moved = true
  const x = Math.min(Math.max(8, drag.origLeft + dx), window.innerWidth - drag.w - 8)
  const y = Math.min(Math.max(8, drag.origTop + dy), window.innerHeight - drag.h - 8)
  fabPos.value = { x: Math.round(x), y: Math.round(y) }
}

function onFabUp() {
  window.removeEventListener('pointermove', onFabMove)
  if (drag?.moved) {
    suppress = true
    localStorage.setItem(FAB_POS_KEY, JSON.stringify(fabPos.value))
  }
  drag = null
}

function onFabClick() {
  if (suppress) { suppress = false; return }
  openDrawer()
}

// 窗口尺寸变化时把入口收回可视区
function clampFab() {
  if (!fabPos.value) return
  const el = document.querySelector('.ai-fab')
  if (!el) return
  const w = el.offsetWidth, h = el.offsetHeight
  fabPos.value = {
    x: Math.min(Math.max(8, fabPos.value.x), window.innerWidth - w - 8),
    y: Math.min(Math.max(8, fabPos.value.y), window.innerHeight - h - 8),
  }
}
window.addEventListener('resize', clampFab)

const props = defineProps({
  caseId: { type: String, default: null },
  caseLabel: { type: String, default: '' },   // 案件上下文条文案（如 "AJ2026-10086 · 王某 vs 张某 · 民间借贷"）
})

const emit = defineEmits(['clear-case'])

const drawer = ref(false)
const sessionId = ref(null)
const messages = ref([])
const input = ref('')
const sending = ref(false)
const chatList = ref(null)
const sessions = ref([])

const quickQuestions = computed(() => {
  const base = [
    '催讨的诉讼时效从什么时候起算？',
    '这种情况能申请司法确认吗？',
    '生成一份要素补充询问清单',
  ]
  // 有案件上下文时前置一条案件快捷问（案件感知直接可答）
  return props.caseId ? ['这个案子现在什么情况', ...base] : base
})

const inputRef = ref(null)

async function openDrawer() {
  drawer.value = true
  await loadSessions()
  nextTick(() => inputRef.value?.focus())   // 打开即可直接打字
}

// 「AI 办案」入口：每次都是全新对话，打开即聚焦输入框
// （想快速了解案件时，点快捷问题「这个案子现在什么情况」——不自动代问）
async function openForCase() {
  newSession()
  await openDrawer()
}

// 对外暴露：App.vue 侧边栏菜单用 open()；案件行「AI 办案」用 openForCase()
defineExpose({ open: openDrawer, openForCase })

async function loadSessions() {
  try {
    // 列表固定展示"我的所有对话"——不按当前案件过滤
    // （caseId 只用于：新对话绑定案件 + AI 案件感知；按案件过滤会让列表忽隐忽现）
    const res = await listSessions()
    sessions.value = res.items || []
  } catch (e) {
    console.error('加载会话列表失败', e)
  }
}

async function selectSession(sid) {
  if (sid === sessionId.value) return
  sessionId.value = sid
  messages.value = []
  try {
    const res = await getSessionMessages(sid)
    messages.value = (res.messages || []).map(m => ({
      role: m.role,
      content: m.content,
      citations: m.citations || [],
      reply_id: m.reply_id || null,
      streaming: false,
    }))
    scrollToBottom()
  } catch (e) {
    ElMessage.error('加载历史消息失败')
  }
}

function newSession() {
  sessionId.value = null
  messages.value = []
}

async function removeSession(sid) {
  try {
    await deleteSession(sid)
    if (sid === sessionId.value) {
      sessionId.value = null
      messages.value = []
    }
    await loadSessions()
    ElMessage.success('已删除')
  } catch (e) {
    ElMessage.error('删除失败')
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (chatList.value) chatList.value.scrollTop = chatList.value.scrollHeight
  })
}

async function send() {
  const text = input.value.trim()
  if (!text || sending.value) return
  input.value = ''
  messages.value.push({ role: 'user', content: text })
  // reactive 包装:必须经代理改属性才能触发渲染,否则流式 delta 不会实时上屏
  const aiMsg = reactive({ role: 'assistant', content: '', streaming: true, citations: [], reply_id: null })
  messages.value.push(aiMsg)
  sending.value = true
  scrollToBottom()
  const isNewSession = !sessionId.value
  try {
    for await (const { event, data } of chatStream({ sessionId: sessionId.value, caseId: props.caseId, message: text })) {
      if (event === 'start') {
        sessionId.value = data.session_id
        if (isNewSession) loadSessions()
      } else if (event === 'delta') {
        aiMsg.content += data.delta
        scrollToBottom()
      } else if (event === 'citations') {
        aiMsg.citations = data.citations
      } else if (event === 'done') {
        aiMsg.reply_id = data.reply_id
      } else if (event === 'error') {
        aiMsg.content = aiMsg.content || ('服务异常：' + (data.error && data.error.message))
      }
    }
  } catch (e) {
    aiMsg.content = aiMsg.content || ('请求失败：' + e.message)
  } finally {
    aiMsg.streaming = false
    sending.value = false
  }
}

async function adopt(message, citation) {
  try {
    await adoptCitation({ caseId: props.caseId, sessionId: sessionId.value,
                          replyId: message.reply_id, citation })
    ElMessage.success(`已采纳到本案（${props.caseId}），可在案件详情备注区查看`)
  } catch (e) {
    ElMessage.error(e.message)
  }
}

// ---------- 引用原文（查看原文弹窗） ----------
const citeVisible = ref(false), citeLoading = ref(false)
const citeData = ref({ title: '', meta: '', content: '' })

async function onViewCitation(c) {
  citeVisible.value = true
  citeLoading.value = true
  citeData.value = { title: c.title || '', meta: '', content: '' }
  try {
    const d = await fetchCitation(c.ref_id)
    citeData.value = {
      title: d.title,
      meta: (d.type === 'law' ? '法条' : '案例') + (d.meta ? ' · ' + d.meta : ''),
      content: d.content,
    }
  } catch (e) {
    citeData.value = { ...citeData.value, content: '加载失败：' + e.message }
  } finally {
    citeLoading.value = false
  }
}

function formatTime(t) {
  if (!t) return ''
  const d = new Date(t)
  if (isNaN(d)) return t.slice(5, 16)
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const mi = String(d.getMinutes()).padStart(2, '0')
  return `${mm}-${dd} ${hh}:${mi}`
}
</script>

<style scoped>
/* ===== 抽屉基础 ===== */
:deep(.el-drawer__body) {
  padding: 0;
}
.drawer-wrap {
  display: flex;
  flex-direction: column;
  height: 100%;
}

/* ===== 顶部标题栏 ===== */
.drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 20px;
  background: linear-gradient(135deg, #16345e 0%, #1d3a6e 60%, #2b5fad 130%);
}
.drawer-title {
  display: flex;
  align-items: center;
  gap: 12px;
}
.title-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.14);
  border: 1px solid rgba(255, 255, 255, 0.25);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
}
.title-text {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}
.title-name {
  font-size: 17px;
  font-weight: 700;
  color: #fff;
  letter-spacing: 0.3px;
}
.title-sub {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.72);
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: 3px;
}
.status-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #67c23a;
  box-shadow: 0 0 5px #67c23a;
  animation: pulse 2s infinite;
}
@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(0.8); }
}
/* ===== 新建会话（左侧面板顶部全宽主按钮） ===== */
.new-session-btn {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  border: none;
  background: linear-gradient(135deg, #2b5fad 0%, #5a8fd9 100%);
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  padding: 11px 12px;
  border-radius: 10px;
  cursor: pointer;
  box-shadow: 0 4px 12px rgba(43, 95, 173,0.35);
  transition: all 0.2s;
  margin-bottom: 14px;
}
.new-session-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(43, 95, 173,0.45);
}
.new-session-btn:active { transform: translateY(0); }

/* ===== 主体布局 ===== */
.drawer-body {
  display: flex;
  flex: 1;
  min-height: 0;
}

/* ===== 左侧会话面板 ===== */
.session-panel {
  width: 248px;
  display: flex;
  flex-direction: column;
  background: #f8f9fb;
  border-right: 1px solid #ebeef5;
  padding: 16px 12px;
}
.panel-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: #909399;
  padding: 2px 6px 10px;
  letter-spacing: 0.5px;
}
.session-list {
  flex: 1;
  overflow-y: auto;
}
.empty-hint {
  color: #c0c4cc;
  font-size: 12px;
  text-align: center;
  margin-top: 24px;
}
.session-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px 8px;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 4px;
  position: relative;
  transition: background 0.2s;
}
.session-item:hover { background: #fff; }
.session-item.active {
  background: #fff;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}
.session-item.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 10px;
  bottom: 10px;
  width: 3px;
  background: #2b5fad;
  border-radius: 2px;
}
.session-avatar {
  width: 28px;
  height: 28px;
  border-radius: 7px;
  background: #eaeff7;
  color: #2b5fad;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 1px;
}
.session-item.active .session-avatar {
  background: #2b5fad;
  color: #fff;
}
.session-info {
  flex: 1;
  min-width: 0;
}
.session-title {
  font-size: 13px;
  color: #303133;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-weight: 500;
}
.session-time {
  font-size: 11px;
  color: #909399;
  margin-top: 2px;
}
.del-btn {
  background: none;
  border: none;
  color: #c0c4cc;
  cursor: pointer;
  padding: 4px;
  border-radius: 4px;
  opacity: 0;
  transition: all 0.2s;
  flex-shrink: 0;
}
.session-item:hover .del-btn { opacity: 1; }
.del-btn:hover { color: #f56c6c; background: #fef0f0; }

/* ===== 右侧聊天区 ===== */
.chat-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  padding: 16px;
}
.tip-bar {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #909399;
  background: #f4f7fb;
  padding: 8px 12px;
  border-radius: 8px;
  margin-bottom: 12px;
  line-height: 1.5;
}
.chat-list {
  flex: 1;
  overflow-y: auto;
  padding: 4px;
}
.empty-chat {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #c0c4cc;
  gap: 8px;
}
.empty-chat .empty-icon {
  width: 72px;
  height: 72px;
  border-radius: 20px;
  background: linear-gradient(135deg, #eaeff7, #f4f9ff);
  color: #2b5fad;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 14px;
}
.empty-chat .empty-title { margin: 0 0 6px; font-size: 16px; font-weight: 600; color: #303133; }
.empty-chat span { font-size: 12.5px; color: #a8abb2; max-width: 320px; text-align: center; line-height: 1.6; }

/* ===== 快捷问题 ===== */
.quick-qs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 12px 0;
}
.quick-tag {
  font-size: 12px;
  color: #2b5fad;
  background: #eaeff7;
  padding: 6px 12px;
  border-radius: 14px;
  cursor: pointer;
  border: 1px solid #d5dfef;
  transition: all 0.2s;
}
.quick-tag:hover {
  background: #2b5fad;
  color: #fff;
  border-color: #2b5fad;
}

/* ===== 输入栏 ===== */
.input-bar {
  display: flex;
  gap: 10px;
  align-items: center;
  padding-top: 10px;
  border-top: 1px solid #f0f2f5;
}
.input-bar :deep(.el-input__wrapper) {
  border-radius: 22px;
  box-shadow: 0 0 0 1px #e4e7ed inset;
  padding: 4px 16px;
}
.input-bar :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px #c0c4cc inset;
}
.input-bar :deep(.el-input__wrapper.is-focus) {
  box-shadow: 0 0 0 1px #2b5fad inset;
}
.send-btn {
  border: none;
  border-radius: 22px;
  padding: 10px 20px;
  font-weight: 600;
  background: linear-gradient(135deg, #2b5fad 0%, #4a80d4 100%);
  box-shadow: 0 4px 12px rgba(43, 95, 173,0.3);
  display: flex;
  align-items: center;
  gap: 4px;
  transition: all 0.2s;
}
.send-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(43, 95, 173,0.4);
}
.send-btn:active { transform: translateY(0); }

/* ===== 消息行（头像 + 气泡） ===== */
.msg-row {
  display: flex;
  gap: 10px;
  margin-bottom: 20px;
}
.msg-row.user { flex-direction: row-reverse; }
.msg-avatar {
  width: 34px;
  height: 34px;
  border-radius: 9px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-top: 2px;
}
.avatar-ai {
  background: linear-gradient(135deg, #2b5fad, #4a80d4);
  color: #fff;
  box-shadow: 0 3px 8px rgba(43, 95, 173,0.3);
}
.avatar-user {
  background: #eef1f6;
  color: #606266;
}
.msg-main {
  max-width: 80%;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.msg-row.user .msg-main { align-items: flex-end; }
.bubble {
  padding: 11px 15px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}
.msg-row.user .bubble {
  background: linear-gradient(135deg, #2b5fad, #4a80d4);
  color: #fff;
  border-bottom-right-radius: 4px;
  box-shadow: 0 3px 10px rgba(43, 95, 173,0.22);
}
.msg-row.assistant .bubble {
  background: #f5f7fa;
  color: #303133;
  border-bottom-left-radius: 4px;
  border: 1px solid #eef0f4;
}
.bubble.streaming::after {
  content: '▋';
  animation: blink 1s infinite;
  color: #2b5fad;
}
@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }

/* 案件上下文条（头部）：超长省略，× 清除退回通用问答 */
.case-chip { max-width: 360px; }
.case-chip :deep(.el-tag__content) {
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}

/* AI 回答 Markdown 渲染（v-html 结构，white-space 交还给块级元素） */
.md-body { white-space: normal; }
.md-body p { margin: 5px 0; }
.md-body h1, .md-body h2, .md-body h3, .md-body h4 {
  margin: 12px 0 6px; font-size: 14px; font-weight: 700; color: #1f3350;
}
.md-body h1 { font-size: 15px; }
.md-body h1:first-child, .md-body h2:first-child, .md-body h3:first-child { margin-top: 2px; }
.md-body ul, .md-body ol { margin: 4px 0; padding-left: 20px; }
.md-body li { margin: 3px 0; }
.md-body li > p { margin: 0; }
.md-body strong { color: #1f3350; }
.md-body code {
  background: #eef2f8; border-radius: 4px; padding: 1px 5px;
  font-family: Consolas, "Courier New", monospace; font-size: 12px;
}
.md-body pre {
  background: #f6f8fc; border: 1px solid #e9eef6; border-radius: 8px;
  padding: 10px 12px; overflow-x: auto;
}
.md-body pre code { background: none; padding: 0; }
.md-body blockquote {
  margin: 6px 0; padding: 2px 12px;
  border-left: 3px solid #c9d8ef; color: #55627a;
}
.md-body table { border-collapse: collapse; margin: 6px 0; font-size: 12.5px; }
.md-body th, .md-body td { border: 1px solid #e2e8f2; padding: 4px 10px; }
.md-body th { background: #f4f7fc; }
.md-body a { color: #2b5fad; }
.md-body hr { border: none; border-top: 1px dashed #dde5f0; margin: 10px 0; }

/* ===== 引用卡片 ===== */
.cite-card {
  margin-top: 8px;
  width: 100%;
  background: #fff;
  border: 1px solid #e8edf3;
  border-left: 3px solid #2b5fad;
  border-radius: 8px;
  padding: 9px 12px;
  transition: box-shadow 0.2s, border-color 0.2s;
}
.cite-card.case { border-left-color: #67c23a; }
.cite-card:hover {
  box-shadow: 0 3px 12px rgba(31, 45, 61, 0.08);
  border-color: #dce6f2;
}
.cite-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.cite-badge {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 600;
  color: #2b5fad;
  background: #eaeff7;
  border-radius: 4px;
  padding: 1px 7px;
  line-height: 1.7;
}
.cite-card.case .cite-badge {
  color: #5daf34;
  background: #f0f9eb;
}
.cite-title {
  font-size: 13px;
  color: #303133;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cite-actions {
  display: flex;
  gap: 4px;
  margin-top: 2px;
  padding-left: 40px;
}
/* 引用原文弹窗 */
.cite-full { max-height: 68vh; overflow-y: auto; padding-right: 6px; }
.cite-full-meta {
  margin-bottom: 10px; padding: 6px 10px;
  background: #f4f7fc; border-radius: 6px;
  color: #5a6b84; font-size: 13px;
}
.cite-full .md-body { font-size: 14px; }

/* ===== 右下角悬浮入口（大胶囊，图标+文字常显，可拖动） ===== */
.ai-fab {
  position: fixed;
  right: 32px;
  bottom: 32px;
  z-index: 2000;
  cursor: grab;
  touch-action: none;      /* 触屏拖动时不触发页面滚动 */
  user-select: none;
  -webkit-user-drag: none;
}
.ai-fab:active { cursor: grabbing; }
.fab-btn {
  position: relative;
  display: flex;
  align-items: center;
  gap: 9px;
  height: 56px;
  padding: 0 22px 0 18px;
  border-radius: 28px;
  background: linear-gradient(135deg, #1d3a6e 0%, #2b5fad 55%, #5a8fd9 100%);
  color: #fff;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: 1px;
  box-shadow: 0 10px 28px rgba(29, 58, 110,0.45), 0 3px 10px rgba(0, 0, 0, 0.12);
  transition: all 0.28s cubic-bezier(0.4, 0, 0.2, 1);
}
/* 呼吸光晕 */
.fab-spark {
  position: absolute;
  inset: -6px;
  border-radius: 34px;
  background: linear-gradient(135deg, #2b5fad, #4a80d4);
  opacity: 0.35;
  filter: blur(14px);
  z-index: -1;
  animation: glow 3s ease-in-out infinite;
}
@keyframes glow {
  0%, 100% { opacity: 0.25; transform: scale(1); }
  50% { opacity: 0.5; transform: scale(1.04); }
}
.ai-fab:hover .fab-btn {
  transform: translateY(-3px) scale(1.03);
  box-shadow: 0 16px 36px rgba(29, 58, 110,0.55), 0 5px 14px rgba(0, 0, 0, 0.15);
}
.ai-fab:active .fab-btn {
  transform: translateY(0) scale(0.98);
}
</style>
