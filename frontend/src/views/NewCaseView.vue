<template>
  <div class="newcase-page">
    <div class="form-card">
      <div class="form-tip">
        💡 录入当事人陈述后提交，系统将<b>即时调用大模型抽取要素</b>（带原文引句），
        随后进入要素确认与核验分流。
      </div>
      <el-form label-position="top" class="form">
        <div class="row2">
          <el-form-item label="纠纷类型">
            <el-select v-model="disputeType" style="width: 100%">
              <el-option label="民间借贷" value="民间借贷" />
              <el-option label="物业服务" value="物业服务" />
              <el-option label="侵权赔偿" value="侵权赔偿" />
              <el-option label="婚姻家庭" value="婚姻家庭" />
            </el-select>
          </el-form-item>
          <el-form-item label="当事人（申请人）">
            <el-input v-model="applicantName" placeholder="如：张某（可留空）" />
          </el-form-item>
        </div>
        <el-form-item label="当事人陈述（原文录入）">
          <el-input
            v-model="narrative"
            type="textarea"
            :rows="10"
            maxlength="20000"
            show-word-limit
            placeholder="将当事人的陈述如实录入，例如：2026年3月，同乡王某以资金周转为由向我借款3万元，约定6月底前归还……（不少于 20 字）"
          />
        </el-form-item>
        <div class="actions">
          <span class="hint">提交后 AI 抽取约需 3~8 秒，请勿关闭页面</span>
          <el-button type="primary" class="submit-btn" :loading="submitting" @click="submit">
            {{ submitting ? 'AI 正在抽取要素…' : '提交并抽取要素' }}
          </el-button>
        </div>
      </el-form>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { createCase } from '../api/cases.js'

const emit = defineEmits(['created'])

const disputeType = ref('民间借贷')
const applicantName = ref('')
const narrative = ref('')
const submitting = ref(false)

async function submit() {
  if (narrative.value.trim().length < 20) {
    ElMessage.warning('陈述过短：请录入不少于 20 字的当事人陈述')
    return
  }
  submitting.value = true
  try {
    const r = await createCase({
      narrative: narrative.value.trim(),
      disputeType: disputeType.value,
      applicantName: applicantName.value.trim(),
    })
    ElMessage.success(`案件 ${r.case_id} 已创建，抽取到 ${r.elements_count} 项要素`)
    narrative.value = ''
    applicantName.value = ''
    emit('created', r.case_id)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.newcase-page { background: #fff; border-radius: var(--radius); padding: 20px 24px; box-shadow: var(--shadow-card); }
.form-card { max-width: 860px; }
.form-tip {
  padding: 10px 14px; margin-bottom: 18px; border-radius: 8px;
  background: #f0f5fc; color: #4a5b76; font-size: 13px; line-height: 1.7;
}
.form-tip b { color: #2b5fad; }
.row2 { display: grid; grid-template-columns: 220px 1fr; gap: 16px; }
.form :deep(.el-form-item__label) { font-weight: 600; color: #1f3350; }
.form :deep(.el-textarea__inner) { font-size: 14px; line-height: 1.8; padding: 12px 14px; }
.actions { display: flex; align-items: center; gap: 16px; }
.actions .hint { color: #909399; font-size: 12.5px; }
.submit-btn {
  height: 42px; padding: 0 28px; font-size: 14.5px; font-weight: 600; border-radius: 10px;
  border: none; background-image: linear-gradient(135deg, #2b5fad 0%, #4a80d4 100%);
  box-shadow: 0 4px 14px rgba(43, 95, 173, 0.32);
}
.actions { justify-content: flex-end; }
</style>
