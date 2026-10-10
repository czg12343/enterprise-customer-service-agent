<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api/client'
import { useAuthStore } from '../stores/auth'

interface Base { id: string; name: string; visibility: 'public' | 'internal' }
interface Hit { document: string; document_id: string; chunk_id: string; section?: string; page?: number; content: string; retrieval: { bm25_score: number; hashed_vector_score: number; rrf_score: number } }
const auth = useAuthStore()
const bases = ref<Base[]>([])
const baseId = ref('')
const query = ref('')
const limit = ref(5)
const publicOnly = ref(false)
const hits = ref<Hit[]>([])
const loading = ref(false)
const searched = ref(false)
const elapsed = ref(0)
const changing = ref('')
onMounted(async () => { bases.value = (await api.get<Base[]>('/knowledge/bases')).data })
async function search() {
  if (!query.value.trim() || loading.value) return
  loading.value = true
  hits.value = []
  searched.value = false
  const start = performance.now()
  try {
    hits.value = (await api.get<{ results: Hit[] }>('/knowledge/search', { params: { q: query.value, limit: limit.value, base_id: baseId.value || undefined, public_only: publicOnly.value } })).data.results
    searched.value = true
    elapsed.value = Math.round(performance.now() - start)
  } finally { loading.value = false }
}
async function setAccess(base: Base, visibility: string | number | boolean | undefined) {
  if (changing.value) return
  changing.value = base.id
  try {
    const { data } = await api.patch<Base>(`/knowledge/bases/${base.id}/access`, { visibility })
    base.visibility = data.visibility
    hits.value = []
    searched.value = false
    ElMessage.success('知识库访问范围已更新')
  } finally { changing.value = '' }
}
</script>

<template>
  <div class="content-page">
    <header class="page-header roomy"><div><p class="eyebrow">RETRIEVAL TEST</p><h1>检索测试</h1><p>检查命中文档、分段内容与排序分数</p></div></header>
    <section class="panel-card search-controls">
      <el-input v-model="query" maxlength="500" placeholder="输入测试问题" @keydown.enter="search" />
      <el-select v-model="baseId" placeholder="所有可访问知识库" clearable><el-option v-for="base in bases" :key="base.id" :label="base.name" :value="base.id" /></el-select>
      <el-input-number v-model="limit" :min="1" :max="20" :precision="0" />
      <el-checkbox v-model="publicOnly">仅客户可见知识</el-checkbox>
      <el-button type="primary" :loading="loading" :disabled="!query.trim()" @click="search">测试检索</el-button>
    </section>
    <p v-if="searched">命中 {{ hits.length }} 个分段 · 请求耗时 {{ elapsed }} ms</p>
    <el-empty v-if="searched && !hits.length" description="当前访问范围没有匹配结果" />
    <section v-for="(hit, index) in hits" :key="hit.chunk_id" class="panel-card hit-card">
      <h3>{{ index + 1 }}. {{ hit.document }}</h3><p>{{ hit.section || '正文' }} <span v-if="hit.page">· 第 {{ hit.page }} 页</span></p>
      <div class="scores"><el-tag>BM25 {{ hit.retrieval.bm25_score }}</el-tag><el-tag>哈希词法 {{ hit.retrieval.hashed_vector_score }}</el-tag><el-tag>RRF {{ hit.retrieval.rrf_score }}</el-tag></div>
      <details><summary>查看命中原文</summary><p class="chunk-content">{{ hit.content }}</p><small>分段 {{ hit.chunk_id }}</small></details>
    </section>
    <section v-if="auth.user?.role === 'admin'" class="panel-card hit-card">
      <h2>知识访问范围</h2><p>内部知识仅客服和管理员可见；公开知识可供客户查询。</p>
      <el-table :data="bases"><el-table-column prop="name" label="知识库" /><el-table-column label="访问范围" width="220"><template #default="{ row }"><el-select :model-value="row.visibility" :disabled="Boolean(changing)" @change="(value: string) => setAccess(row, value)"><el-option label="仅内部人员" value="internal" /><el-option label="客户可见" value="public" /></el-select></template></el-table-column></el-table>
    </section>
  </div>
</template>

<style scoped>
.search-controls { display: flex; flex-wrap: wrap; gap: 12px; padding: 20px; }
.search-controls > .el-input { flex: 1 1 260px; }
.search-controls > .el-select { width: 260px; }
.hit-card { padding: 20px; margin-top: 16px; }
.scores { display: flex; flex-wrap: wrap; gap: 8px; margin: 12px 0; }
.chunk-content { white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.8; }
summary { cursor: pointer; }
</style>
