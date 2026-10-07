// B组 案件接口封装。开发期经 Vite proxy 转发到 8000，生产期与页面同源
import { request } from './http.js'

export async function fetchCases({ status = '', page = 1, pageSize = 20 } = {}) {
  const params = new URLSearchParams()
  if (status) params.set('status', status)
  params.set('page', String(page))
  params.set('page_size', String(pageSize))
  // request 会自动带上 Authorization 头
  const res = await request(`/cases?${params.toString()}`)
  if (!res.ok) throw new Error(`案件列表请求失败：${res.status}`)
  return res.json()
}

// B3 案件详情：案件信息 + 陈述原文 + 流转时间线 + 要素/核验摘要 + 备注
export async function fetchCaseDetail(caseId) {
  const res = await request(`/cases/${encodeURIComponent(caseId)}`)
  if (!res.ok) throw new Error(`案件详情请求失败：${res.status}`)
  return res.json()
}

// B1 新建受理：提交陈述 → 建案 → 同步 LLM 抽取要素（几秒，需 loading）
export async function createCase({ narrative, disputeType = '民间借贷', applicantName = '' }) {
  const res = await request('/cases', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      narrative,
      dispute_type: disputeType,
      applicant: applicantName ? { name: applicantName } : null,
    }),
  })
  if (!res.ok) {
    let msg = `新建受理失败：${res.status}`
    try {
      const body = await res.json()
      msg = body.error?.message || body.detail || msg
    } catch { /* 保留默认信息 */ }
    throw new Error(msg)
  }
  return res.json()
}
