<template>
  <!-- 调解结果与协议书（页面⑤ · F10 结案收尾）：录入 → 纯模板生成协议书 → 签发结案 -->
  <div class="med-panel" v-loading="loading">
   <template v-if="data">
    <!-- 前置：受理文书未签发 -->
    <el-empty v-if="!canEnter && status !== 'closed'" :image-size="76"
              :description="`受理文书签发后可录入调解结果（当前节点：${data.case_status_label}）`" />

    <!-- 已结案 -->
    <template v-else-if="status === 'closed'">
      <div class="closed-banner">
        <el-tag type="success" effect="dark" size="small">已结案</el-tag>
        <span>结案文书已签发，案件办结</span>
      </div>
      <MedSummary v-if="data.result" :result="data.result" :inherited="data.inherited" />
      <div class="doc-line" v-if="data.doc">
        结案文书：{{ data.doc.type_label }}（{{ data.doc.status_label }}）
        <el-button link type="primary" size="small" @click="togglePreview">
          {{ previewOpen ? '收起预览' : '查看全文' }}
        </el-button>
      </div>
      <div v-if="previewOpen" class="doc-preview md-body" v-html="previewHtml"></div>
    </template>

    <!-- 已录（待签发） -->
    <template v-else-if="data.result">
      <div class="rec-head">
        <el-tag :type="data.result.reached ? 'success' : 'danger'" size="small">
          {{ data.result.reached ? '已达成协议' : '未达成（终结）' }}
        </el-tag>
        <span class="rec-sub">录入于 {{ (data.result.updated_at || '').slice(0, 16).replace('T', ' ') }}</span>
        <div class="spacer"></div>
        <el-button size="small" @click="startEdit">重新录入</el-button>
      </div>

      <MedSummary :result="data.result" :inherited="data.inherited" />

      <div class="doc-line" v-if="data.doc">
        结案文书：{{ data.doc.type_label }}（{{ data.doc.status_label }}）
        <el-button link type="primary" size="small" @click="togglePreview">
          {{ previewOpen ? '收起预览' : '查看全文' }}
        </el-button>
      </div>
      <div v-if="previewOpen" class="doc-preview md-body" v-html="previewHtml"></div>

      <div class="sign-bar">
        <span class="hint">签发后案件结案（不可撤销）；协议书全文可在「文书」页签导出</span>
        <el-button type="primary" :loading="signing"
                   :disabled="!data.doc || data.doc.status === 'issued'" @click="sign">
          签发出结案
        </el-button>
      </div>
    </template>

    <!-- 录入表单 -->
    <template v-else-if="canEnter">
      <div class="inherit-box">
        <div class="ib-title">继承自受理要素（受理阶段已确认，自动带入协议书）</div>
        <div class="ib-list">
          <span v-for="it in data.inherited" :key="it.from_element" class="ib-item">
            {{ it.field }}：<b>{{ it.value }}</b>
            <i v-if="!it.confirmed" class="unconfirmed">未确认</i>
          </span>
          <span v-if="!data.inherited.length" class="ib-empty">（本案暂无有值要素）</span>
        </div>
      </div>

      <el-form label-position="top" class="med-form">
        <el-form-item label="调解结果">
          <el-radio-group v-model="form.reached">
            <el-radio :value="true">达成协议（生成《调解协议书》）</el-radio>
            <el-radio :value="false">未达成（生成《调解终结书》）</el-radio>
          </el-radio-group>
        </el-form-item>

        <template v-if="form.reached">
          <div class="row3">
            <el-form-item label="协议本金（元）">
              <el-input-number v-model="form.principal_agreed" :min="0" :step="1000"
                               controls-position="right" style="width: 100%" />
            </el-form-item>
            <el-form-item label="履行方式">
              <el-input v-model="form.pay_method" placeholder="如：银行转账 / 现金" />
            </el-form-item>
            <el-form-item label="利息">
              <el-switch v-model="form.interest_waived" active-text="互不主张" inactive-text="另行约定" />
            </el-form-item>
          </div>

          <el-form-item label="分期计划（合计须等于协议本金）">
            <div class="inst-list">
              <div v-for="(it, i) in form.installments" :key="i" class="inst-row">
                <span class="inst-seq">第 {{ i + 1 }} 期</span>
                <el-date-picker v-model="it.due_date" type="date" value-format="YYYY-MM-DD"
                                placeholder="履行期限" style="width: 160px" />
                <el-input-number v-model="it.amount" :min="0" :step="1000"
                                 controls-position="right" placeholder="金额（元）" style="width: 170px" />
                <el-button link type="danger" size="small"
                           :disabled="form.installments.length <= 1"
                           @click="form.installments.splice(i, 1)">删除</el-button>
              </div>
              <el-button link type="primary" size="small" @click="addInst">+ 添加一期</el-button>
              <span class="inst-total" :class="{ bad: sumMismatch }">
                合计 {{ instTotal.toLocaleString() }} 元{{ sumMismatch ? '（与本金不一致）' : '' }}
              </span>
            </div>
          </el-form-item>

          <el-form-item label="司法确认">
            <el-checkbox v-model="form.judicial_confirmation">
              双方同意自协议生效之日起 30 日内共同向人民法院申请司法确认
            </el-checkbox>
          </el-form-item>
        </template>

        <template v-else>
          <el-form-item label="终结原因（必填）">
            <el-input v-model="form.termination_reason" type="textarea" :rows="3"
                      placeholder="如：双方在履行期限上分歧过大，未能达成一致" />
          </el-form-item>
        </template>

        <div class="form-actions">
          <span class="hint">保存即校验（分期合计 / 期限 / 金额），通过后自动生成结案文书草案</span>
          <el-button type="primary" :loading="saving" @click="save">保存并生成结案文书</el-button>
        </div>
      </el-form>
    </template>
   </template>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch } from 'vue'
import MarkdownIt from 'markdown-it'
import { fetchMediationResult, saveMediationResult, issueAgreement } from '../api/mediation.js'
import { fetchDocument } from '../api/documents.js'
import MedSummary from './MedSummary.vue'

const props = defineProps({ caseId: { type: String, required: true } })
const emit = defineEmits(['changed'])

const md = new MarkdownIt({ html: false, breaks: false, linkify: true })

const loading = ref(false)
const saving = ref(false)
const signing = ref(false)
const data = ref(null)
const editing = ref(false)
const previewOpen = ref(false)
const previewHtml = ref('')

const form = reactive({
  reached: true,
  principal_agreed: null,
  interest_waived: false,
  pay_method: '',
  installments: [{ due_date: '', amount: null }],
  judicial_confirmation: true,
  termination_reason: '',
})

const status = computed(() => data.value?.case_status || '')
const canEnter = computed(() => status.value === 'issued' && (editing.value || !data.value?.result))
const instTotal = computed(() => form.installments.reduce((s, it) => s + (Number(it.amount) || 0), 0))
const sumMismatch = computed(() => form.reached && form.principal_agreed != null
  && form.installments.length > 0 && Math.abs(instTotal.value - Number(form.principal_agreed)) > 1e-6)

async function load() {
  loading.value = true
  try {
    data.value = await fetchMediationResult(props.caseId)
    if (data.value.result && !data.value.result.reached) {
      form.reached = false
      form.termination_reason = data.value.result.settlement?.termination_reason || ''
    }
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}
watch(() => props.caseId, (id) => { if (id) { previewOpen.value = false; editing.value = false; load() } }, { immediate: true })

function addInst() {
  form.installments.push({ due_date: '', amount: null })
}

function startEdit() {
  const r = data.value?.result
  if (r?.reached) {
    const s = r.settlement || {}
    form.reached = true
    form.principal_agreed = s.principal_agreed ?? null
    form.interest_waived = !!s.interest_waived
    form.pay_method = s.pay_method || ''
    form.installments = (s.installments || []).map(it => ({ due_date: it.due_date || '', amount: it.amount ?? null }))
    if (!form.installments.length) form.installments = [{ due_date: '', amount: null }]
  }
  form.judicial_confirmation = !!r?.judicial_confirmation
  editing.value = true
}

async function save() {
  if (form.reached) {
    if (!form.principal_agreed || form.principal_agreed <= 0) {
      ElMessage.warning('请填写协议本金（大于 0）')
      return
    }
    if (form.installments.some(it => !it.due_date || it.amount == null)) {
      ElMessage.warning('每期须填写履行期限与金额')
      return
    }
    if (sumMismatch.value) {
      ElMessage.warning('分期合计与协议本金不一致，请调整（服务端也会校验）')
    }
  } else if (!form.termination_reason.trim()) {
    ElMessage.warning('未达成调解时必须填写终结原因')
    return
  }
  const settlement = form.reached ? {
    principal_agreed: form.principal_agreed,
    interest_waived: form.interest_waived,
    installments: form.installments.map((it, i) => ({ seq: i + 1, due_date: it.due_date, amount: it.amount })),
    pay_method: form.pay_method.trim(),
  } : { termination_reason: form.termination_reason.trim() }

  saving.value = true
  try {
    const r = await saveMediationResult(props.caseId, {
      reached: form.reached, settlement, judicialConfirmation: form.judicial_confirmation,
    })
    ElMessage.success(`已保存，${r.agreement_doc.title}草案已生成`)
    editing.value = false
    previewOpen.value = false
    await load()
    emit('changed')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    saving.value = false
  }
}

async function sign() {
  try {
    await ElMessageBox.confirm(
      '签发后案件结案（不可撤销）：结案文书转正式并写入审计日志。',
      '确认签发结案？', { type: 'warning', confirmButtonText: '确认签发', cancelButtonText: '再想想' })
  } catch { return }
  signing.value = true
  try {
    const r = await issueAgreement(props.caseId)
    const tip = r.judicial_confirmation_deadline
      ? `，双方可于 ${r.judicial_confirmation_deadline} 前申请司法确认`
      : ''
    ElMessage.success(`已签发结案${tip}`)
    await load()
    emit('changed')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    signing.value = false
  }
}

async function togglePreview() {
  if (previewOpen.value) {
    previewOpen.value = false
    return
  }
  if (!data.value?.doc) return
  try {
    const d = await fetchDocument(props.caseId, data.value.doc.doc_id)
    previewHtml.value = md.render(d.doc.content_md || '')
    previewOpen.value = true
  } catch (e) {
    ElMessage.error(e.message)
  }
}
</script>

<style scoped>
.med-panel { min-height: 300px; }
.closed-banner { display: flex; align-items: center; gap: 10px; padding: 10px 12px; background: #f0f9eb; border-radius: 8px; font-size: 13px; color: #3d7a2a; margin-bottom: 12px; }
.rec-head { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.rec-sub { font-size: 12px; color: #a6adb8; }
.spacer { flex: 1; }

.inherit-box { padding: 10px 12px; background: #f0f5fc; border-radius: 8px; margin-bottom: 14px; }
.ib-title { font-size: 12.5px; color: #4a5b76; font-weight: 600; margin-bottom: 6px; }
.ib-list { display: flex; flex-wrap: wrap; gap: 6px 14px; }
.ib-item { font-size: 12.5px; color: #2c3a52; }
.ib-item b { color: #16345e; }
.unconfirmed { color: #b07a1e; font-style: normal; font-size: 11px; margin-left: 4px; }
.ib-empty { font-size: 12.5px; color: #909399; }

.med-form :deep(.el-form-item) { margin-bottom: 14px; }
.med-form :deep(.el-form-item__label) { font-weight: 600; color: #1f3350; }
.row3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 14px; }
.inst-list { width: 100%; }
.inst-row { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.inst-seq { font-size: 12.5px; color: #5a6b84; width: 52px; }
.inst-total { margin-left: 12px; font-size: 12.5px; color: #67c23a; }
.inst-total.bad { color: #d9534f; }
.form-actions { display: flex; align-items: center; justify-content: flex-end; gap: 14px; margin-top: 6px; }
.hint { font-size: 12px; color: #909399; }

.doc-line { margin: 10px 0; font-size: 13px; color: #3a4a60; }
.doc-preview { max-height: 360px; overflow-y: auto; padding: 12px 16px; border: 1px solid #eef1f6; border-radius: 8px; background: #fcfdff; font-size: 13px; line-height: 1.8; }
.sign-bar { display: flex; align-items: center; justify-content: flex-end; gap: 14px; margin-top: 14px; padding-top: 12px; border-top: 1px dashed #eef1f6; }
</style>
