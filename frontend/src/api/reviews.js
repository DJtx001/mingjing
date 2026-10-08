// E 组 复核接口封装（复核工作台 · 页面③）
import { request } from './http.js'

async function errMsg(res, fallback) {
  try {
    const body = await res.json()
    return body.error?.message || body.detail || `${fallback}：${res.status}`
  } catch {
    return `${fallback}：${res.status}`
  }
}

// GET /reviews/count 待裁决任务数（侧边栏徽章口径）
export async function fetchReviewCount() {
  const res = await request('/reviews/count')
  if (!res.ok) throw new Error(await errMsg(res, '复核计数请求失败'))
  return res.json()
}

// GET /reviews 复核队列（优先级 high 在前、等待时间升序）
export async function fetchReviewQueue({ status = 'pending', page = 1, pageSize = 20 } = {}) {
  const params = new URLSearchParams({ status, page: String(page), page_size: String(pageSize) })
  const res = await request(`/reviews?${params.toString()}`)
  if (!res.ok) throw new Error(await errMsg(res, '复核队列请求失败'))
  return res.json()
}

// GET /reviews/{case_id} 复核详情（底情 + 核验 + 类案参考 + 历史裁决）
export async function fetchReviewDetail(caseId) {
  const res = await request(`/reviews/${encodeURIComponent(caseId)}`)
  if (!res.ok) throw new Error(await errMsg(res, '复核详情请求失败'))
  return res.json()
}

// POST /reviews/{case_id}/decision 裁决（pass 通过 / supplement 退回补充 / reject 不予受理）
export async function decideReview(caseId, { decision, reason, questions = null }) {
  const res = await request(`/reviews/${encodeURIComponent(caseId)}/decision`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ decision, reason, questions }),
  })
  if (!res.ok) throw new Error(await errMsg(res, '裁决提交失败'))
  return res.json()
}
