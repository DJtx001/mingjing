// K组 操作日志接口封装（仅管理员可访问）
import { request } from './http.js'

// 分页查询操作日志。action 为空则查全部
export async function fetchLogs({ page = 1, pageSize = 20, action = '' } = {}) {
  const params = new URLSearchParams({ page, page_size: pageSize })
  if (action) params.set('action', action)
  const res = await request(`/admin/logs?${params.toString()}`)
  if (!res.ok) throw new Error(`日志查询失败：${res.status}`)
  return res.json()
}

// 删除单条日志（仅管理员；后端会把「删除日志」动作本身再记一条审计，形成闭环）
export async function deleteLog(logId) {
  const res = await request(`/admin/logs/${logId}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`删除日志失败：${res.status}`)
  return res.json()
}
