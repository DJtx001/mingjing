// 认证接口封装：login / me
import { request, setToken, setUser, getToken, clearAuth, getUser } from './http.js'

/**
 * 登录：账号密码换取 JWT。
 * 成功后把 access_token 和 user 存 localStorage，返回完整响应。
 */
export async function login({ username, password }) {
  const res = await request('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  const data = await res.json()
  if (!res.ok || data.error) {
    throw new Error(data?.error?.message || `登录失败：${res.status}`)
  }
  // 后端返回 { access_token, token_type, expires_in, user }
  setToken(data.access_token)
  setUser(data.user)
  return data
}

/**
 * 获取当前登录用户信息。
 * 页面刷新时调用，用 localStorage 里的 token 去后端校验，返回真实用户。
 * token 失效会返回 401，由 http.js 统一处理。
 */
export async function fetchMe() {
  if (!getToken()) return null
  const res = await request('/auth/me')
  if (!res.ok) return null
  const user = await res.json()
  setUser(user)   // 用后端最新数据覆盖本地缓存
  return user
}

/**
 * 登出：单 token 方案下后端无状态，只需清本地存储。
 */
export function logout() {
  clearAuth()
}

// 供 App.vue 初始化时读取本地缓存的用户（仅用于首屏快速显示，会被 fetchMe 校验覆盖）
export function getCachedUser() {
  return getUser()
}
