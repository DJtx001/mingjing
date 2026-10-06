<template>
  <div class="kb-page">
    <el-tabs v-model="tab" class="kb-tabs">
      <!-- ===================== Tab1 法条库（OSS 文件） ===================== -->
      <el-tab-pane label="法条" name="laws">
        <div class="toolbar">
          <el-upload :show-file-list="false" :auto-upload="false" accept=".md,.txt,.pdf,.doc,.docx"
                     :on-change="(f) => onUpload(f, 'laws')">
            <el-button type="primary" class="upload-btn">📤 上传法条文件</el-button>
          </el-upload>
          <span class="hint">支持 .md / .txt / .pdf / .doc / .docx，上传到 OSS laws/ 目录</span>
          <div class="spacer"></div>
          <el-button size="small" @click="loadLawFiles">刷新</el-button>
        </div>
        <el-table :data="lawFiles" size="small" stripe v-loading="lawLoading">
          <el-table-column prop="key" label="文件路径" min-width="280" show-overflow-tooltip>
            <template #default="{ row }"><span class="path-text">{{ row.key }}</span></template>
          </el-table-column>
          <el-table-column label="大小" width="100">
            <template #default="{ row }">{{ fmtSize(row.size) }}</template>
          </el-table-column>
          <el-table-column label="上传时间" width="170">
            <template #default="{ row }">{{ fmtTime(row.last_modified) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="180">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="onPreview(row)">查看</el-button>
              <el-button link type="primary" size="small" @click="onSyncLaw(row)">入库</el-button>
              <!-- 非 admin 渲染裸按钮：点击直接弹权限提示，不经过 popconfirm，确保必弹 -->
              <el-popconfirm v-if="isAdmin" title="确定删除该文件？" confirm-button-text="删除" cancel-button-text="取消"
                             confirm-button-type="danger" placement="left" width="190"
                             @confirm="doDelete(row, 'laws')">
                <template #reference>
                  <el-button link type="danger" size="small">删除</el-button>
                </template>
              </el-popconfirm>
              <el-button v-else link type="danger" size="small" @click="guardAdmin">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="tip-text">文件存于 OSS，点击「入库」后解析并写入向量库（后续实现）</div>
      </el-tab-pane>

      <!-- ===================== Tab2 案例库（OSS 文件） ===================== -->
      <el-tab-pane label="案例" name="cases">
        <div class="toolbar">
          <el-upload :show-file-list="false" :auto-upload="false" accept=".md,.txt,.pdf,.doc,.docx"
                     :on-change="(f) => onUpload(f, 'cases')">
            <el-button type="primary" class="upload-btn">📤 上传案例文件</el-button>
          </el-upload>
          <span class="hint">支持 .md / .txt / .pdf / .doc / .docx，上传到 OSS cases/ 目录</span>
          <div class="spacer"></div>
          <el-button size="small" @click="loadCaseFiles">刷新</el-button>
        </div>
        <el-table :data="caseFiles" size="small" stripe v-loading="caseLoading">
          <el-table-column prop="key" label="文件路径" min-width="280" show-overflow-tooltip>
            <template #default="{ row }"><span class="path-text">{{ row.key }}</span></template>
          </el-table-column>
          <el-table-column label="大小" width="100">
            <template #default="{ row }">{{ fmtSize(row.size) }}</template>
          </el-table-column>
          <el-table-column label="上传时间" width="170">
            <template #default="{ row }">{{ fmtTime(row.last_modified) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="180">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="onPreview(row)">查看</el-button>
              <el-button link type="primary" size="small" @click="onSyncCase(row)">入库</el-button>
              <!-- 非 admin 渲染裸按钮：点击直接弹权限提示，不经过 popconfirm，确保必弹 -->
              <el-popconfirm v-if="isAdmin" title="确定删除该文件？" confirm-button-text="删除" cancel-button-text="取消"
                             confirm-button-type="danger" placement="left" width="190"
                             @confirm="doDelete(row, 'cases')">
                <template #reference>
                  <el-button link type="danger" size="small">删除</el-button>
                </template>
              </el-popconfirm>
              <el-button v-else link type="danger" size="small" @click="guardAdmin">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="tip-text">文件存于 OSS，点击「入库」后做四段式校验并写入向量库（后续实现）</div>
      </el-tab-pane>

      <!-- ===================== Tab3 核验规则 ===================== -->
      <el-tab-pane label="规则" name="rules">
        <el-alert type="info" :closable="false" class="tip"
                  title="规则引擎不经 LLM（硬规则），停用规则会影响核验召回，请谨慎操作" />
        <el-table :data="rules" size="small" stripe v-loading="ruleLoading">
          <el-table-column prop="rule_id" label="编号" width="80"></el-table-column>
          <el-table-column prop="name" label="规则名" width="180"></el-table-column>
          <el-table-column prop="description" label="说明" min-width="320" show-overflow-tooltip></el-table-column>
          <el-table-column label="启用" width="100">
            <template #default="{ row }">
              <!-- 停用前二次确认（before-change 返回 Promise）；启用直接生效。API 统一在 change 里调 -->
              <el-switch v-model="row.enabled" :before-change="() => beforeSwitchChange(row)"
                         @change="onSwitchChange(row)" />
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- ===================== Tab4 要素 Schema ===================== -->
      <el-tab-pane label="Schema" name="schemas">
        <div class="toolbar">
          <el-select v-model="schemaType" size="small" style="width: 200px" @change="loadSchema">
            <el-option v-for="t in schemaTypes" :key="t" :label="t" :value="t" />
          </el-select>
          <div class="spacer"></div>
          <span class="ver" v-if="schemaVersion">当前版本 v{{ schemaVersion }}</span>
          <el-button size="small" type="primary" @click="onSaveSchema">保存（生成新版本）</el-button>
        </div>
        <el-input v-model="schemaText" type="textarea" :rows="18" class="mono"
                  placeholder='[{"name":"借款金额","core":true,"type":"amount","hint":"…"}]' />
      </el-tab-pane>

      <!-- ===================== Tab5 提示词 ===================== -->
      <el-tab-pane label="提示词" name="prompts">
        <div class="toolbar">
          <el-select v-model="promptKey" size="small" style="width: 200px" @change="loadPrompt">
            <el-option label="要素抽取" value="extract" />
            <el-option label="核验判断" value="verify" />
            <el-option label="类案检索" value="retrieve" />
            <el-option label="助手问答" value="assist" />
          </el-select>
          <div class="spacer"></div>
          <el-button size="small" type="primary" @click="onSavePrompt">保存</el-button>
        </div>
        <el-input v-model="promptText" type="textarea" :rows="18" class="mono" />
      </el-tab-pane>
    </el-tabs>

    <!-- 文件内容预览对话框 -->
    <el-dialog v-model="previewVisible" :title="previewKey" width="70%" top="5vh" destroy-on-close
               @closed="onPreviewClosed">
      <div v-loading="previewLoading" class="preview-body">
        <!-- PDF：浏览器内置阅读器 -->
        <iframe v-if="previewType === 'pdf'" :src="previewUrl" class="preview-pdf"></iframe>
        <!-- 文本 / Markdown -->
        <pre v-else-if="previewType === 'text'" class="preview-text">{{ previewContent }}</pre>
        <!-- 不支持在线预览的类型（doc/docx 等） -->
        <el-empty v-else-if="previewType === 'unsupported'" :description="`该格式暂不支持在线预览`">
          <el-button type="primary" size="small" @click="onDownload">下载文件</el-button>
        </el-empty>
        <!-- 加载失败 -->
        <el-empty v-else-if="previewType === 'error'" :description="previewContent" />
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getUser } from '../api/http.js'
import {
  fetchRules, updateRule,
  fetchSchema, saveSchema,
  fetchPrompts, savePrompt,
  uploadKbFile, fetchKbFiles, deleteKbFile,
  fetchKbFileContent, fetchKbFileBlob,
} from '../api/kb.js'

const tab = ref('laws')

// 权限：删除文件 / 保存 Schema / 保存提示词 仅 admin（后端 require_admin 强校验）；
// 规则启停对所有人开放（后端 get_current_user 校验）。这里只是交互层拦截。
const isAdmin = (getUser()?.role) === 'admin'

function guardAdmin() {
  if (isAdmin) return true
  ElMessage.error('你没有权限，请联系管理员 3112028466@qq.com')
  return false
}

// ---------- OSS 文件（法条/案例共用） ----------
const lawFiles = ref([]), lawLoading = ref(false)
const caseFiles = ref([]), caseLoading = ref(false)

async function onUpload(uploadFile, category) {
  try {
    const r = await uploadKbFile(uploadFile.raw, category)
    ElMessage.success(`已上传 ${r.filename}（${fmtSize(r.size)}）`)
    category === 'laws' ? loadLawFiles() : loadCaseFiles()
  } catch (e) { ElMessage.error(e.message) }
}

async function loadLawFiles() {
  lawLoading.value = true
  try { lawFiles.value = (await fetchKbFiles('laws')).items } finally { lawLoading.value = false }
}

async function loadCaseFiles() {
  caseLoading.value = true
  try { caseFiles.value = (await fetchKbFiles('cases')).items } finally { caseLoading.value = false }
}

// 气泡确认（el-popconfirm）回调：真正执行删除
async function doDelete(row, category) {
  try {
    await deleteKbFile(row.key)
    ElMessage.success('已删除')
    category === 'laws' ? loadLawFiles() : loadCaseFiles()
  } catch (e) { ElMessage.error(e.message) }
}

// 入库：后续实现（从 OSS 读取 → 解析 → 写入向量库 Chroma）
function onSyncLaw(row) { ElMessage.info(`「入库」功能后续实现：${row.key}`) }
function onSyncCase(row) { ElMessage.info(`「入库」功能后续实现：${row.key}`) }

// ---------- 在线预览 ----------
// previewType: pdf（iframe 内嵌）/ text（文本）/ unsupported（仅可下载）/ error
const previewVisible = ref(false), previewKey = ref(''), previewContent = ref('')
const previewLoading = ref(false), previewType = ref(''), previewUrl = ref('')
let previewBlobUrl = ''

function extOf(key) {
  const m = key.toLowerCase().match(/\.[a-z0-9]+$/)
  return m ? m[0] : ''
}

async function onPreview(row) {
  previewKey.value = row.key
  previewContent.value = ''
  previewUrl.value = ''
  previewType.value = ''
  previewVisible.value = true
  previewLoading.value = true
  const ext = extOf(row.key)
  try {
    if (ext === '.pdf') {
      // PDF：拉成 blob 再交给浏览器内置阅读器（iframe 无法带鉴权头）
      const blob = await fetchKbFileBlob(row.key)
      previewBlobUrl = URL.createObjectURL(blob)
      previewUrl.value = previewBlobUrl
      previewType.value = 'pdf'
    } else if (ext === '.md' || ext === '.txt') {
      const data = await fetchKbFileContent(row.key)
      previewContent.value = data.content
      previewType.value = 'text'
    } else {
      // doc/docx 等：不支持内嵌预览，仅提供下载
      previewType.value = 'unsupported'
    }
  } catch (e) {
    previewContent.value = `加载失败：${e.message}`
    previewType.value = 'error'
  } finally {
    previewLoading.value = false
  }
}

// 下载当前预览文件（blob 已带鉴权请求）
async function onDownload() {
  try {
    const blob = await fetchKbFileBlob(previewKey.value)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = previewKey.value.split('/').pop() || 'download'
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) { ElMessage.error(e.message) }
}

// 对话框关闭后释放 blob，避免内存泄漏
function onPreviewClosed() {
  if (previewBlobUrl) {
    URL.revokeObjectURL(previewBlobUrl)
    previewBlobUrl = ''
  }
  previewUrl.value = ''
  previewType.value = ''
}

// ---------- 工具函数 ----------
function fmtSize(bytes) {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}

function fmtTime(ts) {
  return new Date(ts * 1000).toLocaleString('zh-CN')
}

// ---------- 规则 ----------
const rules = ref([]), ruleLoading = ref(false)

async function loadRules() {
  ruleLoading.value = true
  try { rules.value = (await fetchRules()).items } finally { ruleLoading.value = false }
}

// 停用前二次确认（即将从开→关）；启用（关→开）直接放行
// 返回 Promise<boolean>：true 允许切换，false 弹回
function beforeSwitchChange(row) {
  if (!row.enabled) return true
  return ElMessageBox.confirm(
    '停用该规则会影响核验召回，确定停用？',
    '停用确认',
    { type: 'warning', confirmButtonText: '停用', cancelButtonText: '取消' }
  ).then(() => true).catch(() => false)
}

// 开关切换完成后统一调 API（启用/停用都走这里）；失败回滚开关
async function onSwitchChange(row) {
  try {
    await updateRule({ rule_id: row.rule_id, enabled: row.enabled })
    ElMessage.success(row.enabled ? '已启用' : '已停用')
  } catch (e) {
    row.enabled = !row.enabled
    ElMessage.error(e.message)
  }
}

// ---------- Schema ----------
const schemaTypes = ['民间借贷', '物业纠纷', '婚姻家庭', '合同纠纷', '侵权责任']
const schemaType = ref('民间借贷'), schemaText = ref(''), schemaVersion = ref(0)

async function loadSchema() {
  const data = await fetchSchema(schemaType.value)
  schemaText.value = JSON.stringify(data.content, null, 2)
  schemaVersion.value = data.schema_version
}

async function onSaveSchema() {
  if (!guardAdmin()) return
  let content
  try { content = JSON.parse(schemaText.value) } catch { ElMessage.error('JSON 格式错误'); return }
  const r = await saveSchema(schemaType.value, content)
  schemaVersion.value = r.schema_version
  ElMessage.success(`已保存，新版本 v${r.schema_version}`)
}

// ---------- 提示词 ----------
const promptKey = ref('extract'), promptText = ref('')
const promptsCache = ref({})

async function loadPrompts() {
  const data = await fetchPrompts()
  promptsCache.value = data.items
  loadPrompt()
}

function loadPrompt() { promptText.value = promptsCache.value[promptKey.value] || '' }

async function onSavePrompt() {
  if (!guardAdmin()) return
  await savePrompt({ prompt_key: promptKey.value, content: promptText.value })
  promptsCache.value[promptKey.value] = promptText.value
  ElMessage.success('已保存')
}

onMounted(() => { loadLawFiles(); loadCaseFiles(); loadRules(); loadSchema(); loadPrompts() })
</script>

<style scoped>
.kb-page { background: #fff; border-radius: var(--radius); padding: 20px 24px; box-shadow: var(--shadow-card); }
.kb-tabs :deep(.el-tabs__header) { margin-bottom: 18px; }
.kb-tabs :deep(.el-tabs__item) { font-size: 14px; letter-spacing: 0.3px; }
.toolbar {
  display: flex; align-items: center; gap: 8px;
  padding-bottom: 12px; margin-bottom: 12px;
  border-bottom: 1px dashed #eef1f6;
}
/* 上传主操作按钮：放大 + 品牌渐变 + 投影，与全站主按钮风格一致 */
.upload-btn {
  height: 40px;
  padding: 0 24px;
  font-size: 14px;
  font-weight: 600;
  border-radius: 10px;
  border: none;
  background-image: linear-gradient(135deg, #2b5fad 0%, #4a80d4 100%);
  box-shadow: 0 4px 14px rgba(43, 95, 173, 0.32);
  transition: all 0.2s;
}
.upload-btn:hover {
  box-shadow: 0 6px 18px rgba(43, 95, 173, 0.45);
  transform: translateY(-1px);
}
.toolbar .spacer { flex: 1; }
.toolbar .ver { color: #909399; font-size: 12px; }
.toolbar .hint { color: #909399; font-size: 12px; }
.tip { margin-bottom: 12px; }
.tip-text { margin-top: 8px; color: #909399; font-size: 12px; }
.path-text { font-family: Consolas, "Courier New", monospace; font-size: 12.5px; color: #3a4a60; }
.mono :deep(.el-textarea__inner) {
  font-family: Consolas, "Courier New", monospace;
  font-size: 12.5px;
  line-height: 1.7;
  padding: 12px 14px;
  border-radius: 10px;
  background: #fafbfd;
}
.preview-body { min-height: 300px; height: 70vh; overflow-y: auto; }
.preview-text { white-space: pre-wrap; word-break: break-all; font-family: Consolas, monospace; font-size: 13px; line-height: 1.6; margin: 0; }
.preview-pdf { width: 100%; height: 70vh; border: none; }
</style>
