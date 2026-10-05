// 统一请求封装：所有接口都走这里，自动带 Authorization 头，401 自动登出跳登录。
// 这样以后加鉴权不用每个接口单独改。

const TOKEN_KEY = 'mj_token'
const USER_KEY = 'mj_user'

// ---------- token / 用户 存取 ----------
export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || ''
}

export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token)
}

export function getUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || 'null')
  } catch {
    return null
  }
}

export function setUser(user) {
  localStorage.setItem(USER_KEY, JSON.stringify(user))
}

// 登出：清掉 token 和用户信息。单 token 方案下后端无状态，不用调接口。
export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

// ---------- 统一请求 ----------
export async function request(url, options = {}) {
  const headers = { ...(options.headers || {}) }
  // 有 token 就带上。注意：登录接口不需要 token，这里带上也无妨（后端忽略）。
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`

  const res = await fetch(url, { ...options, headers })

  // 401：token 失效或没登录 → 清掉本地会话，刷新页面让用户回登录页
  if (res.status === 401) {
    clearAuth()
    // 避免在登录页反复刷新：仅当当前不在登录页时才 reload
    if (!window.location.pathname.includes('login')) {
      window.location.reload()
    }
    throw new Error('登录已失效，请重新登录')
  }

  return res
}
