<template>
  <div class="kb-page">
    <el-tabs v-model="tab" class="kb-tabs">
      <!-- ===================== Tab1 法条库（OSS 文件） ===================== -->
      <el-tab-pane label="法条" name="laws">
        <div class="toolbar">
          <el-upload :show-file-list="false" :auto-upload="false" accept=".md,.txt,.pdf,.doc,.docx"
                     :on-change="(f) => onUpload(f, 'laws')">
            <el-button type="primary" class="upload-btn">📤 导入</el-button>
          </el-upload>
          <el-button class="batch-btn" @click="openBatch('laws')">📁 批量导入</el-button>
          <span class="hint">导入后自动解析入库：法条按「第X条」切分（.md）；PDF 等仅存 OSS</span>
          <div class="spacer"></div>
          <el-input v-model="lawKw" placeholder="按文件名搜索" clearable class="search-input" />
          <el-button size="small" :type="idx.status === 'error' ? 'danger' : 'default'"
                     :loading="idxRunning" @click="onReindexClick">{{ idxLabel }}</el-button>
          <el-button v-if="isAdmin" size="small" type="danger" plain :disabled="!lawSel.length"
                     @click="batchDelete('laws')">删除选中{{ lawSel.length ? `(${lawSel.length})` : '' }}</el-button>
          <el-button v-else size="small" type="danger" plain @click="guardAdmin">删除选中</el-button>
          <el-button size="small" @click="loadLawFiles">刷新</el-button>
        </div>
        <el-table :data="lawPaged" size="small" stripe v-loading="lawLoading"
                  @selection-change="s => lawSel = s">
          <el-table-column type="selection" width="38" />
          <el-table-column prop="key" label="文件路径" min-width="280" show-overflow-tooltip>
            <template #default="{ row }"><span class="path-text">{{ row.key }}</span></template>
          </el-table-column>
          <el-table-column label="大小" width="100">
            <template #default="{ row }">{{ fmtSize(row.size) }}</template>
          </el-table-column>
          <el-table-column label="上传时间" width="170">
            <template #default="{ row }">{{ fmtTime(row.last_modified) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="140">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="onPreview(row)">查看</el-button>
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
        <el-pagination v-model:current-page="lawPage" v-model:page-size="lawPageSize"
                       :page-sizes="[50, 100, 200]" :total="lawFiltered.length"
                       layout="total, sizes, prev, pager, next" background class="kb-pager" />
        <div class="tip-text">.md 上传即解析入 MySQL 结构化表（law）；向量库由「灌库」统一灌入</div>
      </el-tab-pane>

      <!-- ===================== Tab2 案例库（OSS 文件） ===================== -->
      <el-tab-pane label="案例" name="cases">
        <div class="toolbar">
          <el-upload :show-file-list="false" :auto-upload="false" accept=".md,.txt,.pdf,.doc,.docx"
                     :on-change="(f) => onUpload(f, 'cases')">
            <el-button type="primary" class="upload-btn">📤 导入</el-button>
          </el-upload>
          <el-button class="batch-btn" @click="openBatch('cases')">📁 批量导入</el-button>
          <span class="hint">导入后自动解析入库：案例按四段切分（.md）；PDF 等仅存 OSS</span>
          <div class="spacer"></div>
          <el-input v-model="caseKw" placeholder="按文件名搜索" clearable class="search-input" />
          <el-button size="small" :type="idx.status === 'error' ? 'danger' : 'default'"
                     :loading="idxRunning" @click="onReindexClick">{{ idxLabel }}</el-button>
          <el-button v-if="isAdmin" size="small" type="danger" plain :disabled="!caseSel.length"
                     @click="batchDelete('cases')">删除选中{{ caseSel.length ? `(${caseSel.length})` : '' }}</el-button>
          <el-button v-else size="small" type="danger" plain @click="guardAdmin">删除选中</el-button>
          <el-button size="small" @click="loadCaseFiles">刷新</el-button>
        </div>
        <el-table :data="casePaged" size="small" stripe v-loading="caseLoading"
                  @selection-change="s => caseSel = s">
          <el-table-column type="selection" width="38" />
          <el-table-column prop="key" label="文件路径" min-width="280" show-overflow-tooltip>
            <template #default="{ row }"><span class="path-text">{{ row.key }}</span></template>
          </el-table-column>
          <el-table-column label="大小" width="100">
            <template #default="{ row }">{{ fmtSize(row.size) }}</template>
          </el-table-column>
          <el-table-column label="上传时间" width="170">
            <template #default="{ row }">{{ fmtTime(row.last_modified) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="140">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="onPreview(row)">查看</el-button>
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
        <el-pagination v-model:current-page="casePage" v-model:page-size="casePageSize"
                       :page-sizes="[50, 100, 200]" :total="caseFiltered.length"
                       layout="total, sizes, prev, pager, next" background class="kb-pager" />
        <div class="tip-text">.md 上传即解析入 MySQL 结构化表（case_ref，四段式）；向量库由「灌库」统一灌入</div>
      </el-tab-pane>

      <!-- ===================== Tab3 核验规则 ===================== -->
      <el-tab-pane label="规则" name="rules">
        <el-alert type="info" :closable="false" class="tip"
                  title="规则引擎不经 LLM（硬规则），停用规则会影响核验召回，请谨慎操作" />
        <el-table :data="rules" size="small" stripe v-loading="ruleLoading">
          <el-table-column prop="rule_id" label="编号" width="70"></el-table-column>
          <el-table-column prop="name" label="规则名" width="170"></el-table-column>
          <el-table-column label="级别" width="90">
            <template #default="{ row }">
              <el-tag :type="row.severity === 'block' ? 'danger' : 'warning'" size="small">
                {{ row.severity === 'block' ? '刚性' : '柔性' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="命中关键词" min-width="240" show-overflow-tooltip>
            <template #default="{ row }">
              <span class="kw-text">{{ (row.keywords || []).join('、') || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="description" label="说明" min-width="260" show-overflow-tooltip></el-table-column>
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

    <!-- 批量导入对话框（选文件夹/多选文件 → 并发上传 → 进度与失败汇总） -->
    <el-dialog v-model="batchVisible" :title="batchCategory === 'laws' ? '批量导入法条' : '批量导入案例'"
               width="560px" :close-on-click-modal="false">
      <div class="batch-pick">
        <el-button @click="folderInput.click()" :disabled="batchRunning">📁 选择文件夹</el-button>
        <el-button @click="filesInput.click()" :disabled="batchRunning">📄 选择文件（可多选）</el-button>
        <input ref="folderInput" type="file" webkitdirectory multiple hidden @change="onPickFiles">
        <input ref="filesInput" type="file" multiple hidden accept=".md,.txt" @change="onPickFiles">
      </div>
      <div v-if="batchFiles.length" class="batch-summary">
        已选 <b>{{ batchFiles.length }}</b> 个文件（目录结构将作为分类保留）
      </div>
      <template v-if="batchDone > 0">
        <el-progress :percentage="batchPct" :status="batchFail && batchPct === 100 ? 'warning' : undefined"
                     class="batch-progress" />
        <div class="batch-stat">
          完成 {{ batchDone }}/{{ batchFiles.length }} · 成功 {{ batchOk }} · 解析入库
          <b>{{ batchParsed }}</b> 条 · 失败 <span :class="{ fail: batchFail }">{{ batchFail }}</span>
        </div>
        <div v-if="batchErrors.length" class="batch-errors">
          <div v-for="e in batchErrors.slice(0, 5)" :key="e.name" class="batch-error-item">
            {{ e.name }}：{{ e.message }}
          </div>
          <div v-if="batchErrors.length > 5" class="batch-error-item">…等共 {{ batchErrors.length }} 个失败</div>
        </div>
      </template>
      <template #footer>
        <el-button @click="batchVisible = false" :disabled="batchRunning">关闭</el-button>
        <el-button type="primary" @click="startBatch"
                   :disabled="batchRunning || batchFinished || !batchFiles.length">
          {{ batchRunning ? '导入中…' : (batchFinished ? '✓ 已完成，重新选择可再次导入' : '开始导入') }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { getUser } from '../api/http.js'
import {
  fetchRules, updateRule,
  fetchSchema, saveSchema,
  fetchPrompts, savePrompt,
  uploadKbFile, fetchKbFiles, deleteKbFile,
  fetchKbFileContent, fetchKbFileBlob,
  reindex, fetchReindexStatus,
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
const lawSel = ref([]), caseSel = ref([])   // 表格勾选行（批量删除用）

// 文件名搜索 + 前端分页（千级文件一次渲染会卡）
const lawKw = ref(''), lawPage = ref(1), lawPageSize = ref(50)
const lawFiltered = computed(() => {
  const kw = lawKw.value.trim().toLowerCase()
  return kw ? lawFiles.value.filter(f => f.key.toLowerCase().includes(kw)) : lawFiles.value
})
const lawPaged = computed(() =>
  lawFiltered.value.slice((lawPage.value - 1) * lawPageSize.value, lawPage.value * lawPageSize.value))
watch([lawKw, lawPageSize], () => { lawPage.value = 1 })

const caseKw = ref(''), casePage = ref(1), casePageSize = ref(50)
const caseFiltered = computed(() => {
  const kw = caseKw.value.trim().toLowerCase()
  return kw ? caseFiles.value.filter(f => f.key.toLowerCase().includes(kw)) : caseFiles.value
})
const casePaged = computed(() =>
  caseFiltered.value.slice((casePage.value - 1) * casePageSize.value, casePage.value * casePageSize.value))
watch([caseKw, casePageSize], () => { casePage.value = 1 })

async function onUpload(uploadFile, category) {
  try {
    const r = await uploadKbFile(uploadFile.raw, category)
    if (r.note) ElMessage.warning(`${r.filename} 已存 OSS，但${r.note}`)
    else ElMessage.success(`已上传 ${r.filename}（${fmtSize(r.size)}），解析入库 ${r.parsed} 条`)
    category === 'laws' ? loadLawFiles() : loadCaseFiles()
  } catch (e) { ElMessage.error(e.message) }
}

// ---------- 灌库（把 vector_synced=0 的记录灌入 Chroma，后台任务轮询进度） ----------
const idx = ref({ status: 'idle', total: 0, processed: 0, error: null })
let idxTimer = null

const idxRunning = computed(() => idx.value.status === 'running')
const idxLabel = computed(() => {
  if (idx.value.status === 'running') return `⏳ 灌库中 ${idx.value.processed}/${idx.value.total}`
  if (idx.value.status === 'error') return '⚠️ 灌库失败'
  return '🔄 灌库'
})

async function doReindex(silent = false) {
  try {
    await reindex()
    if (silent) ElMessage.info('已在后台灌入向量库，进度见「灌库」按钮')
    else ElMessage.success('灌库任务已开始')
    pollIdx()
  } catch (e) { if (!silent) ElMessage.error(e.message) }
}

async function onReindexClick() {
  if (!guardAdmin()) return
  try {
    await ElMessageBox.confirm(
      '把待同步的法条/案例向量化写入 Chroma（后台执行，可随时离开页面）。',
      '灌库',
      { type: 'info', confirmButtonText: '开始', cancelButtonText: '取消' }
    )
  } catch { return }
  doReindex()
}

// 轮询灌库进度：running 时每 2s 查一次，结束时刷新并提示
async function pollIdx() {
  clearInterval(idxTimer)
  try { idx.value = await fetchReindexStatus() } catch { /* 后端未起时静默 */ }
  if (idx.value.status !== 'running') { finishIdx(); return }
  idxTimer = setInterval(async () => {
    try { idx.value = await fetchReindexStatus() } catch { return }
    if (idx.value.status !== 'running') { clearInterval(idxTimer); finishIdx() }
  }, 2000)
}

function finishIdx() {
  if (idx.value.status === 'done') {
    const sk = idx.value.skipped ? `，跳过 ${idx.value.skipped} 条（无法向量化）` : ''
    ElMessage.success(`灌库完成，共 ${idx.value.total} 条${sk}`)
  } else if (idx.value.status === 'error') ElMessage.error(`灌库失败：${idx.value.error}`)
}

onUnmounted(() => clearInterval(idxTimer))

// ---------- 批量导入（法条/案例共用，弹窗内选文件夹或多选文件，5 路并发上传） ----------
const batchVisible = ref(false)
const batchCategory = ref('laws')
const batchFiles = ref([])        // [{file, relPath}]，relPath 已去掉所选文件夹首段
const batchRunning = ref(false)
const batchFinished = ref(false)  // 本批已导完：禁用「开始导入」防重复导入；重选文件后复位
const batchDone = ref(0), batchOk = ref(0), batchParsed = ref(0), batchFail = ref(0)
const batchErrors = ref([])       // [{name, message}]
const folderInput = ref(null), filesInput = ref(null)

const batchPct = computed(() =>
  batchFiles.value.length ? Math.round((batchDone.value / batchFiles.value.length) * 100) : 0)

function openBatch(category) {
  batchCategory.value = category
  batchFiles.value = []
  batchDone.value = batchOk.value = batchParsed.value = batchFail.value = 0
  batchErrors.value = []
  batchRunning.value = false
  batchVisible.value = true
}

function onPickFiles(e) {
  const picked = [...e.target.files]
  // webkitRelativePath 含所选文件夹名（如 laws/行政法规/x.md），去掉首段再传给后端
  batchFiles.value = picked.map(f => {
    const rel = (f.webkitRelativePath || f.name).split('/').slice(1).join('/')
    return { file: f, relPath: rel || f.name }
  })
  batchDone.value = batchOk.value = batchParsed.value = batchFail.value = 0
  batchErrors.value = []
  batchFinished.value = false
  e.target.value = ''   // 清空以便重复选择同一目录
}

async function startBatch() {
  batchRunning.value = true
  let idx = 0
  const CONCURRENCY = 5
  const workers = Array.from({ length: CONCURRENCY }, async () => {
    while (idx < batchFiles.value.length) {
      const item = batchFiles.value[idx++]
      try {
        const r = await uploadKbFile(item.file, batchCategory.value, item.relPath)
        if (r.note) throw new Error(r.note)   // 后端解析失败（文件已存 OSS）
        batchOk.value++
        batchParsed.value += r.parsed || 0
      } catch (e) {
        batchFail.value++
        batchErrors.value.push({ name: item.relPath, message: e.message })
      } finally {
        batchDone.value++
      }
    }
  })
  await Promise.all(workers)
  batchRunning.value = false
  batchFinished.value = true
  batchCategory.value === 'laws' ? loadLawFiles() : loadCaseFiles()
  // 导完自动灌库（导完即用）：reindex 幂等，只处理 vector_synced=0；普通用户无灌库权限，跳过
  if (batchParsed.value > 0 && isAdmin && !idxRunning.value) {
    doReindex(true)
  }
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

// 批量删除：3 路并发调单删接口（后端会级联清理 MySQL 结构化数据与 Chroma 向量）
async function batchDelete(category) {
  const sel = (category === 'laws' ? lawSel : caseSel).value
  if (!sel.length) return
  try {
    await ElMessageBox.confirm(
      `确定删除选中的 ${sel.length} 个文件？对应的结构化数据与向量库内容将一并清理。`,
      '批量删除',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch { return }
  const fails = []
  let i = 0
  const workers = Array.from({ length: 3 }, async () => {
    while (i < sel.length) {
      const row = sel[i++]
      try { await deleteKbFile(row.key) } catch (e) { fails.push(`${row.key}：${e.message}`) }
    }
  })
  await Promise.all(workers)
  if (fails.length) ElMessage.error(`${sel.length - fails.length} 个成功，${fails.length} 个失败：${fails[0]}`)
  else ElMessage.success(`已删除 ${sel.length} 个文件`)
  category === 'laws' ? loadLawFiles() : loadCaseFiles()
}

// 入库已随上传自动完成（.md 解析入 MySQL），无需单独操作


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

onMounted(() => { loadLawFiles(); loadCaseFiles(); loadRules(); loadSchema(); loadPrompts(); pollIdx() })
</script>

<style scoped>
.kb-page { background: #fff; border-radius: var(--radius); padding: 20px 24px; box-shadow: var(--shadow-card); font-size: 14px; }
.kb-tabs :deep(.el-tabs__header) { margin-bottom: 18px; }
.kb-tabs :deep(.el-tabs__item) { font-size: 15px; letter-spacing: 0.3px; }
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
/* 批量导入按钮与主按钮同高同圆角，弱化视觉（plain 风格） */
.batch-btn {
  height: 40px;
  padding: 0 20px;
  font-size: 14px;
  font-weight: 600;
  border-radius: 10px;
}
/* 批量导入弹窗 */
.batch-pick { display: flex; gap: 10px; }
.batch-summary { margin-top: 12px; color: #3a4a60; font-size: 13px; }
.batch-progress { margin-top: 14px; }
.batch-stat { margin-top: 8px; color: #3a4a60; font-size: 13px; }
.batch-stat .fail { color: #d93026; font-weight: 600; }
.batch-errors {
  margin-top: 10px; padding: 8px 12px;
  background: #fdf2f1; border-radius: 6px;
  max-height: 140px; overflow-y: auto;
}
.batch-error-item { color: #b42318; font-size: 13px; line-height: 1.8; }
.toolbar .spacer { flex: 1; }
.toolbar .ver { color: #909399; font-size: 13px; }
.toolbar .hint { color: #909399; font-size: 13px; }
/* 搜索框：默认尺寸（32px 高）+ 加宽，与表格字号匹配 */
.search-input { width: 260px; }
.kw-text { font-size: 12.5px; color: #5a6b84; }
.kb-pager { margin-top: 14px; justify-content: flex-end; }
.kb-pager :deep(.el-pagination__total),
.kb-pager :deep(.el-pagination__sizes) { font-size: 13px; }
.tip { margin-bottom: 12px; }
.tip-text { margin-top: 8px; color: #909399; font-size: 13px; }
.path-text { font-family: Consolas, "Courier New", monospace; font-size: 13.5px; color: #3a4a60; }
/* 表格正文整体放大一档（原 small 字号偏小） */
.kb-page :deep(.el-table .cell) { font-size: 13.5px; line-height: 1.7; }
.kb-page :deep(.el-button--small) { font-size: 13px; }
.mono :deep(.el-textarea__inner) {
  font-family: Consolas, "Courier New", monospace;
  font-size: 13.5px;
  line-height: 1.7;
  padding: 12px 14px;
  border-radius: 10px;
  background: #fafbfd;
}
.preview-body { min-height: 300px; height: 70vh; overflow-y: auto; }
.preview-text { white-space: pre-wrap; word-break: break-all; font-family: Consolas, monospace; font-size: 13px; line-height: 1.6; margin: 0; }
.preview-pdf { width: 100%; height: 70vh; border: none; }
</style>
