// H组 AI 助手接口封装
import { request, getToken } from './http.js'

// H1 对话问答：POST + SSE 流式，异步生成器逐块产出 { event, data }
export async function* chatStream({ sessionId = null, caseId = null, message }) {
  // SSE 流式请求需要直接用 fetch 拿 response.body，但仍要带 token
  const headers = { 'Content-Type': 'application/json' }
  const token = getToken()
  if (token) headers['Authorization'] = `Bearer ${token}`

  const res = await fetch('/assist/chat', {
    method: 'POST',
    headers,
    body: JSON.stringify({ session_id: sessionId, case_id: caseId, message }),
  })
  if (!res.ok) throw new Error(`对话请求失败：${res.status}`)

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const parts = buf.split('\n\n')
    buf = parts.pop()
    for (const part of parts) {
      const event = (part.match(/^event:(\w+)/m) || [])[1]
      const dataStr = (part.match(/^data:(.*)$/m) || [])[1]
      if (!event || !dataStr) continue
      yield { event, data: JSON.parse(dataStr) }
    }
  }
}

// H2 采纳回流：引用卡片一键写入案件
export async function adoptCitation({ caseId, replyId, citation, target = 'similar_case_doc' }) {
  // request 自动带 Authorization 头
  const res = await request('/assist/adopt', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      case_id: caseId,
      from_reply_id: replyId,
      citation_type: citation.citation_type,
      ref_id: citation.ref_id,
      content: citation.content || citation.title,
      target,
    }),
  })
  if (!res.ok) throw new Error(`采纳请求失败：${res.status}`)
  return res.json()
}

// H3 会话列表：恢复抽屉时拉取当前用户的所有会话
export async function listSessions(caseId = null) {
  const url = caseId ? `/assist/sessions?case_id=${encodeURIComponent(caseId)}` : '/assist/sessions'
  const res = await request(url)
  if (!res.ok) throw new Error(`获取会话列表失败：${res.status}`)
  return res.json()
}

// H4 清空（删除）会话
export async function deleteSession(sessionId) {
  const res = await request(`/assist/sessions/${sessionId}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`删除会话失败：${res.status}`)
  return res.json()
}

// H5 会话历史消息：点击某个会话时拉取该会话的完整消息列表
export async function getSessionMessages(sessionId) {
  const res = await request(`/assist/sessions/${sessionId}/messages`)
  if (!res.ok) throw new Error(`获取历史消息失败：${res.status}`)
  return res.json()
}
