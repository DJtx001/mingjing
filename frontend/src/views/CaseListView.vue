<template>
  <div class="card">
    <el-tabs v-model="tab" @tab-change="load">
      <el-tab-pane :label="'全部 ' + counts.all" name="all"></el-tab-pane>
      <el-tab-pane :label="'草稿 ' + counts.draft" name="draft"></el-tab-pane>
      <el-tab-pane :label="'要素确认中 ' + counts.awaiting_confirmation" name="awaiting_confirmation"></el-tab-pane>
      <el-tab-pane :label="'待复核 ' + counts.pending_review" name="pending_review"></el-tab-pane>
      <el-tab-pane :label="'待签发 ' + counts.documents_ready" name="documents_ready"></el-tab-pane>
      <el-tab-pane :label="'已结案 ' + counts.completed" name="completed"></el-tab-pane>
    </el-tabs>
    <el-table :data="cases" size="small" stripe v-loading="loading">
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
        <template #default="{ row }">{{ row.updated_at.slice(5, 16).replace('T', ' ') }}</template>
      </el-table-column>
      <el-table-column label="操作" width="110">
        <template #default="{ row }">
          <el-button v-if="row.status === 'decline_pending'" type="danger" size="small">人工确认</el-button>
          <el-button v-else-if="row.status === 'completed'" link type="primary" size="small">查看档案</el-button>
          <el-button v-else link type="primary" size="small">继续处理</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { fetchCases } from '../api/cases.js'

// 各状态计数，供侧边栏徽标使用，通过 emit 上报给 App
const emit = defineEmits(['counts'])

const loading = ref(false)
const cases = ref([])
const tab = ref('all')
const counts = ref({
  all: 0, draft: 0, awaiting_confirmation: 0,
  pending_review: 0, documents_ready: 0, completed: 0,
})

async function load() {
  loading.value = true
  try {
    const status = tab.value === 'all' ? '' : tab.value
    const data = await fetchCases({ status, pageSize: 20 })
    cases.value = data.items
  } finally {
    loading.value = false
  }
}

async function loadCounts() {
  const data = await fetchCases({ pageSize: 100 })
  const all = data.items
  counts.value.all = all.length
  for (const c of all) {
    if (counts.value[c.status] !== undefined) counts.value[c.status]++
  }
  emit('counts', { ...counts.value })
}

onMounted(() => {
  load()
  loadCounts()
})
</script>
