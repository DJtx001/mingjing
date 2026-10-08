<template>
  <!-- 复核工作台（页面③ · 人工介入点②）：左队列 + 右对照裁决 -->
  <div class="review-page">
    <div v-if="!canReview" class="denied">
      <el-empty :image-size="90" description="你没有复核权限（仅复核员 / 管理员可进入）" />
    </div>

    <div v-else class="review-body">
      <!-- 左栏：复核队列 -->
      <div class="queue">
        <div class="queue-head">
          <span>待复核 <b>{{ total }}</b> 案</span>
          <el-button type="primary" plain @click="loadQueue">刷新</el-button>
        </div>
        <div class="queue-list">
          <div v-for="it in queue" :key="it.task_id" class="q-item"
               :class="{ active: it.case_id === currentId, high: it.priority === 'high' }"
               @click="openItem(it)">
            <div class="q-line1">
              <span class="q-case">{{ it.case_id }}</span>
              <el-tag v-if="it.priority === 'high'" type="danger" size="small" effect="dark">优先</el-tag>
            </div>
            <div class="q-line2">{{ it.applicant_name }} · {{ it.dispute_type }}</div>
            <div class="q-line3">{{ it.level_reason || '待人工核实' }}</div>
            <div class="q-line4">{{ it.case_status_label }} · 已等待 {{ since(it.waiting_since) }}</div>
          </div>
          <el-empty v-if="!queue.length" :image-size="60"
                    :description="loadError ? '队列加载失败，请确认服务可用后刷新' : '队列为空，暂无待复核案件'" />
        </div>
      </div>

      <!-- 右栏：对照与裁决 -->
      <div v-if="detail" class="detail">
        <div class="d-head">
          <span class="d-case">{{ detail.case.case_id }}</span>
          <el-tag size="small">{{ detail.case.status_label }}</el-tag>
          <span class="d-sub">{{ detail.case.applicant_name }} · {{ detail.case.dispute_type }}</span>
        </div>

        <div class="d-scroll">
          <!-- 核验结论（对照核心） -->
          <template v-if="detail.verification">
            <div class="vr-banner" :class="detail.verification.level">
              <b>{{ LEVEL_META[detail.verification.level]?.label }}</b>
              <span>{{ detail.verification.conclusion }}</span>
            </div>
            <div v-for="(f, i) in detail.verification.hard_findings" :key="'h' + i" class="vr-finding hard">
              <b>{{ f.name }}</b> · 命中关键词：{{ (f.matched || []).join('、') }}
              <div class="vr-basis">依据：{{ f.basis }}</div>
            </div>
            <div v-for="(f, i) in detail.verification.soft_findings" :key="'s' + i" class="vr-finding warn">
              <template v-if="f.name && f.matched"><b>{{ f.name }}</b> · 命中关键词：{{ (f.matched || []).join('、') }}</template>
              <template v-else><b>{{ f.name }}</b>：{{ (f.items || []).join('、') }}</template>
            </div>
          </template>

          <div class="sec-title">当事人陈述</div>
          <pre class="narrative">{{ detail.case.narrative || '（无陈述原文）' }}</pre>

          <div class="sec-title">要素表（含原文引句）</div>
          <table class="mini-table">
            <thead><tr><th>要素</th><th>内容</th><th>原文依据</th></tr></thead>
            <tbody>
              <tr v-for="e in detail.elements" :key="e.element_id">
                <td class="mt-name">{{ e.name }}<span v-if="e.is_core" class="core">★</span></td>
                <td>{{ e.value || '（未抽取）' }}<span v-if="e.needs_clarify" class="warn-mark">待补</span></td>
                <td class="mt-quote">{{ e.quote ? '“' + e.quote + '”' : '—' }}</td>
              </tr>
            </tbody>
          </table>

          <div class="sec-title">类案参考（辅助裁决）</div>
          <div v-if="detail.similar_cases.length" class="sim-list">
            <div v-for="c in detail.similar_cases" :key="c.ref_id" class="sim-item">
              <div class="sim-title">{{ c.title }}<span class="sim-dist">相似度 {{ (1 - c.distance).toFixed(2) }}</span></div>
              <div class="sim-text">{{ c.summary }}</div>
            </div>
          </div>
          <div v-else class="empty-line">知识库暂未检索到相关类案</div>

          <template v-if="detail.previous_decisions.length">
            <div class="sec-title">历史裁决</div>
            <div v-for="(d, i) in detail.previous_decisions" :key="i" class="dec-item">
              <el-tag size="small" :type="DEC_META[d.decision]?.type">{{ DEC_META[d.decision]?.label }}</el-tag>
              <span class="dec-reason">{{ d.reason }}</span>
              <span class="dec-time">{{ d.decided_by }} · {{ fmt(d.created_at) }}</span>
            </div>
          </template>
        </div>

        <!-- 裁决区 -->
        <div v-if="detail.task" class="decide">
          <div class="decide-title">裁决（resume 人工介入②）</div>
          <el-radio-group v-model="decision" class="dec-radio">
            <el-radio value="pass">通过（转文书生成）</el-radio>
            <el-radio value="supplement">退回补充</el-radio>
            <el-radio value="reject">不予受理</el-radio>
          </el-radio-group>
          <el-input v-model="reason" type="textarea" :rows="2"
                    placeholder="裁决理由（必填，不少于 10 字；将留档回流）" />
          <div v-if="decision === 'supplement'" class="qs">
            <div v-for="(q, i) in questions" :key="i" class="q-row">
              <el-input v-model="questions[i]" size="small" placeholder="追问事项（如：请提供转账凭证核实出借金额）" />
              <el-button link type="danger" size="small" @click="questions.splice(i, 1)">删</el-button>
            </div>
            <el-button link type="primary" size="small" @click="questions.push('')">+ 添加追问</el-button>
          </div>
          <div class="decide-actions">
            <span class="hint">裁决后案件回到对应节点；理由与追问全部留档</span>
            <el-button type="primary" :loading="submitting" @click="submit">提交裁决</el-button>
          </div>
        </div>
        <div v-else class="decide done-tip">
          <el-tag type="info" size="small">该案件已完成复核</el-tag>
          <span class="hint">历史裁决留档见上方；案件已回到流程节点</span>
        </div>
      </div>

      <div v-else class="detail empty">
        <el-empty :image-size="80" description="从左侧队列选择案件，查看底情与核验对照后裁决" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { fetchReviewQueue, fetchReviewDetail, decideReview } from '../api/reviews.js'
import { getUser } from '../api/http.js'

const emit = defineEmits(['queue-count'])

// 权限：非复核员只显示提示（后端 require_reviewer 强校验兜底）
const canReview = ['reviewer', 'admin'].includes(getUser()?.role)

const LEVEL_META = {
  auto_pass: { label: '自动通过' },
  pending_review: { label: '转人工复核' },
  reject_suggestion: { label: '建议不予受理' },
}
const DEC_META = {
  pass: { label: '通过', type: 'success' },
  supplement: { label: '退回补充', type: 'warning' },
  reject: { label: '不予受理', type: 'danger' },
}
const STATUS_CN = { auto_passed: '核验通过·待生成文书', awaiting_confirmation: '要素确认中', reject_suggested: '不予受理意见' }

const queue = ref([])
const total = ref(0)
const loadError = ref(false)
const currentId = ref(null)
const detail = ref(null)
const decision = ref('pass')
const reason = ref('')
const questions = ref([''])
const submitting = ref(false)

async function loadQueue() {
  try {
    const r = await fetchReviewQueue()
    queue.value = r.items || []
    total.value = r.total || 0
    loadError.value = false
    emit('queue-count', total.value)
  } catch (e) {
    loadError.value = true
    ElMessage.error(e.message)
  }
}

// 供案件列表「去复核」直达：切到本页后聚焦指定案件
async function focusCase(caseId) {
  await loadQueue()
  const it = queue.value.find(i => i.case_id === caseId)
  if (it) await openItem(it)
}
defineExpose({ focusCase })

async function openItem(it) {
  currentId.value = it.case_id
  decision.value = 'pass'
  reason.value = ''
  questions.value = ['']
  try {
    detail.value = await fetchReviewDetail(it.case_id)
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function submit() {
  if (reason.value.trim().length < 10) {
    ElMessage.warning('裁决理由不少于 10 字（数据飞轮回流）')
    return
  }
  const label = { pass: '通过（转文书生成）', supplement: '退回补充', reject: '不予受理' }[decision.value]
  try {
    await ElMessageBox.confirm(
      `以「${label}」裁决案件 ${currentId.value}？理由与追问将全部留档。`,
      '确认裁决', { type: 'warning', confirmButtonText: '确认裁决', cancelButtonText: '再想想' })
  } catch { return }
  submitting.value = true
  try {
    const qs = decision.value === 'supplement'
      ? questions.value.map(s => s.trim()).filter(Boolean) : null
    const r = await decideReview(currentId.value, {
      decision: decision.value, reason: reason.value.trim(), questions: qs,
    })
    ElMessage.success(`已裁决 → ${STATUS_CN[r.new_status] || r.new_status}`)
    await loadQueue()
    await openItem({ case_id: currentId.value })   // 重载详情（任务已关闭）
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    submitting.value = false
  }
}

function since(t) {
  if (!t) return '—'
  const ms = Date.now() - new Date(t.replace(' ', 'T')).getTime()
  if (isNaN(ms) || ms < 0) return '—'
  const min = Math.floor(ms / 60000)
  if (min < 60) return `${Math.max(min, 1)} 分钟`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr} 小时`
  return `${Math.floor(hr / 24)} 天`
}

function fmt(t) {
  return t ? String(t).slice(5, 16).replace('T', ' ') : ''
}

onMounted(() => {
  if (canReview) loadQueue()
})
</script>

<style scoped>
.review-page { background: #fff; border-radius: var(--radius); padding: 16px; box-shadow: var(--shadow-card); }
.denied { padding: 40px 0; }
.review-body { display: flex; gap: 14px; height: calc(100vh - 220px); min-height: 520px; }

/* 左栏队列 */
.queue { width: 292px; flex: none; display: flex; flex-direction: column; border: 1px solid #e9eef6; border-radius: 10px; overflow: hidden; background: #fafbfe; }
.queue-head { display: flex; align-items: center; justify-content: space-between; padding: 10px 12px; font-size: 13px; color: #1f3350; border-bottom: 1px solid #eef2f8; }
.queue-head b { color: #2b5fad; font-size: 15px; }
.queue-list { flex: 1; overflow-y: auto; padding: 8px; }
.q-item { padding: 9px 10px; border-radius: 8px; cursor: pointer; margin-bottom: 6px; border: 1px solid transparent; background: #fff; }
.q-item:hover { border-color: #d8e2f0; }
.q-item.active { background: #eaf1fb; border-color: #c6d8f2; }
.q-item.high { border-left: 3px solid #d9534f; }
.q-line1 { display: flex; align-items: center; gap: 6px; }
.q-case { font-weight: 700; font-size: 13px; color: #16345e; }
.q-line2 { margin-top: 2px; font-size: 12.5px; color: #3a4a60; }
.q-line3 { margin-top: 3px; font-size: 12px; color: #7c8db5; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.q-line4 { margin-top: 4px; font-size: 11.5px; color: #a6adb8; }

/* 右栏详情 */
.detail { flex: 1; min-width: 0; display: flex; flex-direction: column; border: 1px solid #e9eef6; border-radius: 10px; overflow: hidden; }
.detail.empty { align-items: center; justify-content: center; }
.d-head { display: flex; align-items: center; gap: 10px; padding: 10px 14px; border-bottom: 1px solid #eef2f8; }
.d-case { font-weight: 700; font-size: 14.5px; color: #16345e; }
.d-sub { font-size: 12.5px; color: #5a6b84; }
.d-scroll { flex: 1; overflow-y: auto; padding: 12px 14px; }
.sec-title { margin: 14px 0 6px; font-weight: 600; font-size: 13.5px; color: #1f3350; }
.sec-title:first-child { margin-top: 0; }
.narrative { white-space: pre-wrap; word-break: break-word; font-family: inherit; font-size: 13px; line-height: 1.8; color: #303133; background: #fafbfd; border: 1px solid #eef1f6; border-radius: 8px; padding: 10px 12px; margin: 0; max-height: 180px; overflow-y: auto; }
.mini-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.mini-table th { text-align: left; color: #7c8db5; font-weight: 600; padding: 5px 8px; border-bottom: 1px solid #eef1f6; }
.mini-table td { padding: 6px 8px; border-bottom: 1px solid #f4f7fb; vertical-align: top; color: #303133; }
.mt-name { white-space: nowrap; font-weight: 600; color: #1f3350; }
.core { color: #d9534f; margin-left: 2px; }
.warn-mark { color: #b07a1e; font-size: 11px; margin-left: 4px; }
.mt-quote { color: #6b7a90; }
.vr-banner { display: flex; flex-direction: column; gap: 3px; padding: 10px 12px; border-radius: 8px; font-size: 13px; line-height: 1.7; }
.vr-banner.auto_pass { background: #f0f9eb; color: #3d7a2a; }
.vr-banner.pending_review { background: #fdf6ec; color: #9a6a1a; }
.vr-banner.reject_suggestion { background: #fdf2f1; color: #b42318; }
.vr-finding { padding: 8px 12px; margin-top: 6px; border-radius: 8px; font-size: 12.5px; color: #303133; background: #fafbfd; border-left: 3px solid #d9534f; }
.vr-finding.warn { border-left-color: #e6a23c; }
.vr-basis { margin-top: 3px; font-size: 12px; color: #8492a6; }
.sim-list { display: flex; flex-direction: column; gap: 8px; }
.sim-item { padding: 9px 12px; border: 1px solid #eef1f6; border-radius: 8px; background: #fcfdff; }
.sim-title { font-size: 13px; font-weight: 600; color: #1f3350; }
.sim-dist { margin-left: 8px; font-size: 11.5px; color: #67c23a; font-weight: 400; }
.sim-text { margin-top: 4px; font-size: 12px; color: #5a6b84; line-height: 1.7; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.empty-line { font-size: 12.5px; color: #a6adb8; }
.dec-item { display: flex; align-items: baseline; gap: 8px; padding: 6px 0; font-size: 12.5px; }
.dec-reason { flex: 1; color: #3a4a60; }
.dec-time { font-size: 11.5px; color: #a6adb8; }

/* 裁决区 */
.decide { border-top: 2px solid #eef2f8; padding: 12px 14px; background: #fcfdff; }
.decide-title { font-weight: 700; font-size: 13.5px; color: #1f3350; margin-bottom: 8px; }
.dec-radio { margin-bottom: 8px; }
.qs { margin-top: 8px; }
.q-row { display: flex; gap: 6px; margin-bottom: 6px; }
.decide-actions { display: flex; align-items: center; justify-content: flex-end; gap: 12px; margin-top: 10px; }
.decide-actions .hint, .done-tip .hint { font-size: 12px; color: #909399; }
.done-tip { display: flex; align-items: center; gap: 10px; }
</style>
