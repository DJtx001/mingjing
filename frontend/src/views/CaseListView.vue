<template>
  <div class="card">
    <el-tabs v-model="tab" @tab-change="load">
      <el-tab-pane :label="'全部 ' + counts.all" name="all"></el-tab-pane>
      <el-tab-pane :label="'草稿 ' + counts.draft" name="draft"></el-tab-pane>
      <el-tab-pane :label="'要素确认中 ' + counts.awaiting_confirmation" name="awaiting_confirmation"></el-tab-pane>
      <el-tab-pane :label="'待复核 ' + counts.pending_review" name="pending_review"></el-tab-pane>
      <el-tab-pane :label="'待签发 ' + counts.documents_ready" name="documents_ready"></el-tab-pane>
      <el-tab-pane :label="'调解中 ' + counts.issued" name="issued"></el-tab-pane>
      <el-tab-pane :label="'已办结 ' + counts.archived" name="archived"></el-tab-pane>
    </el-tabs>
    <el-table :data="cases" size="small" stripe v-loading="loading"
              @row-click="openCase" style="cursor: pointer">
      <el-table-column prop="case_id" label="案件编号" width="150"></el-table-column>
      <el-table-column prop="dispute_type" label="纠纷类型" width="100"></el-table-column>
      <el-table-column prop="applicant_name" label="当事人" min-width="150"></el-table-column>
      <el-table-column prop="status_label" label="当前节点" min-width="150"></el-table-column>
      <el-table-column label="核验分流" width="110">
        <template #default="{ row }">
          <el-tag v-if="row.triage === 'pass'" type="success" size="small">pass · 通过</el-tag>
          <el-tag v-else-if="row.triage === 'review'" type="warning" size="small">review · 复核</el-tag>
          <el-tag v-else-if="row.triage === 'reject'" type="danger" size="small">reject · 拒绝</el-tag>
          <span v-else>—</span>
        </template>
      </el-table-column>
      <el-table-column label="更新时间" width="150">
        <template #default="{ row }">{{ (row.updated_at || '').slice(5, 16).replace('T', ' ') }}</template>
      </el-table-column>
      <el-table-column label="操作" width="290">
        <template #default="{ row }">
          <el-button type="primary" size="small" plain
                     @click.stop="emit('open-case-ai', row)">🤖 AI 办案</el-button>
          <!-- 待复核/待确认驳回：引导到复核工作台（受理员看到只读提示） -->
          <el-button v-if="row.status === 'pending_review' || (row.status === 'reject_suggested' && row.review_pending)"
                     :type="canReview ? 'warning' : 'info'" size="small" plain
                     :disabled="!canReview" @click.stop="goReview(row)">
            🧐 {{ canReview ? '去复核' : '复核中' }}</el-button>
          <!-- 复核已确认驳回：下一步是生成并签发通知书 -->
          <el-button v-else-if="row.status === 'reject_suggested'"
                     type="primary" size="small" plain
                     @click.stop="openCase(row, 'docs')">📄 生成通知书</el-button>
          <el-button v-else-if="row.status === 'issued'" type="success" size="small" plain
                     @click.stop="openCase(row, 'mediation')">⚖ 调解结案</el-button>
          <el-button v-else-if="['closed', 'rejected'].includes(row.status)"
                     link type="primary" size="small" @click.stop="openCase(row)">查看档案</el-button>
          <el-button v-else link type="primary" size="small" @click.stop="openCase(row)">继续处理</el-button>
          <!-- 文书入口：核验通过/待签发，直达文书 tab -->
          <el-button v-if="['auto_passed', 'documents_ready'].includes(row.status)"
                     type="success" size="small" plain
                     @click.stop="openCase(row, 'docs')">📄 文书</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>

  <!-- 案件工作台：信息 / 案情 / 要素确认（页面②） / 核验 / 文书 / 备注 -->
  <el-dialog v-model="detailVisible" width="820px" top="5vh" destroy-on-close>
    <template #header>
      <span class="detail-title">{{ detail.case?.case_id || '' }}</span>
      <el-tag v-if="detail.case" size="small" class="detail-status">{{ detail.case.status_label }}</el-tag>
      <el-tag v-if="detail.verification_level" size="small" class="detail-status"
              :type="LEVEL_META[detail.verification_level]?.type">
        {{ LEVEL_META[detail.verification_level]?.label }}
      </el-tag>
    </template>
    <div v-loading="detailLoading" class="detail-body">
      <el-tabs v-model="dtab">
        <!-- 信息 -->
        <el-tab-pane label="信息" name="info">
          <!-- 下一步指引：把"当前节点该做什么"说清楚（减少"点了没反应"的困惑） -->
          <div v-if="nextStepText" class="next-step"><span class="ns-icon">→</span>{{ nextStepText }}</div>
          <div v-if="detail.case" class="case-info">
            <div class="info-item"><span class="k">纠纷类型</span>{{ detail.case.dispute_type }}</div>
            <div class="info-item"><span class="k">当事人</span>{{ detail.case.applicant_name }}</div>
            <div class="info-item">
              <span class="k">核验分流</span>
              <el-tag v-if="detail.case.triage === 'pass'" type="success" size="small">pass · 通过</el-tag>
              <el-tag v-else-if="detail.case.triage === 'review'" type="warning" size="small">review · 复核</el-tag>
              <el-tag v-else-if="detail.case.triage === 'reject'" type="danger" size="small">reject · 拒绝</el-tag>
              <span v-else>—</span>
            </div>
            <div class="info-item"><span class="k">更新时间</span>{{ (detail.case.updated_at || '').slice(0, 16).replace('T', ' ') }}</div>
          </div>
          <div class="notes-head">流转时间线</div>
          <el-timeline v-if="detail.history?.length" class="timeline">
            <el-timeline-item v-for="(h, i) in detail.history" :key="i"
                              :timestamp="fmtTime(h.created_at)" placement="top">
              {{ h.to_status }}<span v-if="h.note" class="tl-note"> · {{ h.note }}</span>
            </el-timeline-item>
          </el-timeline>
          <el-empty v-else description="暂无流转记录（演示种子案件）" :image-size="60" />
        </el-tab-pane>

        <!-- 案情（陈述原文） -->
        <el-tab-pane label="案情" name="narrative">
          <pre v-if="detail.case?.narrative" class="narrative-text">{{ detail.case.narrative }}</pre>
          <el-empty v-else description="该案件没有录入陈述原文（演示种子案件）" :image-size="70" />
        </el-tab-pane>

        <!-- 要素确认（页面②核心：原文引句 + 人工确认回环） -->
        <el-tab-pane :label="`要素确认（${elements.length}）`" name="elements">
          <template v-if="elements.length">
            <div v-if="detail.reviewFollowup" class="rv-followup">
              <b>复核补充要求</b>：{{ detail.reviewFollowup.reason }}
              <ul v-if="detail.reviewFollowup.questions?.length">
                <li v-for="(q, i) in detail.reviewFollowup.questions" :key="i">{{ q }}</li>
              </ul>
            </div>
            <div class="el-ops-tip">
              核对每项要素与其原文依据，标记确认 / 修正 / 待补后提交，系统将自动核验分流
            </div>
            <div class="el-list">
              <div v-for="el in elements" :key="el.element_id" class="el-card"
                   :class="{ marked: elMark(el) !== 'confirm', missing: el.needs_clarify }">
                <div class="el-head">
                  <span class="el-name">{{ el.name }}</span>
                  <el-tag v-if="el.is_core" size="small" type="danger" effect="plain">核心</el-tag>
                  <el-tag size="small" :type="CONF_META[el.confidence_level]?.type">
                    {{ CONF_META[el.confidence_level]?.label }} {{ Math.round((el.confidence || 0) * 100) }}%</el-tag>
                  <span class="el-spacer"></span>
                  <el-button size="small" :type="elMark(el) === 'confirm' ? 'success' : 'default'"
                             @click="mark(el, 'confirm')">✓ 确认</el-button>
                  <el-button size="small" :type="elMark(el) === 'modify' ? 'warning' : 'default'"
                             @click="doModify(el)">✎ 修正</el-button>
                  <el-button size="small" :type="elMark(el) === 'mark_missing' ? 'danger' : 'default'"
                             @click="mark(el, 'mark_missing')">? 待补</el-button>
                  <el-button size="small" link type="primary" @click="doClarify(el)">💬 询问话术</el-button>
                </div>
                <div class="el-value">{{ elMark(el) === 'modify' && elReason[el.element_id]?.value != null
                  ? elReason[el.element_id].value : (el.value || '（未抽取到）') }}</div>
                <div v-if="el.quote" class="el-quote">原文：“{{ el.quote }}”</div>
                <div v-else-if="el.value" class="el-quote none">（未定位到原文引句）</div>
                <div v-if="elReason[el.element_id]?.reason" class="el-reason">
                  修正理由：{{ elReason[el.element_id].reason }}</div>
              </div>
            </div>
            <div class="el-submit">
              <span class="hint">修正/待补的要素将记入确认流水（数据回流）</span>
              <el-button type="primary" :loading="submittingEls" @click="submitElements">
                提交确认并核验
              </el-button>
            </div>
          </template>
          <el-empty v-else description="该案件还没有要素（演示种子案件未走抽取流程）" :image-size="70" />
        </el-tab-pane>

        <!-- 核验报告 -->
        <el-tab-pane label="核验" name="verify">
          <template v-if="verification">
            <div class="vr-banner" :class="verification.level">
              <b>{{ LEVEL_META[verification.level]?.label }}</b>
              <span>{{ verification.conclusion }}</span>
            </div>
            <template v-if="verification.hard_findings?.length">
              <div class="notes-head">硬规则命中（{{ verification.hard_findings.length }}）</div>
              <div v-for="(f, i) in verification.hard_findings" :key="i" class="vr-finding hard">
                <b>{{ f.name }}</b> · 命中关键词：{{ (f.matched || []).join('、') }}
                <div class="vr-basis">依据：{{ f.basis }}</div>
              </div>
            </template>
            <template v-if="verification.soft_findings?.length">
              <div class="notes-head">复核项（{{ verification.soft_findings.length }}）</div>
              <div v-for="(f, i) in verification.soft_findings" :key="i" class="vr-finding warn">
                <template v-if="f.name && f.matched"><b>{{ f.name }}</b> · 命中关键词：{{ (f.matched || []).join('、') }}</template>
                <template v-else><b>{{ f.name }}</b>：{{ (f.items || []).join('、') }}</template>
              </div>
            </template>
            <div class="vr-meta">核验模型：{{ verification.model }} · {{ fmtTime(verification.verified_at) }}</div>
          </template>
          <el-empty v-else description="尚未核验——在「要素确认」页提交后自动触发" :image-size="70" />
        </el-tab-pane>

        <!-- 文书（四产出物生成 + 签发；控件与「文书签发」页共用 DocumentPanel） -->
        <el-tab-pane label="文书" name="docs">
          <DocumentPanel v-if="detail.case" :case-id="detail.case.case_id" @changed="onDocsChanged" />
        </el-tab-pane>

        <!-- 调解结果与协议书（页面⑤：录入 → 纯模板生成 → 签发结案） -->
        <el-tab-pane label="调解" name="mediation">
          <MediationPanel v-if="detail.case" :case-id="detail.case.case_id" @changed="onDocsChanged" />
        </el-tab-pane>

        <!-- 备注（AI 采纳回流落点） -->
        <el-tab-pane :label="`备注（${detail.notes.length}）`" name="notes">
          <div class="notes-head">
            <span>AI 助手引用采纳的内容汇总在此</span>
            <el-button link type="primary" size="small" @click="reloadDetail">刷新</el-button>
          </div>
          <el-empty v-if="!detail.notes.length" description="暂无备注" :image-size="72" />
          <div v-else class="notes-list">
            <div v-for="n in detail.notes" :key="n.id" class="note-item">
              <div class="note-head">
                <el-tag :type="tagType(n.tag)" size="small">{{ tagLabel(n.tag) }}</el-tag>
                <span class="note-source">{{ n.source || '' }}</span>
                <span class="note-time">{{ fmtTime(n.created_at) }}</span>
              </div>
              <div class="note-content">{{ n.content }}</div>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>
  </el-dialog>
</template>

<script setup>
import { ref, reactive, computed, watch, onMounted } from 'vue'
import { fetchCases, fetchCaseDetail } from '../api/cases.js'
import { getUser } from '../api/http.js'
import { fetchElements, confirmElements, fetchVerification, fetchClarify } from '../api/intake.js'
import { fetchReviewCount } from '../api/reviews.js'
import DocumentPanel from '../components/DocumentPanel.vue'
import MediationPanel from '../components/MediationPanel.vue'

const props = defineProps({
  openCaseId: { type: String, default: null },   // 新建受理成功后自动打开的案号
})

const emit = defineEmits(['counts', 'open-case', 'open-case-ai', 'go-review'])

// 复核权限（决定"去复核"按钮可点还是只读提示；后端 require_reviewer 强校验兜底）
const canReview = ['reviewer', 'admin'].includes(getUser()?.role)

const loading = ref(false)
const cases = ref([])
const tab = ref('all')
const counts = ref({
  all: 0, draft: 0, awaiting_confirmation: 0, pending_review: 0,
  documents_ready: 0, auto_passed: 0, closed: 0, issued: 0, rejected: 0, archived: 0,
})

const LEVEL_META = {
  auto_pass: { label: '自动通过', type: 'success' },
  pending_review: { label: '转人工复核', type: 'warning' },
  reject_suggestion: { label: '建议不予受理', type: 'danger' },
}
const CONF_META = {
  high: { label: '高置信', type: 'success' },
  medium: { label: '中置信', type: 'warning' },
  low: { label: '低置信', type: 'info' },
}

async function load() {
  loading.value = true
  try {
    // 「已办结」= 聚合终态（closed+rejected）；issued（调解中）有独立 tab。后端 status 支持逗号多值
    const status = tab.value === 'all' ? ''
      : tab.value === 'archived' ? 'closed,rejected' : tab.value
    const data = await fetchCases({ status, pageSize: 20 })
    cases.value = data.items
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

async function loadCounts() {
  try {
    const data = await fetchCases({ pageSize: 100 })
    const all = data.items
    const next = { all: all.length, draft: 0, awaiting_confirmation: 0, pending_review: 0,
                   documents_ready: 0, auto_passed: 0, closed: 0, issued: 0, rejected: 0,
                   reject_suggested: 0 }
    for (const c of all) {
      if (next[c.status] !== undefined) next[c.status]++
    }
    next.archived = next.closed + next.rejected
    // 徽章口径：文书待办 = 待签发 + 意见稿（与文书签发页列表一致）
    next.doc_pending = next.documents_ready + next.reject_suggested
    // 徽章口径：复核 = 待裁决任务数（拉取失败时用案件状态近似）
    try {
      next.review_pending = (await fetchReviewCount()).pending
    } catch {
      next.review_pending = next.pending_review + next.reject_suggested
    }
    counts.value = { ...counts.value, ...next }
    emit('counts', { ...counts.value })
  } catch { /* 徽标计数失败不打扰 */ }
}

// ---------- 案件工作台 ----------
const detailVisible = ref(false)
const detailLoading = ref(false)
const dtab = ref('info')
const detail = ref({ case: null, notes: [], history: [] })
const elements = ref([])
const verification = ref(null)
const elOps = reactive({})      // element_id -> {action, value, reason}
const elReason = reactive({})   // element_id -> {value, reason}（修正态展示用）
const submittingEls = ref(false)
let currentCaseId = ''

function openCase(row, tab = null) {
  if (!row?.case_id) return
  currentCaseId = row.case_id
  detailVisible.value = true
  emit('open-case', row)
  loadDetail(tab)
}

// 新建受理成功后（App 传入 openCaseId）自动打开
watch(() => props.openCaseId, (id) => {
  if (id) openCase({ case_id: id })
})

async function loadDetail(tab = 'info') {
  detailLoading.value = true
  // tab || 'info'：openCase 的默认参数是 null，而 JS 默认参数只在 undefined 时生效——
  // 直传 null 会让 el-tabs 没有任何 pane 匹配（全部 display:none，信息页空白）
  dtab.value = tab || 'info'
  verification.value = null
  Object.keys(elOps).forEach(k => delete elOps[k])
  Object.keys(elReason).forEach(k => delete elReason[k])
  try {
    const data = await fetchCaseDetail(currentCaseId)
    if (data.error) {
      ElMessage.error(data.error.message)
      detailVisible.value = false
      return
    }
    detail.value = { case: data.case, notes: data.notes || [], history: data.history || [],
                     reviewFollowup: data.review_followup || null }
    // 有过程的案件：并行载入要素与核验报告
    if (data.elements_count > 0) {
      const elData = await fetchElements(currentCaseId)
      elements.value = elData.elements || []
      elements.value.forEach(e => { elOps[e.element_id] = { action: 'confirm' } })
    } else {
      elements.value = []
    }
    verification.value = await fetchVerification(currentCaseId).catch(() => null)
  } catch (e) {
    ElMessage.error(e.message)
    detailVisible.value = false
  } finally {
    detailLoading.value = false
  }
}

async function reloadDetail() {
  if (currentCaseId) await loadDetail(dtab.value)   // 保持当前 tab（不跳回信息）
}

// 文书生成/签发后：刷新案件详情（状态/时间线）、列表行与计数
function onDocsChanged() {
  loadDetail(dtab.value)
  load()
  loadCounts()
}

// 「去复核」：切换到复核工作台并聚焦该案（App 负责切视图与转发 focusCase）
function goReview(row) {
  emit('go-review', row)
}

// 下一步指引：按当前状态给出"该做什么"（含复核任务是否待裁决的区分）
const nextStepText = computed(() => {
  const c = detail.value?.case
  if (!c) return ''
  const map = {
    draft: '草稿：请到「要素确认」页签核对要素并提交',
    extracting: '要素抽取中，请稍候…',
    awaiting_confirmation: '请到「要素确认」页签核对/修正要素后提交，系统将自动核验分流',
    auto_passed: '核验通过：请到「文书」页签生成四产出物',
    documents_ready: '待签发：请到「文书」页签核对溯源并签发受理登记表',
    issued: '已受理：请到「调解」页签录入调解结果，签发协议书后结案',
    closed: '案件已结案',
    rejected: '不予受理通知书已签发，案件已终结',
  }
  if (c.status === 'pending_review') {
    return '已进入复核队列：等待复核员在「复核工作台」裁决；可在此补充要素材料'
  }
  if (c.status === 'reject_suggested') {
    return c.review_pending
      ? '命中硬性规则：等待复核员在「复核工作台」确认驳回'
      : '复核已确认不予受理：请到「文书」页签生成并签发《不予受理通知书》'
  }
  return map[c.status] || ''
})

// ---------- 要素确认交互 ----------
function elMark(el) {
  return elOps[el.element_id]?.action || 'confirm'
}

function mark(el, action) {
  if (!elOps[el.element_id]) elOps[el.element_id] = {}
  elOps[el.element_id].action = action
  if (action !== 'modify') {
    delete elOps[el.element_id].value
    delete elOps[el.element_id].reason
    delete elReason[el.element_id]
  }
}

async function doModify(el) {
  try {
    const v = await ElMessageBox.prompt('请输入修正后的值', `修正「${el.name}」`, {
      inputValue: el.value || '', confirmButtonText: '下一步', cancelButtonText: '取消',
    })
    const r = await ElMessageBox.prompt('修正理由将记入数据回流（必填，≥4 字）', '修正理由', {
      confirmButtonText: '确定', cancelButtonText: '取消',
      inputValidator: (val) => (val && val.trim().length >= 4) || '理由不少于 4 个字',
    })
    elOps[el.element_id] = { action: 'modify', value: v.value, reason: r.value.trim() }
    elReason[el.element_id] = { value: v.value, reason: r.value.trim() }
  } catch { /* 用户取消 */ }
}

async function doClarify(el) {
  try {
    const d = await fetchClarify(currentCaseId, el.element_id)
    await ElMessageBox.alert(d.question, `补充询问话术 · ${d.purpose}`, { confirmButtonText: '知道了' })
  } catch (e) {
    ElMessage.error(e.message)
  }
}

async function submitElements() {
  submittingEls.value = true
  try {
    const actions = elements.value.map(e => ({
      element_id: e.element_id,
      ...(elOps[e.element_id] || { action: 'confirm' }),
    }))
    const r = await confirmElements(currentCaseId, actions)
    const meta = LEVEL_META[r.verification?.level]
    ElMessage.success(`已提交：确认 ${r.confirmed_count} · 修正 ${r.modified_count} · 待补 ${r.missing_count} → ${meta?.label}`)
    await loadDetail()          // 刷新状态/核验/时间线
    loadCounts()
    dtab.value = 'verify'       // 直达核验结果
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    submittingEls.value = false
  }
}

const TAG_META = {
  law: { label: '法条', type: 'primary' },
  similar_case: { label: '类案', type: 'success' },
  reasoning: { label: '释法说理', type: 'warning' },
}
function tagLabel(tag) { return TAG_META[tag]?.label || tag }
function tagType(tag) { return TAG_META[tag]?.type || 'info' }
function fmtTime(t) { return t ? String(t).slice(5, 16).replace('T', ' ') : '' }

onMounted(() => {
  load()
  loadCounts()
})
</script>

<style scoped>
.detail-title { font-weight: 700; font-size: 15px; color: #1f3350; }
.detail-status { margin-left: 10px; }
.detail-body { min-height: 320px; max-height: 68vh; overflow-y: auto; }
.case-info {
  display: grid; grid-template-columns: 1fr 1fr; gap: 10px 24px;
  padding: 14px 16px; background: #f6f8fc; border-radius: 10px; margin-bottom: 16px;
}
.info-item { font-size: 13.5px; color: #303133; }
.info-item .k { display: inline-block; width: 70px; color: #8492a6; }
.notes-head {
  display: flex; justify-content: space-between; align-items: center;
  margin: 16px 0 8px; font-weight: 600; font-size: 14px; color: #1f3350;
}
.timeline { padding-left: 6px; }
.next-step {
  display: flex; align-items: center; gap: 8px;
  padding: 9px 14px; margin-bottom: 12px; border-radius: 8px;
  background: #eff6ff; border-left: 3px solid #2b5fad;
  font-size: 13px; color: #2b5fad; line-height: 1.7;
}
.next-step .ns-icon { font-weight: 700; }
.tl-note { color: #909399; font-size: 12.5px; }
.narrative-text {
  white-space: pre-wrap; word-break: break-word;
  font-family: inherit; font-size: 14px; line-height: 1.9; color: #303133;
  background: #fafbfd; border: 1px solid #eef1f6; border-radius: 10px; padding: 16px 18px; margin: 0;
}
/* 要素确认 */
.el-ops-tip { font-size: 12.5px; color: #909399; margin-bottom: 10px; }
.rv-followup {
  padding: 10px 14px; margin-bottom: 10px; border-radius: 8px;
  background: #fdf6ec; border-left: 3px solid #e6a23c;
  font-size: 13px; color: #7a5a1a; line-height: 1.8;
}
.rv-followup ul { margin: 4px 0 0 18px; padding: 0; }
.el-list { display: flex; flex-direction: column; gap: 10px; }
.el-card { padding: 12px 14px; border: 1px solid #eef1f6; border-radius: 10px; background: #fff; }
.el-card.marked { border-color: #f3d19e; background: #fffdf6; }
.el-card.missing { border-color: #f4b5ae; background: #fff8f7; }
.el-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.el-name { font-weight: 600; font-size: 13.5px; color: #1f3350; }
.el-spacer { flex: 1; }
.el-value { margin-top: 8px; font-size: 14px; color: #303133; font-weight: 500; }
.el-quote { margin-top: 4px; font-size: 12.5px; color: #6b7a90; }
.el-quote.none { color: #c0c4cc; }
.el-reason { margin-top: 4px; font-size: 12.5px; color: #b8860b; }
.el-submit {
  display: flex; justify-content: flex-end; align-items: center; gap: 16px;
  margin-top: 14px; padding-top: 12px; border-top: 1px dashed #eef1f6;
}
.el-submit .hint { color: #909399; font-size: 12.5px; }
/* 核验报告 */
.vr-banner {
  display: flex; flex-direction: column; gap: 4px;
  padding: 12px 16px; border-radius: 10px; font-size: 13.5px; line-height: 1.7;
}
.vr-banner.auto_pass { background: #f0f9eb; color: #3d7a2a; }
.vr-banner.pending_review { background: #fdf6ec; color: #9a6a1a; }
.vr-banner.reject_suggestion { background: #fdf2f1; color: #b42318; }
.vr-finding {
  padding: 10px 14px; margin-bottom: 8px; border-radius: 8px;
  font-size: 13px; color: #303133; background: #fafbfd; border-left: 3px solid #d9534f;
}
.vr-finding.warn { border-left-color: #e6a23c; }
.vr-basis { margin-top: 4px; font-size: 12.5px; color: #8492a6; }
.vr-meta { margin-top: 10px; font-size: 12px; color: #a6adb8; }
/* 备注 */
.notes-list { max-height: 44vh; overflow-y: auto; }
.note-item {
  padding: 10px 12px; margin-bottom: 8px;
  background: #fafbfd; border: 1px solid #eef1f6; border-radius: 8px;
}
.note-head { display: flex; align-items: center; gap: 8px; }
.note-source { flex: 1; font-size: 12.5px; color: #5a6b84; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.note-time { font-size: 12px; color: #a6adb8; }
.note-content {
  margin-top: 6px; font-size: 13px; color: #3a4a60; line-height: 1.7;
  white-space: pre-wrap; word-break: break-word;
}
</style>
