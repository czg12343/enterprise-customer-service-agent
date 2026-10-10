<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref } from 'vue'
import MarkdownIt from 'markdown-it'
import { ElMessage } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { api, authenticatedFetch } from '../api/client'
import type { Conversation, Message, Source } from '../types'
import { serverDate } from '../utils/date'

const md = new MarkdownIt({ breaks: true, linkify: true })
const route = useRoute()
const router = useRouter()
const sourceOpen = ref(false)
const sourceLoading = ref(false)
const sourceTitle = ref('')
const sourceContent = ref('')
const returning = ref(false)
const humanActive = computed(() => ['waiting_human', 'human_active'].includes(activeConversation.value?.status || ''))
const statusTitle = computed(() => activeConversation.value?.status === 'waiting_human' ? '等待人工接入' : activeConversation.value?.status === 'human_active' ? '人工客服服务中' : '智能客服在线')
let refreshing = false
const conversations = ref<Conversation[]>([])
const activeId = ref('')
const messages = ref<Message[]>([])
const input = ref('')
const sending = ref(false)
const historyOpen = ref(false)
const scrollBox = ref<HTMLElement>()
const STREAM_TIMEOUT_MS = 75_000
const suggestions = ['查询订单 EM20260710001', '这个订单物流到哪了？', '七天无理由退货有什么要求？', '我要退货']
const activeConversation = computed(() => conversations.value.find((item) => item.id === activeId.value))
let messageRefreshTimer = 0
const traceNames: Record<string, string> = {
  agent_route: '意图识别与安全路由',
  query_order: '查询订单',
  query_logistics: '查询物流',
  search_products: '检索商品',
  check_refund_eligibility: '校验退款资格',
  duplicate_refund_guard: '防重复退款校验',
  create_refund: '创建退款申请',
  create_ticket: '创建售后工单',
  hybrid_retrieval: '混合知识检索',
  handoff_to_human: '转接人工客服',
  refund_progress: '退款流程进度',
}
const statusNames: Record<string, string> = {
  success: '已完成', waiting: '等待输入', waiting_confirmation: '等待确认',
  completed: '已提交', existing: '处理中', blocked_duplicate: '已拦截重复提交',
  not_found: '未找到', blocked: '已阻止',
}

function traceLabel(name: string) { return traceNames[name] || name }
function statusLabel(status: string) { return statusNames[status] || status }
function refundProgress(message: Message) {
  return [...(message.tool_calls || [])].reverse().find((tool) => tool.name === 'refund_progress')
}
function refundActionable(message: Message) {
  const latest = [...messages.value].reverse().find(item => refundProgress(item))
  return latest?.id === message.id && Boolean(activeConversation.value?.refund_state?.awaiting) && !humanActive.value
}
function routeNodes(message: Message): { node: string; latency_ms: number; status: string }[] {
  const nodes = message.tool_calls.find(tool => tool.name === 'agent_route')?.arguments.nodes
  return Array.isArray(nodes) ? nodes : []
}
async function showSource(source: Source) {
  if (!source.document_id || sourceLoading.value) return
  sourceLoading.value = true
  sourceContent.value = ''
  sourceTitle.value = `[${source.citation_id || ''}] ${source.document}`
  sourceOpen.value = true
  try {
    const { data } = await api.get<{ chunks: { id: string; content: string }[] }>(`/knowledge/documents/${source.document_id}`)
    sourceContent.value = data.chunks.find(chunk => chunk.id === source.chunk_id)?.content || '该分段已更新或删除。'
  } catch {
    sourceContent.value = '文档已删除或当前账号无权查看。'
  } finally { sourceLoading.value = false }
}
async function returnToBot() {
  if (!activeId.value || returning.value) return
  returning.value = true
  const id = activeId.value
  try {
    await api.post(`/chat/conversations/${id}/return-to-bot`)
    await loadConversations()
    if (activeId.value === id) await selectConversation(id)
  } finally { returning.value = false }
}

async function loadConversations() {
  const { data } = await api.get<Conversation[]>('/chat/conversations')
  conversations.value = data
  if (!activeId.value && data.length) await selectConversation(data[0].id)
  if (!data.length) await newConversation()
}

async function newConversation() {
  const { data } = await api.post<Conversation>('/chat/conversations', { title: '新会话' })
  conversations.value.unshift(data)
  await selectConversation(data.id)
  historyOpen.value = false
}

async function selectConversation(id: string) {
  activeId.value = id
  const { data } = await api.get<Message[]>(`/chat/conversations/${id}/messages`)
  messages.value = data
  historyOpen.value = false
  await scrollToBottom()
}

async function removeConversation(id: string) {
  await api.delete(`/chat/conversations/${id}`)
  activeId.value = ''
  messages.value = []
  await loadConversations()
}

function render(content: string) { return md.render(content) }

async function scrollToBottom() {
  await nextTick()
  if (scrollBox.value) scrollBox.value.scrollTop = scrollBox.value.scrollHeight
}

async function send(text?: string) {
  const content = (text ?? input.value).trim()
  if (!content || sending.value || !activeId.value) return
  input.value = ''
  sending.value = true
  const now = new Date().toISOString()
  messages.value.push({ id: crypto.randomUUID(), conversation_id: activeId.value, role: 'user', content, sources: [], tool_calls: [], created_at: now })
  const placeholder = reactive<Message>({ id: crypto.randomUUID(), conversation_id: activeId.value, role: 'assistant', content: '', sources: [], tool_calls: [], created_at: now, streaming: true })
  messages.value.push(placeholder)
  await scrollToBottom()
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), STREAM_TIMEOUT_MS)
  try {
    const response = await authenticatedFetch(`/api/v1/chat/conversations/${activeId.value}/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
      signal: controller.signal,
    })
    if (!response.ok || !response.body) {
      const payload = await response.json().catch(() => null) as { detail?: string } | null
      throw new Error(payload?.detail || '服务请求失败')
    }
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let completed = false
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const events = buffer.split('\n\n')
      buffer = events.pop() || ''
      for (const event of events) {
        const line = event.split('\n').find((item) => item.startsWith('data: '))
        if (!line) continue
        const data = JSON.parse(line.slice(6))
        if (data.type === 'delta') placeholder.content += data.content
        if (data.type === 'done') {
          Object.assign(placeholder, data.message, { streaming: false })
          completed = true
        }
      }
      await scrollToBottom()
    }
    if (!completed) throw new Error('响应流意外中断，请重试')
    await loadConversations()
  } catch (error: unknown) {
    placeholder.content = error instanceof Error && error.name === 'AbortError'
      ? '请求超时，请稍后重试。'
      : error instanceof Error ? error.message : '服务暂时不可用，请稍后重试。'
    placeholder.streaming = false
    ElMessage.error(placeholder.content)
  } finally {
    window.clearTimeout(timeout)
    sending.value = false
  }
}

async function feedback(message: Message, value: number) {
  const { data } = await api.post<Message>(`/chat/messages/${message.id}/feedback`, { value })
  message.feedback = data.feedback
}

onMounted(async () => {
  await loadConversations()
  if (typeof route.query.prompt === 'string') {
    const prompt = route.query.prompt.slice(0, 500)
    await newConversation()
    await router.replace('/chat')
    await send(prompt)
  }
  messageRefreshTimer = window.setInterval(async () => {
    if (!activeId.value || sending.value || refreshing || returning.value) return
    refreshing = true
    const id = activeId.value
    try {
    const [history, states] = await Promise.all([api.get<Message[]>(`/chat/conversations/${id}/messages`), api.get<Conversation[]>('/chat/conversations')])
    if (activeId.value !== id || sending.value) return
    conversations.value = states.data
    const data = history.data
    const currentLast = messages.value.at(-1)?.id
    const remoteLast = data.at(-1)?.id
    if (currentLast !== remoteLast || data.length !== messages.value.length) {
      messages.value = data
      await scrollToBottom()
    }
    } catch { /* The next poll retries a transient failure. */ }
    finally { refreshing = false }
  }, 4000)
})
onUnmounted(() => window.clearInterval(messageRefreshTimer))
</script>

<template>
  <div class="chat-page">
    <button v-if="historyOpen" class="conversation-mask" aria-label="关闭会话列表" @click="historyOpen = false"></button>
    <aside class="conversation-panel" :class="{ open: historyOpen }">
      <div class="conversation-mobile-head"><strong>会话记录</strong><button aria-label="关闭会话列表" @click="historyOpen = false">×</button></div>
      <button class="new-chat" @click="newConversation"><span>＋</span> 新建会话</button>
      <p class="section-label">最近会话</p>
      <div class="conversation-list">
        <button v-for="item in conversations" :key="item.id" :class="{ active: item.id === activeId }" @click="selectConversation(item.id)">
          <span><strong>{{ item.title }}</strong><small>{{ serverDate(item.updated_at).toLocaleDateString() }}</small></span>
          <i @click.stop="removeConversation(item.id)">×</i>
        </button>
      </div>
    </aside>
    <section class="chat-workspace">
      <header class="page-header">
        <div><p class="eyebrow">AI SERVICE DESK</p><h2>{{ activeConversation?.title || '智能客服' }}</h2></div>
        <div class="chat-header-actions">
          <button class="history-toggle" @click="historyOpen = true">会话记录</button>
          <span class="online-chip"><i></i>{{ statusTitle }}</span>
          <el-button v-if="humanActive" size="small" :loading="returning" @click="returnToBot">返回智能客服</el-button>
          <el-button v-else size="small" :disabled="sending" @click="send('我要转人工客服')">转人工</el-button>
        </div>
      </header>
      <div ref="scrollBox" class="message-scroll">
        <div v-if="!messages.length" class="welcome-state">
          <span class="ai-orbit">AI</span>
          <h1>上午好，有什么可以帮你？</h1>
          <p>我能理解企业知识，也能安全地查询订单、物流并办理售后。</p>
          <div class="suggestions"><button v-for="item in suggestions" :key="item" @click="send(item)">{{ item }} <span>↗</span></button></div>
        </div>
        <article v-for="message in messages" :key="message.id" class="message-row" :class="message.role">
          <span class="message-avatar">{{ message.role === 'assistant' ? 'AI' : '你' }}</span>
          <div class="message-body">
            <div class="message-meta">{{ message.role === 'assistant' ? (message.tool_calls.some(tool => ['human_reply', 'human_takeover'].includes(tool.name)) ? '人工客服' : 'EnterpriseMind') : '我' }} <small>{{ serverDate(message.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }}</small></div>
            <div class="bubble markdown-body" v-html="render(message.content || '正在思考…')"></div>
            <div v-if="refundProgress(message)" class="refund-progress">
              <div><strong>退款申请进度</strong><span>{{ refundProgress(message)?.arguments.step }}/{{ refundProgress(message)?.arguments.total }}</span></div>
              <progress :value="Number(refundProgress(message)?.arguments.step || 0)" :max="Number(refundProgress(message)?.arguments.total || 4)"></progress>
              <small>{{ refundProgress(message)?.arguments.label }}</small>
              <small v-if="refundProgress(message)?.arguments.order_no">订单 {{ refundProgress(message)?.arguments.order_no }}</small>
              <div v-if="refundActionable(message)"><el-button v-if="activeConversation?.refund_state?.awaiting === 'confirm'" type="primary" size="small" :disabled="sending" @click="send('确认提交')">确认提交申请</el-button><el-button size="small" :disabled="sending" @click="send('取消退货')">取消本次申请</el-button></div>
              <el-button v-if="refundProgress(message)?.status === 'completed' || refundProgress(message)?.status === 'existing'" link type="primary" @click="router.push('/tickets')">查看售后工单</el-button>
            </div>
            <details v-if="message.tool_calls?.length" class="trace-box"><summary>查看 Agent 执行轨迹（{{ message.tool_calls.length }} 项）</summary><div v-for="(node, index) in routeNodes(message)" :key="`node-${index}`"><code>{{ traceLabel(node.node) }}</code><span>{{ node.latency_ms }} ms · {{ statusLabel(node.status) }}</span></div><section v-for="(tool, index) in message.tool_calls" :key="`${tool.name}-${index}`"><div><code>{{ traceLabel(tool.name) }}</code><span>{{ statusLabel(tool.status) }}</span></div><pre class="trace-arguments">{{ JSON.stringify(tool.arguments, null, 2) }}</pre></section></details>
            <div v-if="message.sources?.length" class="source-list"><p>引用来源</p><button v-for="(source, index) in message.sources" :key="index" :disabled="!source.document_id" @click="showSource(source)"><strong>[{{ source.citation_id || index + 1 }}] {{ source.document }}</strong><span>{{ source.section || '相关章节' }} · {{ source.page ? `第 ${source.page} 页` : '查看原文' }}</span></button></div>
            <div v-if="message.role === 'assistant' && !message.streaming" class="message-actions"><button :class="{ active: message.feedback === 1 }" @click="feedback(message, 1)">有帮助</button><button :class="{ active: message.feedback === -1 }" @click="feedback(message, -1)">需改进</button></div>
          </div>
        </article>
      </div>
      <footer class="composer">
        <textarea v-model="input" rows="1" :placeholder="humanActive ? '发送给人工客服，Shift + Enter 换行' : '输入问题，Shift + Enter 换行'" @keydown.enter.exact.prevent="send()"></textarea>
        <button :disabled="sending || !input.trim()" @click="send()">{{ sending ? '处理中' : '发送' }} <span>↗</span></button>
        <small>AI 可能会出错。涉及账号和交易的操作会执行权限校验。</small>
      </footer>
    </section>
    <el-drawer v-model="sourceOpen" :title="sourceTitle" size="min(700px, 95vw)"><div v-loading="sourceLoading" class="source-content">{{ sourceContent }}</div></el-drawer>
  </div>
</template>

<style scoped>
.trace-arguments { white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; margin: 8px 0 16px; }
.source-content { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.8; }
</style>
