// C/D 组 受理流程接口封装：要素表 + 核验报告
import { request } from './http.js'

async function errMsg(res, fallback) {
  try {
    const body = await res.json()
    return body.error?.message || body.detail || `${fallback}：${res.status}`
  } catch {
    return `${fallback}：${res.status}`
  }
}

// GET /cases/{id}/elements 要素表（含原文引句与偏移，页面②原文面板渲染依据）
export async function fetchElements(caseId) {
  const res = await request(`/cases/${encodeURIComponent(caseId)}/elements`)
  if (!res.ok) throw new Error(await errMsg(res, '要素表请求失败'))
  return res.json()
}

// PUT /cases/{id}/elements 批量确认/修正/待补（自动触发核验）
// actions: [{element_id, action, value?, reason?}]
export async function confirmElements(caseId, actions) {
  const res = await request(`/cases/${encodeURIComponent(caseId)}/elements`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ elements: actions }),
  })
  if (!res.ok) throw new Error(await errMsg(res, '要素确认失败'))
  return res.json()
}

// GET /cases/{id}/verification 最新核验报告
export async function fetchVerification(caseId) {
  const res = await request(`/cases/${encodeURIComponent(caseId)}/verification`)
  if (res.status === 404) return null   // 尚未核验
  if (!res.ok) throw new Error(await errMsg(res, '核验报告请求失败'))
  return res.json()
}

// POST /cases/{id}/elements/{element_id}/clarify 生成补充询问话术（给受理员）
export async function fetchClarify(caseId, elementId) {
  const res = await request(
    `/cases/${encodeURIComponent(caseId)}/elements/${encodeURIComponent(elementId)}/clarify`,
    { method: 'POST' })
  if (!res.ok) throw new Error(await errMsg(res, '话术生成失败'))
  return res.json()
}
