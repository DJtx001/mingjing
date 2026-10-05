<template>
  <!-- 页⑥ AI 助手：右下角悬浮按钮 + 抽屉（全局组件，无独立路由） -->
  <div class="ai-fab" @click="openDrawer">
    <div class="fab-btn">
      <svg viewBox="0 0 24 24" width="34" height="34" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <rect x="3" y="10" width="18" height="11" rx="3"/>
        <path d="M12 3v3"/>
        <circle cx="12" cy="3" r="1.2" fill="currentColor" stroke="none"/>
        <circle cx="9" cy="15" r="1.3" fill="currentColor" stroke="none"/>
        <circle cx="15" cy="15" r="1.3" fill="currentColor" stroke="none"/>
        <path d="M9 18h6"/>
      </svg>
    </div>
    <div class="fab-glow"></div>
    <span class="fab-label">AI 助手</span>
  </div>

  <el-drawer v-model="drawer" size="720px" :with-header="false">
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
          <el-tag v-if="caseId" size="small" type="success" effect="light" round>案件 {{ caseId }}</el-tag>
        </div>
        <el-button class="new-btn" size="small" @click="newSession">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          新会话
        </el-button>
      </div>

      <div class="drawer-body">
        <!-- 左侧：会话列表 -->
        <div class="session-panel">
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
                <div class="session-title">{{ s.last_message || '新对话' }}</div>
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
                <svg viewBox="0 0 24 24" width="40" height="40" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>
              </div>
              <p>受理工位随问随答</p>
              <span>知识库未覆盖时会明确告知「暂无依据」</span>
            </div>
            <div v-for="(m, i) in messages" :key="i" class="msg" :class="m.role">
              <div class="bubble" :class="{ streaming: m.streaming }">{{ m.content }}</div>
              <div v-for="(c, j) in m.citations" :key="j" class="cite-card">
                <div>{{ c.citation_type === 'law' ? '📜' : '📖' }} {{ c.title }}</div>
                <div class="actions">
                  <el-button link type="primary" size="small">↗ 查看原文</el-button>
                  <el-button v-if="caseId" link type="success" size="small" @click="adopt(m, c)">✅ 采纳到本案</el-button>
                </div>
              </div>
            </div>
          </div>
          <div class="quick-qs">
            <span v-for="q in quickQuestions" :key="q" class="quick-tag" @click="input = q">{{ q }}</span>
          </div>
          <div class="input-bar">
            <el-input
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
</template>

<script setup>
import { ref, nextTick } from 'vue'
import { ElMessage } from 'element-plus'
import { chatStream, adoptCitation, listSessions, getSessionMessages, deleteSession } from '../api/assist.js'

const props = defineProps({
  caseId: { type: String, default: null },
})

const drawer = ref(false)
const sessionId = ref(null)
const messages = ref([])
const input = ref('')
const sending = ref(false)
const chatList = ref(null)
const sessions = ref([])

const quickQuestions = [
  '催讨的诉讼时效从什么时候起算？',
  '这种情况能申请司法确认吗？',
  '生成一份要素补充询问清单',
]

async function openDrawer() {
  drawer.value = true
  await loadSessions()
}

async function loadSessions() {
  try {
    const res = await listSessions(props.caseId)
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
  const aiMsg = { role: 'assistant', content: '', streaming: true, citations: [], reply_id: null }
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
  await adoptCitation({ caseId: props.caseId, replyId: message.reply_id, citation })
  ElMessage.success('已采纳到本案类案参考')
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
  background: #fff;
  border-bottom: 1px solid #ebeef5;
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
  background: linear-gradient(135deg, #409eff 0%, #66b1ff 100%);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 12px rgba(64, 158, 255, 0.3);
}
.title-text {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}
.title-name {
  font-size: 17px;
  font-weight: 700;
  color: #1f2937;
  letter-spacing: 0.3px;
}
.title-sub {
  font-size: 11px;
  color: #909399;
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
.new-btn {
  border: none;
  background: #f0f7ff;
  color: #409eff;
  border-radius: 8px;
  padding: 8px 14px;
  font-weight: 500;
  transition: all 0.2s;
}
.new-btn:hover {
  background: #409eff;
  color: #fff;
}

/* ===== 主体布局 ===== */
.drawer-body {
  display: flex;
  flex: 1;
  min-height: 0;
}

/* ===== 左侧会话面板 ===== */
.session-panel {
  width: 220px;
  display: flex;
  flex-direction: column;
  background: #f8f9fb;
  border-right: 1px solid #ebeef5;
  padding: 16px 10px;
}
.panel-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: #606266;
  padding: 0 8px 10px;
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
  background: #409eff;
  border-radius: 2px;
}
.session-avatar {
  width: 28px;
  height: 28px;
  border-radius: 7px;
  background: #ecf5ff;
  color: #409eff;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 1px;
}
.session-item.active .session-avatar {
  background: #409eff;
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
  color: #e4e7ed;
  margin-bottom: 4px;
}
.empty-chat p { margin: 0; font-size: 14px; color: #909399; }
.empty-chat span { font-size: 12px; }

/* ===== 快捷问题 ===== */
.quick-qs {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 12px 0;
}
.quick-tag {
  font-size: 12px;
  color: #409eff;
  background: #ecf5ff;
  padding: 6px 12px;
  border-radius: 14px;
  cursor: pointer;
  border: 1px solid #d9ecff;
  transition: all 0.2s;
}
.quick-tag:hover {
  background: #409eff;
  color: #fff;
  border-color: #409eff;
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
  box-shadow: 0 0 0 1px #409eff inset;
}
.send-btn {
  border: none;
  border-radius: 22px;
  padding: 10px 20px;
  font-weight: 600;
  background: linear-gradient(135deg, #409eff 0%, #66b1ff 100%);
  box-shadow: 0 4px 12px rgba(64, 158, 255, 0.3);
  display: flex;
  align-items: center;
  gap: 4px;
  transition: all 0.2s;
}
.send-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(64, 158, 255, 0.4);
}
.send-btn:active { transform: translateY(0); }

/* ===== 气泡 ===== */
.msg { display: flex; margin-bottom: 14px; }
.msg.user { justify-content: flex-end; }
.msg.assistant { justify-content: flex-start; }
.bubble {
  max-width: 78%;
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
.msg.user .bubble {
  background: linear-gradient(135deg, #409eff, #66b1ff);
  color: #fff;
  border-bottom-right-radius: 4px;
}
.msg.assistant .bubble {
  background: #f4f7fb;
  color: #303133;
  border-bottom-left-radius: 4px;
}
.bubble.streaming::after {
  content: '▋';
  animation: blink 1s infinite;
  color: #409eff;
}
@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }

/* ===== 右下角悬浮按钮 ===== */
.ai-fab {
  position: fixed;
  right: 32px;
  bottom: 32px;
  z-index: 2000;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}
.fab-btn {
  position: relative;
  width: 72px;
  height: 72px;
  border-radius: 22px;
  background: linear-gradient(135deg, #2b6cb0 0%, #409eff 50%, #66b1ff 100%);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 8px 24px rgba(43, 108, 176, 0.45), 0 2px 8px rgba(0, 0, 0, 0.12);
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: visible;
}
.fab-glow {
  position: absolute;
  top: -4px; left: -4px; right: -4px; bottom: -4px;
  border-radius: 26px;
  background: linear-gradient(135deg, #409eff, #66b1ff);
  opacity: 0.4;
  filter: blur(12px);
  z-index: -1;
  animation: glow 3s ease-in-out infinite;
}
@keyframes glow {
  0%, 100% { opacity: 0.3; transform: scale(1); }
  50% { opacity: 0.55; transform: scale(1.05); }
}
.ai-fab:hover .fab-btn {
  transform: translateY(-4px) scale(1.06);
  box-shadow: 0 14px 32px rgba(43, 108, 176, 0.55), 0 4px 12px rgba(0, 0, 0, 0.15);
}
.ai-fab:active .fab-btn {
  transform: translateY(-1px) scale(0.98);
}
.fab-label {
  font-size: 12px;
  color: #fff;
  background: rgba(31, 41, 55, 0.85);
  padding: 4px 12px;
  border-radius: 12px;
  white-space: nowrap;
  opacity: 0;
  transform: translateY(4px);
  transition: all 0.25s ease;
  pointer-events: none;
  backdrop-filter: blur(4px);
}
.ai-fab:hover .fab-label {
  opacity: 1;
  transform: translateY(0);
}
</style>
