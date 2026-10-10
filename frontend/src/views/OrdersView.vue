<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { isAxiosError } from 'axios'
import { useRouter } from 'vue-router'
import { api } from '../api/client'
import type { Order, Product, User } from '../types'
import { useAuthStore } from '../stores/auth'
import { serverDate } from '../utils/date'

const orders = ref<Order[]>([])
const router = useRouter()
function askAboutOrder(order: Order, action: string) {
  router.push({ path: '/chat', query: { prompt: `${action} ${order.order_no}` } })
}
const selected = ref<Order | null>(null)
const loading = ref(true)

const auth = useAuthStore()
const isAdmin = computed(() => auth.user?.role === 'admin')
const isStaff = computed(() => auth.user?.role !== 'customer')
const createDialog = ref(false)
const logisticsDialog = ref(false)
const saving = ref(false)
const products = ref<Product[]>([])
const productLoading = ref(false)
const customers = ref<User[]>([])
const form = reactive({ customer_username: '', order_no: '', payment_status: 'paid', items: [{ product_id: '', quantity: 1 }] })
const logisticsForm = reactive({ carrier: '', tracking_no: '', status: 'in_transit', latest_event: '', estimated_delivery: '', delivered_at: '' })
const logisticsStatus: Record<string, string> = { shipped: '已发货', in_transit: '运输中', out_for_delivery: '派送中', delivered: '已签收' }

function normalizeOrderNo(value: string) {
  const orderNo = value.trim().toUpperCase().replace(/\s+/g, '')
  if (!orderNo) return null
  return /^\d{6,35}$/.test(orderNo) ? `EM${orderNo}` : orderNo
}

function errorText(error: unknown, fallback: string) {
  const detail = isAxiosError<{ detail?: string | { msg?: string }[] }>(error) ? error.response?.data?.detail : undefined
  return Array.isArray(detail) ? detail.map(item => item.msg || '字段格式错误').join('；') : detail || fallback
}

async function searchProducts(keyword = '') {
  productLoading.value = true
  try {
    const { data } = await api.get<Product[]>('/products', { params: { keyword: keyword.trim(), limit: 100 } })
    const selectedIds = new Set(form.items.map(item => item.product_id).filter(Boolean))
    const retained = products.value.filter(product => selectedIds.has(product.id))
    products.value = [...data, ...retained.filter(product => !data.some(item => item.id === product.id))]
  } finally {
    productLoading.value = false
  }
}

async function load() {
  loading.value = true
  try { orders.value = (await api.get<Order[]>('/orders')).data }
  catch (error: unknown) {
    ElMessage.error(isAxiosError<{ detail?: string }>(error) ? error.response?.data?.detail || '订单列表加载失败' : '订单列表加载失败')
  }
  finally { loading.value = false }
}
onMounted(load)

async function openCreate() {
  Object.assign(form, { customer_username: '', order_no: '', payment_status: 'paid', items: [{ product_id: '', quantity: 1 }] })
  try {
    const [, customerResponse] = await Promise.all([
      searchProducts(),
      api.get<User[]>('/admin/customers'),
    ])
    customers.value = customerResponse.data
  } catch (error: unknown) {
    ElMessage.error(errorText(error, '订单表单数据加载失败'))
    return
  }
  createDialog.value = true
}
async function createOrder() {
  if (saving.value) return
  const orderNo = normalizeOrderNo(form.order_no)
  if (orderNo && !/^[A-Z]{2,5}\d{6,35}$/.test(orderNo)) {
    ElMessage.warning('订单号需为 2～5 位字母加 6～35 位数字，也可以只输入 6～35 位数字')
    return
  }
  saving.value = true
  try {
    const { data } = await api.post<Order>('/orders', { ...form, order_no: orderNo })
    createDialog.value = false
    selected.value = data
    orders.value = [data, ...orders.value.filter(order => order.id !== data.id)]
    ElMessage.success('订单已录入')
    await load()
  } catch (error: unknown) {
    ElMessage.error(errorText(error, '订单保存失败，请检查客户、订单号和商品'))
  } finally { saving.value = false }
}
async function orderAction(order: Order, action: 'pay' | 'cancel') {
  const label = action === 'pay' ? '确认支付' : '取消订单'
  try {
    await ElMessageBox.confirm(`确定要${label} ${order.order_no} 吗？`, label, { type: 'warning' })
    const { data } = await api.post<Order>(`/orders/${order.order_no}/${action}`)
    const index = orders.value.findIndex(item => item.id === data.id)
    if (index >= 0) orders.value[index] = data
    if (selected.value?.id === data.id) selected.value = data
    ElMessage.success(`${label}成功`)
  } catch (error: unknown) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(errorText(error, `${label}失败`))
  }
}
function openLogistics(order: Order) {
  selected.value = order
  const info = order.logistics
  Object.assign(logisticsForm, {
    carrier: info?.carrier || '', tracking_no: info?.tracking_no || '',
    status: order.shipping_status === 'delivered' ? 'delivered' : Object.keys(logisticsStatus).find(key => logisticsStatus[key] === info?.status) || 'in_transit',
    latest_event: info?.latest_event || '', estimated_delivery: info?.estimated_delivery || '', delivered_at: info?.delivered_at || '',
  })
  logisticsDialog.value = true
}
async function saveLogistics() {
  if (saving.value || !selected.value) return
  saving.value = true
  try {
    const { data } = await api.put<Order>(`/orders/${selected.value.order_no}/logistics`, {
      ...logisticsForm, estimated_delivery: logisticsForm.estimated_delivery || null,
      delivered_at: logisticsForm.status === 'delivered' && logisticsForm.delivered_at ? new Date(logisticsForm.delivered_at).toISOString() : null,
    })
    selected.value = data
    logisticsDialog.value = false
    await load()
    ElMessage.success('物流已更新')
  } finally { saving.value = false }
}

const statusText: Record<string, string> = { paid: '已支付', shipped: '已发货', pending: '待处理', delivered: '已签收', cancelled: '已取消', refunded: '已退款' }
</script>

<template>
  <div class="content-page">
    <header class="page-header roomy"><div><p class="eyebrow">ORDER CENTER</p><h1>订单中心</h1><p>查看商品、支付状态与物流进度</p></div><div><span class="count-badge">{{ orders.length }} 笔订单</span><el-button v-if="isAdmin" type="primary" @click="openCreate">新增订单</el-button></div></header>
    <section class="panel-card">
      <el-table v-loading="loading" :data="orders" stripe @row-click="(row: Order) => selected = row">
        <el-table-column label="订单号" min-width="180"><template #default="{ row }"><strong class="mono">{{ row.order_no }}</strong></template></el-table-column>
        <el-table-column v-if="isStaff" prop="customer_username" label="客户账号" min-width="120" />
        <el-table-column label="商品" min-width="220"><template #default="{ row }">{{ row.items.map((item: any) => item.product_name).join('、') }}</template></el-table-column>
        <el-table-column label="金额" width="120"><template #default="{ row }"><strong>¥{{ Number(row.total_amount).toFixed(2) }}</strong></template></el-table-column>
        <el-table-column label="支付状态" width="110"><template #default="{ row }"><el-tag type="success" effect="light">{{ statusText[row.payment_status] || row.payment_status }}</el-tag></template></el-table-column>
        <el-table-column label="配送状态" width="110"><template #default="{ row }"><el-tag effect="plain">{{ statusText[row.shipping_status] || row.shipping_status }}</el-tag></template></el-table-column>
        <el-table-column label="下单时间" width="170"><template #default="{ row }">{{ serverDate(row.created_at).toLocaleString() }}</template></el-table-column>
        <el-table-column label="快捷操作" width="210"><template #default="{ row }"><el-button link type="primary" @click.stop="askAboutOrder(row, '查询物流')">查物流</el-button><el-button link type="primary" :disabled="row.payment_status !== 'paid' || ['cancelled', 'refunded'].includes(row.status)" @click.stop="askAboutOrder(row, '我要退货')">申请退货</el-button><el-button link @click.stop="askAboutOrder(row, '转人工咨询订单')">转人工</el-button></template></el-table-column>
        <el-table-column v-if="isAdmin" label="操作" width="230" fixed="right"><template #default="{ row }"><el-button v-if="row.payment_status === 'pending' && row.status !== 'cancelled'" link type="primary" @click.stop="orderAction(row, 'pay')">确认支付</el-button><el-button v-if="row.payment_status === 'pending' && row.shipping_status === 'pending' && row.status !== 'cancelled'" link type="danger" @click.stop="orderAction(row, 'cancel')">取消订单</el-button><el-button v-if="row.payment_status === 'paid' && !['cancelled', 'refunded'].includes(row.status)" link type="primary" @click.stop="openLogistics(row)">更新物流</el-button></template></el-table-column>
      </el-table>
    </section>
    <el-drawer :model-value="Boolean(selected)" title="订单详情" size="440px" @close="selected = null">
      <template v-if="selected">
        <p class="eyebrow">{{ selected.order_no }}</p>
        <h2>¥{{ Number(selected.total_amount).toFixed(2) }}</h2>
        <div class="detail-list"><div v-for="item in selected.items" :key="item.product_name"><span>{{ item.product_name }} × {{ item.quantity }}</span><strong>¥{{ Number(item.unit_price).toFixed(2) }}</strong></div></div>
        <div v-if="selected.logistics" class="logistics-card"><p>物流追踪</p><h3>{{ selected.logistics.status }}</h3><span>{{ selected.logistics.carrier }} · {{ selected.logistics.tracking_no }}</span><strong>{{ selected.logistics.latest_event }}</strong><small>预计送达 {{ selected.logistics.estimated_delivery || '待定' }}</small></div>
      </template>
    </el-drawer>
    <el-dialog v-model="createDialog" title="新增订单" width="min(640px, 95vw)" :close-on-click-modal="false">
      <el-alert title="已支付订单会扣减库存；待支付订单会锁定库存，支付或取消后自动结转。" type="info" :closable="false" />
      <el-form label-position="top">
        <el-form-item label="客户账号"><el-select v-model="form.customer_username" filterable placeholder="选择客户" style="width:100%"><el-option v-for="customer in customers" :key="customer.id" :label="`${customer.username} · ${customer.email}`" :value="customer.username" /></el-select><small v-if="!customers.length">暂无可用客户，请先注册普通用户账号</small></el-form-item>
        <el-form-item label="订单号（选填，留空自动生成）"><el-input v-model="form.order_no" placeholder="例如 EM20260905001；纯数字会自动补 EM" maxlength="40" /></el-form-item>
        <el-form-item label="支付状态"><el-select v-model="form.payment_status"><el-option label="已支付" value="paid" /><el-option label="未支付" value="pending" /></el-select></el-form-item>
        <el-form-item v-for="(item, index) in form.items" :key="index" :label="`商品 ${index + 1}`">
          <el-select v-model="item.product_id" filterable remote reserve-keyword :remote-method="searchProducts" :loading="productLoading" placeholder="输入名称或 SKU 搜索商品" style="width:60%"><el-option v-for="product in products" :key="product.id" :disabled="product.stock - product.locked_stock <= 0" :label="`${product.name} · ¥${product.price} · 可售 ${Math.max(0, product.stock - product.locked_stock)}`" :value="product.id" /></el-select>
          <el-input-number v-model="item.quantity" :min="1" :max="999" :precision="0" style="width:120px" />
          <el-button link type="danger" :disabled="form.items.length === 1" @click="form.items.splice(index, 1)">移除</el-button>
        </el-form-item>
        <el-button :disabled="form.items.length >= 100" @click="form.items.push({ product_id: '', quantity: 1 })">添加商品</el-button>
      </el-form>
      <template #footer><el-button @click="createDialog = false">取消</el-button><el-button type="primary" :loading="saving" :disabled="!form.customer_username.trim() || form.items.some(item => !item.product_id || !item.quantity)" @click="createOrder">保存订单</el-button></template>
    </el-dialog>
    <el-dialog v-model="logisticsDialog" title="更新物流" width="min(560px, 95vw)" :close-on-click-modal="false">
      <el-form label-position="top">
        <el-form-item label="承运商"><el-input v-model="logisticsForm.carrier" placeholder="例如 顺丰速运" maxlength="80" /></el-form-item>
        <el-form-item label="运单号"><el-input v-model="logisticsForm.tracking_no" maxlength="80" /></el-form-item>
        <el-form-item label="物流状态"><el-select v-model="logisticsForm.status"><el-option v-for="(label, value) in logisticsStatus" :key="value" :label="label" :value="value" /></el-select></el-form-item>
        <el-form-item label="最新位置 / 进展"><el-input v-model="logisticsForm.latest_event" placeholder="例如 包裹已到达大同分拨中心" maxlength="255" /></el-form-item>
        <el-form-item label="预计送达日期（选填）"><el-date-picker v-model="logisticsForm.estimated_delivery" type="date" value-format="YYYY-MM-DD" /></el-form-item>
        <el-form-item v-if="logisticsForm.status === 'delivered'" label="签收时间（首次留空使用当前时间）"><el-date-picker v-model="logisticsForm.delivered_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="logisticsDialog = false">取消</el-button><el-button type="primary" :loading="saving" :disabled="!logisticsForm.carrier.trim() || !logisticsForm.tracking_no.trim() || !logisticsForm.latest_event.trim()" @click="saveLogistics">保存物流</el-button></template>
    </el-dialog>
  </div>
</template>
