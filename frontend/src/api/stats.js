// I组 统计接口封装（仅管理员，后端 require_admin 兜底）
import { request } from './http.js'

// GET /stats/kb 知识库存量：条数 / 灌库覆盖 / 法律部门分布
export async function fetchKbStats() {
  const res = await request('/stats/kb')
  if (!res.ok) throw new Error(`知识库统计请求失败：${res.status}`)
  return res.json()
}

// GET /stats/assist?days=30 AI 助手使用分析：会话/提问/延迟/采纳率/引用Top/趋势
export async function fetchAssistStats(days = 30) {
  const res = await request(`/stats/assist?days=${days}`)
  if (!res.ok) throw new Error(`AI 助手统计请求失败：${res.status}`)
  return res.json()
}
