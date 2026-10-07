<template>
  <!-- 非管理员：菜单可见、进页即提示权限不足（后端接口同样强校验，数据拿不到） -->
  <div v-if="!isAdmin" class="log-page denied">
    <div class="denied-icon">🔒</div>
    <p class="denied-text">你没有权限，请联系管理员 3112028466@qq.com</p>
  </div>

  <div v-else class="log-page">
    <div class="toolbar">
      <el-select v-model="actionFilter" size="small" style="width: 160px" @change="onFilter">
        <el-option label="全部操作" value="" />
        <el-option v-for="(meta, key) in ACTION_META" :key="key" :label="meta.label" :value="key" />
      </el-select>
      <span class="hint">记录登录与知识库的全部操作；「删除日志」动作本身也会留痕</span>
      <div class="spacer"></div>
      <span class="total">共 <b>{{ total }}</b> 条</span>
      <el-button size="small" @click="load">刷新</el-button>
      <el-button size="small" type="danger" plain @click="onClear">清空日志</el-button>
    </div>

    <el-table :data="items" size="small" stripe v-loading="loading">
      <el-table-column label="时间" width="175">
        <template #default="{ row }"><span class="mono-text">{{ fmtTime(row.created_at) }}</span></template>
      </el-table-column>
      <el-table-column label="操作人" width="170">
        <template #default="{ row }">
          {{ row.username }} <span class="uid">{{ row.user_id }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作类型" width="120">
        <template #default="{ row }">
          <el-tag :type="meta(row.action).type" size="small" effect="light">{{ meta(row.action).label }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作对象" min-width="200" show-overflow-tooltip>
        <template #default="{ row }">{{ row.target || '—' }}</template>
      </el-table-column>
      <el-table-column label="详情" min-width="150" show-overflow-tooltip>
        <template #default="{ row }"><span class="mono-text">{{ row.detail || '—' }}</span></template>
      </el-table-column>
      <el-table-column label="来源 IP" width="130">
        <template #default="{ row }"><span class="mono-text">{{ row.ip || '—' }}</span></template>
      </el-table-column>
      <!-- 删除：仅管理员角色可进入本页，后端接口同样强校验；删除动作会再记一条 log_delete -->
      <el-table-column label="操作" width="80" fixed="right">
        <template #default="{ row }">
          <el-popconfirm title="删除这条日志？（删除动作本身会再记一条审计）" confirm-button-text="删除" cancel-button-text="取消"
                         confirm-button-type="danger" placement="left" width="250"
                         @confirm="onDelete(row)">
            <template #reference>
              <el-button link type="danger" size="small">删除</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination background layout="prev, pager, next" :total="total" :page-size="pageSize"
                     v-model:current-page="page" @current-change="load" />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { fetchLogs, deleteLog, clearLogs } from '../api/logs.js'
import { getUser } from '../api/http.js'
// ElMessage 由 unplugin-auto-import 自动注入（显式 import 会丢样式，别加）

// 权限：非 admin 只看提示、不发请求（后端 require_admin 硬校验兜底）
const isAdmin = (getUser()?.role) === 'admin'

// 操作类型 → 中文标签 + 标签颜色
const ACTION_META = {
  login:       { label: '登录',       type: 'primary' },
  kb_upload:   { label: '上传文件',   type: 'success' },
  kb_delete:   { label: '删除文件',   type: 'danger' },
  rule_update: { label: '修改规则',   type: 'warning' },
  schema_save: { label: '保存 Schema', type: 'warning' },
  prompt_save: { label: '保存提示词', type: 'warning' },
  kb_reindex:  { label: '灌库',   type: 'info' },
  log_delete:  { label: '删除日志',   type: 'danger' },
  log_clear:   { label: '清空日志',   type: 'danger' },
}

const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const actionFilter = ref('')
const loading = ref(false)

function meta(action) {
  return ACTION_META[action] || { label: action, type: 'info' }
}

function fmtTime(t) {
  // 后端为 "YYYY-MM-DD HH:mm:ss.SSS" 字符串，展示到秒
  return t ? t.slice(0, 19) : ''
}

async function load() {
  loading.value = true
  try {
    const data = await fetchLogs({ page: page.value, pageSize, action: actionFilter.value })
    items.value = data.items
    total.value = data.total
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
}

function onFilter() {
  page.value = 1
  load()
}

async function onDelete(row) {
  try {
    await deleteLog(row.id)
    ElMessage.success('已删除')
    // 删掉当前页最后一条时回退一页，避免看到空白页
    if (items.value.length === 1 && page.value > 1) page.value -= 1
    load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

// 清空全部日志：二次确认（不可逆重操作）；清空动作本身会留一条审计记录
async function onClear() {
  try {
    await ElMessageBox.confirm(
      '确定清空全部日志？该操作不可恢复；清空动作本身会留下一条记录。',
      '清空确认',
      { type: 'warning', confirmButtonText: '清空', cancelButtonText: '取消' }
    )
  } catch {
    return   // 用户取消
  }
  try {
    const r = await clearLogs()
    ElMessage.success(`已清空 ${r.cleared} 条日志`)
    page.value = 1
    load()
  } catch (e) {
    ElMessage.error(e.message)
  }
}

onMounted(() => { if (isAdmin) load() })
</script>

<style scoped>
.log-page {
  background: #fff;
  border-radius: var(--radius);
  padding: 20px 24px;
  box-shadow: var(--shadow-card);
}
.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-bottom: 12px;
  margin-bottom: 12px;
  border-bottom: 1px dashed #eef1f6;
}
.toolbar .hint { color: #909399; font-size: 12px; }
.toolbar .spacer { flex: 1; }
.toolbar .total { color: #8a97ac; font-size: 12.5px; }
.toolbar .total b {
  color: var(--primary);
  font-size: 16px;
  font-family: Consolas, "Courier New", monospace;
  margin: 0 3px;
}
/* 数字/ID/IP 等技术性内容用等宽字体，审计感更强 */
.mono-text { font-family: Consolas, "Courier New", monospace; font-size: 12.5px; color: #4a5b76; }
.uid { color: #909399; font-size: 12px; }
.pager { display: flex; justify-content: flex-end; margin-top: 14px; }

/* ===== 无权限提示 ===== */
.denied {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 420px;
  gap: 14px;
}
.denied-icon { font-size: 46px; }
.denied-text { margin: 0; color: #f56c6c; font-size: 15px; font-weight: 600; }
</style>
