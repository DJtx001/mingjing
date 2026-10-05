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
