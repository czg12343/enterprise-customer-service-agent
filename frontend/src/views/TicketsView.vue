<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { isAxiosError } from 'axios'
import { api } from '../api/client'
import { useAuthStore } from '../stores/auth'
import type { Ticket, TicketCategory, TicketStatus } from '../types'
import { serverDate } from '../utils/date'

const auth = useAuthStore()
const tickets = ref<Ticket[]>([])
const dialog = ref(false)
const form = reactive<Pick<Ticket, 'category' | 'title' | 'description' | 'priority'> & { order_no: string }>({ order_no: '', category: 'order', title: '', description: '', priority: 'normal' })
const statusText: Record<TicketStatus, string> = { pending: '待处理', processing: '处理中', waiting_customer: '待用户回复', resolved: '已解决', closed: '已关闭' }
const categories: Record<TicketCategory, string> = { product: '商品问题', order: '订单问题', logistics: '物流问题', refund: '退款退货', repair: '维修售后', complaint: '投诉建议', other: '其他问题' }
const updateStatuses: TicketStatus[] = ['processing', 'waiting_customer', 'resolved', 'closed']
const refundStatuses: TicketStatus[] = ['processing', 'waiting_customer']

function errorText(error: unknown, fallback: string) {
  return isAxiosError<{ detail?: string }>(error) ? error.response?.data?.detail || fallback : fallback
}
function statusesFor(ticket: Ticket) { return ticket.category === 'refund' ? refundStatuses : updateStatuses }

async function load() { tickets.value = (await api.get<Ticket[]>('/tickets')).data }
async function create() {
  await api.post('/tickets', { ...form, order_no: form.order_no || null })
  ElMessage.success('工单创建成功')
  dialog.value = false
  Object.assign(form, { order_no: '', category: 'order', title: '', description: '', priority: 'normal' })
  await load()
}
async function update(ticket: Ticket, status: TicketStatus) {
  try {
    const { data } = await api.patch<Ticket>(`/tickets/${ticket.id}`, { status })
    Object.assign(ticket, data)
    ElMessage.success('状态已更新')
  } catch (error: unknown) {
    ElMessage.error(errorText(error, '状态更新失败'))
  }
}
async function decideRefund(ticket: Ticket, action: 'complete' | 'reject') {
  try {
    let result = ''
    if (action === 'complete') {
      await ElMessageBox.confirm(`确认订单 ${ticket.order_no} 已完成退款并恢复库存吗？`, '完成退款', { type: 'warning' })
    } else {
      const prompt = await ElMessageBox.prompt('请输入驳回原因', '驳回退款', {
        inputValidator: value => value.trim().length >= 2 || '请至少输入 2 个字',
      })
      result = prompt.value.trim()
    }
    const { data } = await api.post<Ticket>(`/tickets/${ticket.id}/refund-decision`, { action, result: result || null })
    Object.assign(ticket, data)
    ElMessage.success(action === 'complete' ? '退款已完成，库存已恢复' : '退款申请已驳回')
  } catch (error: unknown) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(errorText(error, action === 'complete' ? '完成退款失败' : '驳回退款失败'))
  }
}
onMounted(load)
</script>

<template>
  <div class="content-page">
    <header class="page-header roomy"><div><p class="eyebrow">SERVICE TICKETS</p><h1>{{ auth.user?.role === 'customer' ? '我的工单' : '工单中心' }}</h1><p>所有售后问题都有记录、有负责人、有结果</p></div><el-button type="primary" size="large" @click="dialog = true">＋ 创建工单</el-button></header>
    <div class="ticket-grid">
      <article v-for="ticket in tickets" :key="ticket.id" class="ticket-card">
        <header><span class="ticket-number">{{ ticket.ticket_no }}</span><el-tag :type="ticket.status === 'resolved' ? 'success' : ticket.status === 'processing' ? 'warning' : 'info'">{{ statusText[ticket.status] || ticket.status }}</el-tag></header>
        <h3>{{ ticket.title }}</h3><p>{{ ticket.description }}</p>
        <div class="ticket-tags"><span>{{ categories[ticket.category] || ticket.category }}</span><span>{{ ticket.priority }}</span><span v-if="ticket.order_no">{{ ticket.order_no }}</span></div>
        <footer><small>{{ serverDate(ticket.created_at).toLocaleString() }}</small><div v-if="auth.user?.role !== 'customer'"><template v-if="ticket.category === 'refund' && !['resolved', 'closed'].includes(ticket.status)"><el-button link type="success" @click="decideRefund(ticket, 'complete')">完成退款</el-button><el-button link type="danger" @click="decideRefund(ticket, 'reject')">驳回</el-button></template><el-dropdown @command="(value: TicketStatus) => update(ticket, value)"><button class="text-button">更新状态 ▾</button><template #dropdown><el-dropdown-menu><el-dropdown-item v-for="status in statusesFor(ticket)" :key="status" :command="status">{{ statusText[status] }}</el-dropdown-item></el-dropdown-menu></template></el-dropdown></div></footer>
        <p v-if="ticket.result"><strong>处理结果：</strong>{{ ticket.result }}</p>
      </article>
      <div v-if="!tickets.length" class="empty-card">暂无工单。遇到订单、物流或售后问题时，可以在这里创建。</div>
    </div>
    <el-dialog v-model="dialog" title="创建售后工单" width="520px">
      <el-form label-position="top"><el-form-item label="关联订单号（选填）"><el-input v-model="form.order_no" /></el-form-item><el-form-item label="问题分类"><el-select v-model="form.category" style="width:100%"><el-option v-for="(name, key) in categories" :key="key" :label="name" :value="key" /></el-select></el-form-item><el-form-item label="标题"><el-input v-model="form.title" /></el-form-item><el-form-item label="问题描述"><el-input v-model="form.description" type="textarea" :rows="4" /></el-form-item><el-form-item label="优先级"><el-radio-group v-model="form.priority"><el-radio-button value="low">低</el-radio-button><el-radio-button value="normal">普通</el-radio-button><el-radio-button value="high">高</el-radio-button></el-radio-group></el-form-item></el-form>
      <template #footer><el-button @click="dialog = false">取消</el-button><el-button type="primary" :disabled="!form.title || !form.description" @click="create">提交工单</el-button></template>
    </el-dialog>
  </div>
</template>
