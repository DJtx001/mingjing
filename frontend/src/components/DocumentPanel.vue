<template>
  <!-- 文书工作台：左栏文件列表 + 右栏正文（带溯源锚点）+ 侧栏注解（案件详情 tab 与签发页共用） -->
  <div class="doc-panel">
    <!-- 左栏：文书列表 -->
    <div class="doc-side">
      <div class="side-head">
        <el-button v-if="generatable" class="gen-btn" type="primary" size="small"
                   :loading="generating" @click="generate(null)">
          {{ generating ? 'AI 起草中（2~5 秒）…' : (items.length ? '生成 / 补充文书' : '生成文书') }}
        </el-button>
        <div v-else-if="!items.length" class="side-tip">当前节点（{{ caseStatusLabel }}）不可生成文书</div>
      </div>
      <div class="doc-list">
        <div v-for="d in items" :key="d.doc_id" class="doc-item"
             :class="{ active: d.doc_id === currentDocId }" @click="openItem(d)">
          <div class="di-title">{{ d.type_label }}</div>
          <div class="di-meta">
            <el-tag size="small" :type="d.status === 'issued' ? 'success' : 'info'" effect="plain">
              {{ d.status_label }}
            </el-tag>
            <span v-if="d.annotation_count" class="di-count">溯源 {{ d.annotation_count }} 处</span>
          </div>
        </div>
        <el-empty v-if="!items.length && generatable" :image-size="56"
                  description="尚无文书：点上方按钮，一键生成四产出物" />
        <el-empty v-else-if="!items.length" :image-size="56" description="暂无可查看的文书" />
      </div>
    </div>

    <!-- 右栏：正文 + 溯源侧栏 -->
    <div class="doc-main" v-if="detail">
      <div class="main-head">
        <div class="mh-title">
          <span class="mh-name">{{ detail.doc.title }}</span>
          <el-tag size="small" :type="detail.doc.status === 'issued' ? 'success' : 'warning'"
                  :effect="detail.doc.status === 'issued' ? 'light' : 'plain'">
            {{ detail.doc.status_label }}
          </el-tag>
          <span v-if="detail.doc.status === 'issued'" class="mh-issued">
            {{ detail.doc.issued_by }} 签发于 {{ fmt(detail.doc.issued_at) }} · 不可撤销
          </span>
        </div>
        <div class="mh-actions">
          <el-dropdown v-if="detail.doc.status === 'draft' && generatable" @command="exportAs">
            <el-button size="small">导出 ▾</el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="md">Markdown（.md）</el-dropdown-item>
                <el-dropdown-item command="html">网页（.html）</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-button v-if="detail.doc.status === 'draft' && generatable" size="small"
                     :loading="generating" @click="generate(detail.doc.type)">重新生成</el-button>
          <el-button v-if="issuable" size="small" type="primary" @click="issue(detail.doc)">
            签发生效
          </el-button>
          <el-tag v-else-if="detail.doc.status === 'issued'" size="small" type="success" effect="dark">
            已签发
          </el-tag>
        </div>
      </div>
      <div class="main-body">
        <div class="content-scroll">
          <div v-if="detail.doc.status === 'draft'" class="watermark">草 案</div>
          <div ref="contentRef" class="doc-content md-body" v-html="rendered"
               @click="onContentClick"></div>
        </div>
        <div class="ann-side">
          <div class="ann-head">
            溯源注解<span class="ann-stats">{{ mergedAnns.length }} 处 · 覆盖 {{ detail.stats.lines }} 行正文</span>
          </div>
          <div ref="annListRef" class="ann-list">
            <div v-for="(m, i) in mergedAnns" :key="i" class="ann-item"
                 :class="{ active: i === activeAnn }" @click="focusAnn(i)">
              <span class="ann-badge" :class="m.items[0].annotation_type">
                {{ ANN_LABEL[m.items[0].annotation_type] || m.items[0].annotation_type }}
              </span>
              <div class="ann-text">
                <div v-for="(a, j) in m.items" :key="j" class="ann-one">
                  <b>{{ a.label }}</b>
                  <span v-if="a.sub_label" class="ann-sub">{{ a.sub_label }}</span>
                </div>
              </div>
              <el-button v-if="citeRefId(m)" link type="primary" size="small"
                         @click.stop="viewCitation(m)">原文 ↗</el-button>
            </div>
            <el-empty v-if="!mergedAnns.length" :image-size="48" description="本文书暂无溯源锚点" />
          </div>
        </div>
      </div>
    </div>
    <div class="doc-main empty" v-else>
      <el-empty :image-size="80"
                :description="items.length ? '从左侧选择一份文书查看' : '尚无文书可查看'" />
    </div>

    <!-- 引用原文弹窗（法条全文 / 案例四段，复用 AI 助手的引用接口） -->
    <el-dialog v-model="citeVisible" :title="citeData.title" width="640px" top="8vh" append-to-body>
      <div v-loading="citeLoading" class="cite-full">
        <div v-if="citeData.meta" class="cite-meta">{{ citeData.meta }}</div>
        <div class="md-body" v-html="citeMd"></div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import MarkdownIt from 'markdown-it'
import { fetchDocuments, fetchDocument, generateDocuments, issueDocument } from '../api/documents.js'
import { fetchCitation } from '../api/assist.js'

const props = defineProps({
  caseId: { type: String, required: true },
})
const emit = defineEmits(['changed'])

// LLM 正文只由后端生成，内容里的 <>& 已清洗；html:true 仅放行本组件注入的锚点 span
const md = new MarkdownIt({ html: true, breaks: false, linkify: true })
const citeMd = new MarkdownIt({ html: false, breaks: true, linkify: true })

const ANN_LABEL = {
  element_source: '要素原文', law: '法条', similar_case: '类案', rule: '规则依据',
}
const STATUS_CN = {
  pending_review: '人工复核', reject_suggested: '不予受理意见', draft: '草稿', extracting: '要素抽取中',
}
const ISSUABLE_STATUS = { reject_notice: 'reject_suggested' }   // 通知书在意见稿态签发；其余需待签发态

const items = ref([])
const caseStatus = ref('')
const generatable = ref(false)
const generating = ref(false)
const detail = ref(null)
const currentDocId = ref(null)
const activeAnn = ref(-1)
const contentRef = ref(null)
const annListRef = ref(null)

// ---------- 加载 ----------
async function loadList() {
  const r = await fetchDocuments(props.caseId)
  items.value = r.items || []
  caseStatus.value = r.case_status || ''
  generatable.value = !!r.generatable
}

async function openItem(d) {
  currentDocId.value = d.doc_id
  activeAnn.value = -1
  detail.value = await fetchDocument(props.caseId, d.doc_id)
  nextTick(() => { if (contentRef.value) contentRef.value.parentElement.scrollTop = 0 })
}

async function boot() {
  detail.value = null
  currentDocId.value = null
  if (!props.caseId) return
  try {
    await loadList()
    if (items.value.length) await openItem(items.value[0])
  } catch (e) {
    ElMessage.error(e.message)
  }
}
watch(() => props.caseId, boot, { immediate: true })

const caseStatusLabel = computed(() => STATUS_CN[caseStatus.value] || caseStatus.value)

// ---------- 生成 / 签发 ----------
async function generate(onlyType) {
  generating.value = true
  try {
    const r = await generateDocuments(props.caseId, onlyType ? [onlyType] : null)
    const skipped = r.skipped?.length ? `，跳过已签发 ${r.skipped.length} 份` : ''
    const msg = `已生成 ${r.generated.length} 份文书${skipped}`
    if (r.warnings?.length) ElMessage.warning(`${msg}；${r.warnings.join('；')}`)
    else ElMessage.success(msg)
    await loadList()
    const target = onlyType
      ? items.value.find(i => i.type === onlyType)
      : items.value.find(i => i.doc_id === r.generated[0]?.doc_id)
    if (target) await openItem(target)
    emit('changed', r)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    generating.value = false
  }
}

const issuable = computed(() => {
  const d = detail.value?.doc
  if (!d || d.status !== 'draft') return false
  const need = ISSUABLE_STATUS[d.type] || 'documents_ready'
  return caseStatus.value === need
})

async function issue(d) {
  const tail = d.type === 'intake_form'
    ? '签发后案件进入「已签发」节点，其余草案将一并归档。'
    : d.type === 'reject_notice'
      ? '签发后案件终结为「不予受理」，不可撤销。'
      : '案件需受理登记表签发后才进入「已签发」节点。'
  try {
    await ElMessageBox.confirm(
      `签发不可撤销：文书转为正式并写入审计日志。${tail}`,
      `确认签发「${d.type_label}」？`,
      { type: 'warning', confirmButtonText: '确认签发', cancelButtonText: '再想想' })
  } catch { return }
  try {
    const r = await issueDocument(props.caseId, d.doc_id)
    const extra = r.also_issued?.length ? `，其余 ${r.also_issued.length} 份草案一并归档` : ''
    ElMessage.success(`已签发生效${extra}`)
    await loadList()
    const cur = items.value.find(i => i.doc_id === d.doc_id)
    if (cur) await openItem(cur)
    emit('changed', r)
  } catch (e) {
    ElMessage.error(e.message)
  }
}

// ---------- 正文渲染（按锚点切片注入 span；锚点不跨行由后端不变量保证） ----------
function esc(s) {
  return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

// 同区间多注解（如"核心要素待补：A、B"）合并为一条侧栏项
const mergedAnns = computed(() => {
  const merged = []
  for (const a of (detail.value?.annotations || [])) {
    const last = merged[merged.length - 1]
    if (last && last.start === a.anchor_start && last.end === a.anchor_end) last.items.push(a)
    else merged.push({ start: a.anchor_start, end: a.anchor_end, items: [a] })
  }
  return merged
})

const rendered = computed(() => {
  const content = detail.value?.doc?.content_md || ''
  let out = ''
  let pos = 0
  mergedAnns.value.forEach((m, i) => {
    out += esc(content.slice(pos, m.start))
    out += `<span class="ann" data-ann="${i}">${esc(content.slice(m.start, m.end))}</span>`
    pos = m.end
  })
  out += esc(content.slice(pos))
  return md.render(out)
})

function onContentClick(e) {
  const el = e.target.closest('.ann')
  if (!el) return
  const i = Number(el.dataset.ann)
  activeAnn.value = i
  scrollAnnItem(i)
}

function focusAnn(i) {
  activeAnn.value = i
  const el = contentRef.value?.querySelector(`[data-ann="${i}"]`)
  if (el) {
    el.scrollIntoView({ block: 'center', behavior: 'smooth' })
    el.classList.add('flash')
    setTimeout(() => el.classList.remove('flash'), 900)
  }
}

function scrollAnnItem(i) {
  const list = annListRef.value
  const item = list?.children?.[i]
  if (item) item.scrollIntoView({ block: 'nearest' })
}

function citeRefId(m) {
  const rt = m.items[0]?.ref_type
  return (rt === 'law' || rt === 'case') ? m.items[0].ref_id : null
}

// ---------- 引用原文（法条全文 / 案例四段） ----------
const citeVisible = ref(false)
const citeLoading = ref(false)
const citeData = ref({ title: '', meta: '', content: '' })

async function viewCitation(m) {
  const refId = citeRefId(m)
  citeVisible.value = true
  citeLoading.value = true
  citeData.value = { title: m.items[0].label || '', meta: '', content: '' }
  try {
    const d = await fetchCitation(refId)
    citeData.value = {
      title: d.title,
      meta: (d.type === 'law' ? '法条' : '案例') + (d.meta ? ' · ' + d.meta : ''),
      content: d.content,
    }
  } catch (e) {
    citeData.value = { ...citeData.value, content: '加载失败：' + e.message }
  } finally {
    citeLoading.value = false
  }
}

// ---------- 导出（纯前端 Blob：草案导出带"草案"水印/标记） ----------
function exportAs(format) {
  const d = detail.value?.doc
  if (!d) return
  const isDraft = d.status === 'draft'
  const base = `${props.caseId}-${d.type_label}${isDraft ? '-草案' : ''}`
  if (format === 'md') {
    const head = `<!-- ${d.title}${isDraft ? '（草案 · 未签发，仅供内部核对）' : '（已签发）'} · ${props.caseId} -->\n\n`
    download(new Blob([head + d.content_md], { type: 'text/markdown;charset=utf-8' }), `${base}.md`)
  } else {
    const html = `<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>${base}</title>
<style>
body{max-width:840px;margin:32px auto;padding:0 24px;font-family:"Microsoft YaHei","PingFang SC",sans-serif;line-height:1.9;color:#1f3350}
h1,h2,h3{line-height:1.5}table{border-collapse:collapse;width:100%;margin:12px 0;font-size:14px}
td,th{border:1px solid #cfd8e3;padding:6px 10px;text-align:left}
blockquote{margin:10px 0;padding:8px 14px;background:#f0f5fc;border-left:3px solid #2b5fad;color:#4a5b76}
.wm{position:fixed;inset:0;display:flex;align-items:center;justify-content:center;font-size:120px;font-weight:700;letter-spacing:32px;color:rgba(43,95,173,.07);transform:rotate(-24deg);pointer-events:none}
</style></head><body>
${isDraft ? '<div class="wm">草 案</div>' : ''}${rendered.value}
</body></html>`
    download(new Blob([html], { type: 'text/html;charset=utf-8' }), `${base}.html`)
  }
  ElMessage.success(`已导出 ${base}`)
}

function download(blob, name) {
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = name
  a.click()
  URL.revokeObjectURL(a.href)
}

function fmt(t) {
  return t ? String(t).slice(5, 16).replace('T', ' ') : ''
}
</script>

<style scoped>
.doc-panel { display: flex; gap: 0; height: 100%; min-height: 460px; border: 1px solid #e4e9f2; border-radius: 10px; overflow: hidden; background: #fff; }

/* ===== 左栏 ===== */
.doc-side { width: 236px; flex: none; border-right: 1px solid #e9eef6; display: flex; flex-direction: column; background: #fafbfe; }
.side-head { padding: 10px 12px; border-bottom: 1px solid #eef2f8; }
.gen-btn { width: 100%; }
.side-tip { font-size: 12px; color: #909399; text-align: center; padding: 4px 0; }
.doc-list { flex: 1; overflow-y: auto; padding: 8px; }
.doc-item { padding: 9px 10px; border-radius: 8px; cursor: pointer; margin-bottom: 6px; border: 1px solid transparent; transition: all .15s; }
.doc-item:hover { background: #f0f5fc; }
.doc-item.active { background: #eaf1fb; border-color: #c6d8f2; }
.di-title { font-size: 13.5px; font-weight: 600; color: #1f3350; }
.di-meta { display: flex; align-items: center; gap: 8px; margin-top: 5px; }
.di-count { font-size: 11.5px; color: #7c8db5; }

/* ===== 右栏 ===== */
.doc-main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.doc-main.empty { align-items: center; justify-content: center; }
.main-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 10px 14px; border-bottom: 1px solid #eef2f8; flex-wrap: wrap; }
.mh-title { display: flex; align-items: center; gap: 8px; min-width: 0; }
.mh-name { font-size: 14.5px; font-weight: 700; color: #16345e; }
.mh-issued { font-size: 12px; color: #7c8db5; }
.mh-actions { display: flex; align-items: center; gap: 8px; }
.main-body { flex: 1; display: flex; min-height: 0; }
.content-scroll { flex: 1; overflow-y: auto; position: relative; padding: 18px 22px; }
.doc-content { font-size: 14px; color: #2c3a52; line-height: 1.85; }

/* 草案水印（45° 斜排，跟随内容滚动；导出的 HTML 同样携带） */
.watermark {
  position: absolute; top: 36%; left: 50%; transform: translate(-50%, -50%) rotate(-24deg);
  font-size: 84px; font-weight: 700; letter-spacing: 30px; color: rgba(43, 95, 173, 0.075);
  pointer-events: none; white-space: nowrap; user-select: none;
}

/* 正文锚点：可点击回链，hover 提示 */
.doc-content :deep(.ann) {
  cursor: pointer; border-bottom: 1px dashed #8fb3e0; background: rgba(90, 143, 217, 0.06);
  transition: background .2s, box-shadow .2s; border-radius: 2px;
}
.doc-content :deep(.ann:hover) { background: rgba(90, 143, 217, 0.18); }
.doc-content :deep(.ann.flash) { background: #ffe9a8; box-shadow: 0 0 0 2px #f5c94c; }

/* ===== 溯源侧栏 ===== */
.ann-side { width: 268px; flex: none; border-left: 1px solid #e9eef6; display: flex; flex-direction: column; background: #fcfdff; }
.ann-head { padding: 10px 12px; font-size: 13px; font-weight: 600; color: #1f3350; border-bottom: 1px solid #eef2f8; }
.ann-stats { display: block; font-size: 11.5px; font-weight: 400; color: #7c8db5; margin-top: 2px; }
.ann-list { flex: 1; overflow-y: auto; padding: 8px; }
.ann-item { display: flex; gap: 8px; align-items: flex-start; padding: 8px 9px; border-radius: 8px; cursor: pointer; border: 1px solid transparent; margin-bottom: 6px; }
.ann-item:hover { background: #f2f6fc; }
.ann-item.active { background: #eaf1fb; border-color: #c6d8f2; }
.ann-badge { flex: none; font-size: 11px; padding: 1px 7px; border-radius: 999px; margin-top: 1px; }
.ann-badge.element_source { background: #e8f4e8; color: #3d8b40; }
.ann-badge.law { background: #eaf1fb; color: #2b5fad; }
.ann-badge.similar_case { background: #fdf1e0; color: #b07a1e; }
.ann-badge.rule { background: #fdeaea; color: #c04545; }
.ann-text { flex: 1; min-width: 0; font-size: 12.5px; line-height: 1.6; }
.ann-one b { color: #1f3350; font-weight: 600; }
.ann-sub { color: #5a6b8c; margin-left: 6px; }
.cite-full { min-height: 120px; max-height: 60vh; overflow-y: auto; font-size: 14px; }
.cite-meta { font-size: 12.5px; color: #7c8db5; margin-bottom: 8px; }
</style>
