<template>
  <!-- 文书签发页：待签发案件队列（documents_ready + 不予受理意见稿），点行进入文书工作台 -->
  <div class="docs-page">
    <div class="toolbar">
      <span class="total">待处理 <b>{{ cases.length }}</b> 案
        <span class="sub">待签发 {{ pendingCount }} · 意见稿 {{ cases.length - pendingCount }}</span></span>
      <span class="hint">核验通过的案件生成四产出物后进入此队列；签发受理登记表即完成受理</span>
      <el-button size="small" @click="load">刷新</el-button>
    </div>
    <el-table :data="cases" size="small" stripe v-loading="loading" @row-click="openCase"
              class="docs-table">

      <el-table-column prop="case_id" label="案号" width="140" />
      <el-table-column prop="applicant_name" label="当事人" min-width="150" />
      <el-table-column prop="dispute_type" label="纠纷类型" width="110" />
      <el-table-column label="节点" width="170">
        <template #default="{ row }">
          <el-tag size="small" :type="row.status === 'reject_suggested' ? 'danger' : 'warning'"
                  effect="light">{{ row.status_label }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="assignee_user_id" label="承办" width="90" />
      <el-table-column label="更新时间" width="140">
        <template #default="{ row }">{{ fmt(row.updated_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="110">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click.stop="openCase(row)">去签发 →</el-button>
        </template>
      </el-table-column>
    </el-table>
    <el-empty v-if="!loading && !cases.length" :image-size="90"
              description="暂无待签发案件（案件核验通过后，在文书页生成四产出物即进入本队列）" />

    <!-- 文书工作台（全屏弹窗复用案件详情 tab 的同一组件） -->
    <el-dialog v-model="panelVisible" :title="panelTitle" width="92%" top="4vh"
               destroy-on-close class="panel-dialog" append-to-body>
      <DocumentPanel v-if="currentCaseId" :case-id="currentCaseId" @changed="onChanged" />
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import DocumentPanel from '../components/DocumentPanel.vue'
import { fetchCases } from '../api/cases.js'

const emit = defineEmits(['doc-count'])

const cases = ref([])
const loading = ref(false)
const panelVisible = ref(false)
const currentCaseId = ref(null)
const currentLabel = ref('')

const pendingCount = computed(() => cases.value.filter(c => c.status === 'documents_ready').length)
const panelTitle = computed(() => currentLabel.value ? `文书工作台 · ${currentLabel.value}` : '文书工作台')

async function load() {
  loading.value = true
  try {
    // B2 已支持逗号分隔多值；page_size 上限 100，演示数据量足够
    const r = await fetchCases({ status: 'documents_ready,reject_suggested', pageSize: 100 })
    cases.value = r.items || []
    emit('doc-count', cases.value.length)   // 徽章口径 = 本页列表条数（两类待办合计）
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

function openCase(row) {
  currentCaseId.value = row.case_id
  currentLabel.value = `${row.case_id} · ${row.applicant_name}`
  panelVisible.value = true
}

// 生成/签发会改变案件状态（可能离开本队列），刷新列表与徽章
function onChanged() {
  load()
}

function fmt(t) {
  return t ? String(t).slice(5, 16).replace('T', ' ') : ''
}

onMounted(load)
</script>

<style scoped>
.docs-page { background: #fff; border-radius: var(--radius); padding: 18px 20px; box-shadow: var(--shadow-card); }
.toolbar { display: flex; align-items: center; gap: 14px; margin-bottom: 14px; }
.toolbar .total { font-size: 14px; color: #1f3350; }
.toolbar .total b { color: #2b5fad; font-size: 16px; }
.toolbar .sub { font-size: 12px; color: #909399; font-weight: 400; margin-left: 4px; }
.toolbar .hint { flex: 1; font-size: 12.5px; color: #909399; }
.docs-table :deep(.el-table__row) { cursor: pointer; }

.panel-dialog :deep(.el-dialog__body) { padding: 10px 14px; height: 78vh; }
</style>
