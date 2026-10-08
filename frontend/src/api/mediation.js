// G 组 调解结果与协议书接口封装（页面⑤ · 结案收尾）
import { request } from './http.js'

async function errMsg(res, fallback) {
  try {
    const body = await res.json()
    return body.error?.message || body.detail || `${fallback}：${res.status}`
  } catch {
    return `${fallback}：${res.status}`
  }
}

// GET /cases/{id}/mediation-result 读取（继承要素 + 已录结果 + 结案文书摘要）
export async function fetchMediationResult(caseId) {
  const res = await request(`/cases/${encodeURIComponent(caseId)}/mediation-result`)
  if (!res.ok) throw new Error(await errMsg(res, '调解结果请求失败'))
  return res.json()
}

// PUT /cases/{id}/mediation-result 录入/覆盖（即时校验 + 生成协议书/终结书草案）
export async function saveMediationResult(caseId, { reached, settlement, judicialConfirmation = false }) {
  const res = await request(`/cases/${encodeURIComponent(caseId)}/mediation-result`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reached, settlement, judicial_confirmation: judicialConfirmation }),
  })
  if (!res.ok) throw new Error(await errMsg(res, '调解结果保存失败'))
  return res.json()
}

// POST /cases/{id}/agreement/issue 签发结案（不可逆，返回司法确认 30 日期限）
export async function issueAgreement(caseId) {
  const res = await request(`/cases/${encodeURIComponent(caseId)}/agreement/issue`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
  })
  if (!res.ok) throw new Error(await errMsg(res, '签发结案失败'))
  return res.json()
}
