// J组 知识库与规则接口封装（对齐《受理Agent接口文档》V1.1 J组，页面⑨）
// 所有接口都走 http.js 的 request，自动带 Authorization 头
import { request } from './http.js'

// 法条/案例原文存 OSS、向量存 Chroma，不再走 MySQL CRUD 接口

// 提取后端错误响应里的消息（FastAPI 包装体为 {error: {code, message}}，兼容旧 {detail}）
async function errMsg(res, fallback) {
  try {
    const body = await res.json()
    return body.error?.message || body.detail || `${fallback}：${res.status}`
  } catch {
    return `${fallback}：${res.status}`
  }
}

// ---------- 核验规则 ----------
// GET /admin/rules 规则清单
export async function fetchRules() {
  const res = await request('/admin/rules')
  if (!res.ok) throw new Error(await errMsg(res, '规则列表请求失败'))
  return res.json()
}

// PUT /admin/rules 规则启停/修改。payload: {rule_id, name?, description?, enabled?}
export async function updateRule(payload) {
  const res = await request('/admin/rules', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await errMsg(res, '规则更新失败'))
  return res.json()
}

// ---------- 要素 Schema ----------
// GET /admin/schemas/{dispute_type} 读取某类纠纷的 Schema
export async function fetchSchema(disputeType) {
  const res = await request(`/admin/schemas/${encodeURIComponent(disputeType)}`)
  if (!res.ok) throw new Error(await errMsg(res, 'Schema 请求失败'))
  return res.json()
}

// PUT /admin/schemas/{dispute_type} 保存 Schema（产生新 schema_version，已有案件不受影响）
export async function saveSchema(disputeType, content) {
  const res = await request(`/admin/schemas/${encodeURIComponent(disputeType)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  })
  if (!res.ok) throw new Error(await errMsg(res, 'Schema 保存失败'))
  return res.json()
}

// ---------- 提示词 ----------
// GET /admin/prompts 四组提示词
export async function fetchPrompts() {
  const res = await request('/admin/prompts')
  if (!res.ok) throw new Error(await errMsg(res, '提示词请求失败'))
  return res.json()
}

// PUT /admin/prompts 保存某组提示词。payload: {prompt_key, content}
export async function savePrompt(payload) {
  const res = await request('/admin/prompts', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(await errMsg(res, '提示词保存失败'))
  return res.json()
}

// ---------- 索引 ----------
// POST /admin/kb/reindex 灌库（后台线程灌 vector_synced=0 的记录，幂等）
export async function reindex() {
  const res = await request('/admin/kb/reindex', { method: 'POST' })
  if (!res.ok) throw new Error(await errMsg(res, '灌库失败'))
  return res.json()
}

// GET /admin/kb/reindex/status 灌库进度 {task_id, status, total, processed, error}
export async function fetchReindexStatus() {
  const res = await request('/admin/kb/reindex/status')
  if (!res.ok) throw new Error(await errMsg(res, '查询灌库进度失败'))
  return res.json()
}

// ---------- OSS 文件管理（法条/案例原始文件 + 解析入库） ----------
// POST /admin/kb/upload?category=laws|cases 上传文件到 OSS 并解析入库
// relPath：批量导入时的相对路径（不含所选文件夹首段），如 "行政法规/xxx.md"，后端取目录段作分类
// 注意：不手动设 Content-Type，浏览器自动带 multipart/form-data; boundary=...
export async function uploadKbFile(file, category = 'laws', relPath = '') {
  const form = new FormData()
  form.append('file', file)
  const qp = new URLSearchParams({ category })
  if (relPath) qp.set('rel_path', relPath)
  const res = await request(`/admin/kb/upload?${qp}`, {
    method: 'POST',
    body: form,
  })
  if (!res.ok) throw new Error(await errMsg(res, '文件上传失败'))
  return res.json()
}

// GET /admin/kb/files?category=laws|cases 列出 OSS 文件
export async function fetchKbFiles(category = '') {
  const params = category ? `?category=${category}` : ''
  const res = await request(`/admin/kb/files${params}`)
  if (!res.ok) throw new Error(await errMsg(res, '文件列表请求失败'))
  return res.json()
}

// DELETE /admin/kb/files?key=xxx 删除 OSS 文件
export async function deleteKbFile(key) {
  const res = await request(`/admin/kb/files?key=${encodeURIComponent(key)}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(await errMsg(res, '删除文件失败'))
  return res.json()
}

// GET /admin/kb/files/content?key=xxx 在线查看文本内容
export async function fetchKbFileContent(key) {
  const res = await request(`/admin/kb/files/content?key=${encodeURIComponent(key)}`)
  if (!res.ok) throw new Error(await errMsg(res, '获取文件内容失败'))
  return res.json()
}

// GET /admin/kb/files/raw?key=xxx 下载原始字节流（PDF 等用于 blob 内嵌预览）
export async function fetchKbFileBlob(key) {
  const res = await request(`/admin/kb/files/raw?key=${encodeURIComponent(key)}`)
  if (!res.ok) throw new Error(await errMsg(res, '获取文件失败'))
  return res.blob()
}
