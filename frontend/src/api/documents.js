// F 组 文书接口封装：四产出物生成 + 签发（页面④）
import { request } from './http.js'

async function errMsg(res, fallback) {
  try {
    const body = await res.json()
    return body.error?.message || body.detail || `${fallback}：${res.status}`
  } catch {
    return `${fallback}：${res.status}`
  }
}

// GET /cases/{id}/documents 文书列表（含案件状态与可生成标记）
export async function fetchDocuments(caseId) {
  const res = await request(`/cases/${encodeURIComponent(caseId)}/documents`)
  if (!res.ok) throw new Error(await errMsg(res, '文书列表请求失败'))
  return res.json()
}

// GET /cases/{id}/documents/{doc_id} 文书详情（正文 + 溯源注解 + 覆盖率）
export async function fetchDocument(caseId, docId) {
  const res = await request(`/cases/${encodeURIComponent(caseId)}/documents/${encodeURIComponent(docId)}`)
  if (!res.ok) throw new Error(await errMsg(res, '文书详情请求失败'))
  return res.json()
}

// POST /cases/{id}/documents/generate 生成/重生成（types 缺省=按案件状态推导）
// 案件底情含 LLM 起草，耗时 2~5 秒，调用方需 loading
export async function generateDocuments(caseId, types = null) {
  const res = await request(`/cases/${encodeURIComponent(caseId)}/documents/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ types }),
  })
  if (!res.ok) throw new Error(await errMsg(res, '文书生成失败'))
  return res.json()
}

// POST /cases/{id}/documents/{doc_id}/issue 签发（不可逆，二次确认后调用）
export async function issueDocument(caseId, docId) {
  const res = await request(
    `/cases/${encodeURIComponent(caseId)}/documents/${encodeURIComponent(docId)}/issue`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
  if (!res.ok) throw new Error(await errMsg(res, '签发失败'))
  return res.json()
}
