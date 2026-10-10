<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { isAxiosError } from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api/client'
import type { Product } from '../types'
import { serverDate } from '../utils/date'

const products = ref<Product[]>([])
const keyword = ref('')
const loading = ref(false)
const saving = ref(false)
const dialog = ref(false)
const editing = ref<Product | null>(null)
const quickEdits = reactive<Record<string, { price: string; stock: string; saving: boolean }>>({})
const form = reactive({
  sku: '', name: '', category: '', description: '', price: '1.00', stock: '0', is_active: true,
})

function errorText(error: unknown, fallback: string) {
  const detail = isAxiosError<{ detail?: string | { msg?: string }[] }>(error)
    ? error.response?.data?.detail
    : undefined
  return Array.isArray(detail) ? detail.map(item => item.msg || '字段格式错误').join('；') : detail || fallback
}

async function load() {
  loading.value = true
  try {
    products.value = (await api.get<Product[]>('/admin/products', {
      params: { keyword: keyword.value.trim() },
    })).data
    for (const product of products.value) {
      quickEdits[product.id] = { price: String(product.price), stock: String(product.stock), saving: false }
    }
  } catch (error: unknown) {
    ElMessage.error(errorText(error, '商品列表加载失败'))
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = null
  Object.assign(form, { sku: '', name: '', category: '', description: '', price: '1.00', stock: '0', is_active: true })
  dialog.value = true
}

function openEdit(product: Product) {
  editing.value = product
  Object.assign(form, {
    sku: product.sku, name: product.name, category: product.category,
    description: product.description, price: String(product.price),
    stock: String(product.stock), is_active: product.is_active,
  })
  dialog.value = true
}

async function save() {
  if (saving.value) return
  const price = Number(form.price)
  const stock = Number(form.stock)
  if (!form.sku.trim() || !form.name.trim() || !form.category.trim() || !Number.isFinite(price) || price <= 0 || !Number.isInteger(stock) || stock < 0) {
    ElMessage.warning('请完整填写 SKU、名称、分类、价格和库存')
    return
  }
  saving.value = true
  const payload = { ...form, price, stock, sku: form.sku.trim().toUpperCase() }
  try {
    if (editing.value) await api.patch(`/admin/products/${editing.value.id}`, payload)
    else await api.post('/admin/products', payload)
    dialog.value = false
    ElMessage.success(editing.value ? '商品已更新' : '商品已创建')
    await load()
  } catch (error: unknown) {
    ElMessage.error(errorText(error, '商品保存失败'))
  } finally {
    saving.value = false
  }
}

async function savePriceStock(product: Product) {
  const edit = quickEdits[product.id]
  if (!edit || edit.saving) return
  const price = Number(edit.price)
  const stock = Number(edit.stock)
  if (!Number.isFinite(price) || price <= 0 || !Number.isInteger(stock) || stock < 0) {
    ElMessage.warning('售价必须大于 0，库存必须是大于等于 0 的整数')
    return
  }
  edit.saving = true
  try {
    const { data } = await api.patch<Product>(`/admin/products/${product.id}`, { price, stock })
    Object.assign(product, data)
    edit.price = String(data.price)
    edit.stock = String(data.stock)
    ElMessage.success('价格和库存已保存')
  } catch (error: unknown) {
    ElMessage.error(errorText(error, '价格和库存保存失败'))
  } finally {
    edit.saving = false
  }
}

async function toggleActive(product: Product) {
  const action = product.is_active ? '下架' : '上架'
  try {
    await ElMessageBox.confirm(`确认${action}“${product.name}”吗？`, `${action}商品`, { type: 'warning' })
    const { data } = await api.patch<Product>(`/admin/products/${product.id}`, { is_active: !product.is_active })
    Object.assign(product, data)
    ElMessage.success(`商品已${action}`)
  } catch (error: unknown) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(errorText(error, `${action}失败`))
  }
}

onMounted(load)
</script>

<template>
  <div class="content-page">
    <header class="page-header roomy">
      <div><p class="eyebrow">PRODUCT CATALOG</p><h1>商品管理</h1><p>维护商品资料、价格、库存与上下架状态</p></div>
      <el-button type="primary" size="large" @click="openCreate">＋ 新增商品</el-button>
    </header>
    <section class="panel-card product-panel">
      <div class="product-toolbar">
        <el-input v-model="keyword" clearable placeholder="搜索名称、SKU 或分类" @keyup.enter="load" @clear="load" />
        <el-button type="primary" @click="load">搜索</el-button>
        <span>共 {{ products.length }} 件商品</span>
      </div>
      <el-table v-loading="loading" :data="products" stripe empty-text="暂无商品">
        <el-table-column label="SKU" min-width="145"><template #default="{ row }"><strong class="mono">{{ row.sku }}</strong></template></el-table-column>
        <el-table-column prop="name" label="商品名称" min-width="180" />
        <el-table-column prop="category" label="分类" width="120" />
        <el-table-column label="售价（可直接修改）" width="160"><template #default="{ row }"><el-input v-if="quickEdits[row.id]" v-model="quickEdits[row.id].price" type="number" min="0.01" step="0.01"><template #prepend>¥</template></el-input></template></el-table-column>
        <el-table-column label="库存（可直接修改）" width="150"><template #default="{ row }"><el-input v-if="quickEdits[row.id]" v-model="quickEdits[row.id].stock" type="number" min="0" step="1" /><small v-if="row.locked_stock">锁定 {{ row.locked_stock }}</small></template></el-table-column>
        <el-table-column label="状态" width="90"><template #default="{ row }"><el-tag :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? '销售中' : '已下架' }}</el-tag></template></el-table-column>
        <el-table-column label="创建时间" width="170"><template #default="{ row }">{{ serverDate(row.created_at).toLocaleString() }}</template></el-table-column>
        <el-table-column label="操作" width="245" fixed="right"><template #default="{ row }"><el-button link type="primary" :loading="quickEdits[row.id]?.saving" @click="savePriceStock(row)">保存价格库存</el-button><el-button link @click="openEdit(row)">编辑资料</el-button><el-button link :type="row.is_active ? 'danger' : 'success'" @click="toggleActive(row)">{{ row.is_active ? '下架' : '上架' }}</el-button></template></el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="dialog" :title="editing ? '编辑商品' : '新增商品'" width="min(660px, 95vw)" :close-on-click-modal="false">
      <el-form label-position="top">
        <div class="product-form-grid">
          <el-form-item label="SKU"><el-input v-model="form.sku" placeholder="例如 PHONE-X2" maxlength="40" /></el-form-item>
          <el-form-item label="商品名称"><el-input v-model="form.name" placeholder="例如 星云 X2 手机" maxlength="120" /></el-form-item>
          <el-form-item label="分类"><el-input v-model="form.category" placeholder="例如 手机" maxlength="50" /></el-form-item>
          <el-form-item label="销售状态"><el-switch v-model="form.is_active" active-text="上架" inactive-text="下架" /></el-form-item>
          <el-form-item label="售价（元）"><el-input v-model="form.price" type="number" min="0.01" max="9999999999" step="0.01" placeholder="0.00" /></el-form-item>
          <el-form-item label="库存"><el-input v-model="form.stock" type="number" min="0" max="10000000" step="1" placeholder="0" /></el-form-item>
        </div>
        <el-form-item label="商品描述"><el-input v-model="form.description" type="textarea" :rows="4" maxlength="5000" show-word-limit placeholder="用于客服检索与商品介绍" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="dialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存商品</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.product-panel { overflow: visible; }
.product-toolbar { display: flex; align-items: center; gap: 10px; padding: 16px 20px; border-bottom: 1px solid var(--line); }
.product-toolbar .el-input { max-width: 380px; }
.product-toolbar > span { margin-left: auto; color: #75837e; font-size: 12px; }
.product-form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 18px; }
small { color: #87938e; }
@media (max-width: 640px) {
  .product-toolbar { flex-wrap: wrap; }
  .product-toolbar > span { width: 100%; margin-left: 0; }
  .product-form-grid { grid-template-columns: 1fr; }
}
</style>
