<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api/client'
import { useAuthStore } from '../stores/auth'
import type { HandoffConversation, Message } from '../types'
import { serverDate } from '../utils/date'

const auth = useAuthStore()
const queue = ref<HandoffConversation[]>([])
const activeId = ref('')
const messages = ref<Message[]>([])
const reply = ref('')
const busy = ref(false)
let refreshTimer = 0

const active = computed(() => queue.value.find((item) => item.id === activeId.value))
const canReply = computed(() => active.value?.status === 'human_active' && active.value.assignee_id === auth.user?.id)

async function loadQueue() {
  const { data } = await api.get<HandoffConversation[]>('/handoffs')
  queue.value = data
  if (activeId.value && !data.some((item) => item.id === activeId.value)) {
    activeId.value = ''
    messages.value = []
  }
  if (!activeId.value && data.length) await selectConversation(data[0].id)
}

async function loadMessages() {
  if (!activeId.value) return
  const { data } = await api.get<Message[]>(`/handoffs/${activeId.value}/messages`)
  messages.value = data
}

async function selectConversation(id: string) {
  activeId.value = id
  await loadMessages()
}

async function takeover() {
  if (!active.value || busy.value) return
  busy.value = true
  try {
    await api.post(`/handoffs/${active.value.id}/takeover`)
    ElMessage.success('会话已接管')
    await Promise.all([loadQueue(), loadMessages()])
  } finally { busy.value = false }
}

async function sendReply() {
  const content = reply.value.trim()
  if (!content || !active.value || busy.value || !canReply.value) return
  busy.value = true
  try {
    await api.post(`/handoffs/${active.value.id}/messages`, { content })
    reply.value = ''
    await loadMessages()
  } finally { busy.value = false }
}

async function closeHandoff() {
  if (!active.value || busy.value) return
  busy.value = true
  try {
    await api.post(`/handoffs/${active.value.id}/close`)
    ElMessage.success('人工服务已结束，会话已交回智能客服')
    activeId.value = ''
    messages.value = []
    await loadQueue()
  } finally { busy.value = false }
}

onMounted(async () => {
  await loadQueue()
  refreshTimer = window.setInterval(async () => {
    if (busy.value) return
    await loadQueue()
    await loadMessages()
  }, 4000)
})
onUnmounted(() => window.clearInterval(refreshTimer))
</script>

<template>
  <div class="handoff-page">
    <header class="page-header roomy">
      <div><p class="eyebrow">HUMAN HANDOFF</p><h1>人工接管工作台</h1><p>接管高风险或复杂会话，处理完毕后平滑交回智能客服</p></div>
      <span class="handoff-count">{{ queue.length }} 个待处理会话</span>
    </header>
    <div class="handoff-workspace">
      <aside class="handoff-queue">
        <p>实时队列</p>
        <button v-for="item in queue" :key="item.id" :class="{ active: item.id === activeId }" @click="selectConversation(item.id)">
          <div><strong>{{ item.customer_name }}</strong><span :class="item.status">{{ item.status === 'waiting_human' ? '等待接入' : '服务中' }}</span></div>
          <b>{{ item.title }}</b><small>{{ item.latest_message }}</small>
        </button>
        <div v-if="!queue.length" class="handoff-empty">当前没有等待人工处理的会话</div>
      </aside>
      <section class="handoff-chat">
        <template v-if="active">
          <header><div><strong>{{ active.customer_name }}</strong><small>会话 {{ active.id.slice(0, 8) }}</small></div><div><el-button v-if="active.status === 'waiting_human'" type="primary" :loading="busy" @click="takeover">接管会话</el-button><el-button v-if="canReply" :loading="busy" @click="closeHandoff">结束并交回机器人</el-button></div></header>
          <div class="handoff-messages">
            <article v-for="message in messages" :key="message.id" :class="message.role"><small>{{ message.role === 'user' ? active.customer_name : message.intent === 'human' ? '人工客服' : 'EnterpriseMind' }} · {{ serverDate(message.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) }}</small><p>{{ message.content }}</p></article>
          </div>
          <footer><textarea v-model="reply" :disabled="!canReply" :placeholder="canReply ? '输入人工回复，Enter 发送' : '接管会话后即可回复'" @keydown.enter.exact.prevent="sendReply"></textarea><button :disabled="!canReply || !reply.trim() || busy" @click="sendReply">发送回复 ↗</button></footer>
        </template>
        <div v-else class="handoff-placeholder"><span>接</span><h2>选择一个会话开始处理</h2><p>客服回复会实时同步到用户聊天窗口。</p></div>
      </section>
    </div>
  </div>
</template>
