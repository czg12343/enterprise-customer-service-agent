<script setup lang="ts">
import { isAxiosError } from 'axios'
import { computed, onMounted, ref } from 'vue'
import { ElMessage, type UploadRequestOptions } from 'element-plus'
import { api } from '../api/client'
import { useAuthStore } from '../stores/auth'
import { serverDate } from '../utils/date'

interface Stats { users: number; orders: number; open_tickets: number; conversations: number; knowledge_documents: number; today_agent_runs: number }
interface KnowledgeBase { id: string; name: string; description: string; is_active: boolean; document_count: number; chunk_count: number }
interface Document { id: string; filename: string; file_type: string; status: string; chunk_count: number; created_at: string }
interface DocumentChunk { id: string; chunk_index: number; content: string; page_number?: number; section?: string; start_char: number; end_char: number }
interface DocumentContent extends Document { knowledge_base_id: string; knowledge_base_name: string; chunks: DocumentChunk[] }
interface LLMConfig { base_url: string; model: string; enabled: boolean; ready: boolean; has_api_key: boolean; source: string }

const auth = useAuthStore()
const stats = ref<Stats>({ users: 0, orders: 0, open_tickets: 0, conversations: 0, knowledge_documents: 0, today_agent_runs: 0 })
const bases = ref<KnowledgeBase[]>([])
const activeBase = ref('')
const documents = ref<Document[]>([])
const baseDialog = ref(false)
const baseName = ref('')
const baseVisibility = ref('internal')
const previewOpen = ref(false)
const previewLoading = ref(false)
const previewQuery = ref('')
const previewDocument = ref<DocumentContent | null>(null)
const llmConfig = ref<LLMConfig | null>(null)
const llmForm = ref({
  base_url: 'https://openrouter.ai/api/v1',
  api_key: '',
  model: 'openrouter/free',
  enabled: true,
})
const savingLLM = ref(false)
const testingLLM = ref(false)
const activeBaseInfo = computed(() => bases.value.find((base) => base.id === activeBase.value))
const filteredChunks = computed(() => {
  const chunks = previewDocument.value?.chunks || []
  const keyword = previewQuery.value.trim().toLowerCase()
  if (!keyword) return chunks
  return chunks.filter((chunk) => `${chunk.section || ''} ${chunk.content}`.toLowerCase().includes(keyword))
})

function errorMessage(error: unknown, fallback: string) {
  return isAxiosError<{ detail?: string }>(error) ? error.response?.data?.detail || fallback : fallback
}

async function loadLLMConfig() {
  const { data } = await api.get<LLMConfig>('/admin/llm-config')
  llmConfig.value = data
  llmForm.value.base_url = data.base_url || 'https://openrouter.ai/api/v1'
  llmForm.value.model = data.model || 'openrouter/free'
  llmForm.value.enabled = data.enabled || !data.base_url
  llmForm.value.api_key = ''
}

async function load() {
  stats.value = (await api.get<Stats>('/admin/stats')).data
  bases.value = (await api.get<KnowledgeBase[]>('/knowledge/bases')).data
  if (!activeBase.value && bases.value.length) activeBase.value = bases.value[0].id
  await loadDocuments()
  if (auth.user?.role === 'admin') await loadLLMConfig()
}
async function loadDocuments() {
  documents.value = activeBase.value ? (await api.get<Document[]>(`/knowledge/bases/${activeBase.value}/documents`)).data : []
}
async function selectBase(id: string) {
  activeBase.value = id
  previewOpen.value = false
  await loadDocuments()
}
async function viewDocument(document: Document) {
  previewOpen.value = true
  previewLoading.value = true
  previewQuery.value = ''
  previewDocument.value = null
  try {
    previewDocument.value = (await api.get<DocumentContent>(`/knowledge/documents/${document.id}`)).data
  } catch (error: unknown) {
    ElMessage.error(errorMessage(error, '读取知识文档失败'))
    previewOpen.value = false
  } finally {
    previewLoading.value = false
  }
}
async function createBase() {
  const { data } = await api.post<KnowledgeBase>('/knowledge/bases', { name: baseName.value, description: '由管理后台创建', visibility: baseVisibility.value })
  bases.value.unshift(data); activeBase.value = data.id; baseDialog.value = false; baseName.value = ''; await loadDocuments()
}
async function upload(options: UploadRequestOptions) {
  if (!activeBase.value) {
    ElMessage.warning('请先选择知识库')
    return
  }
  const data = new FormData(); data.append('file', options.file)
  try {
    await api.post(`/knowledge/bases/${activeBase.value}/documents`, data, { headers: { 'Content-Type': 'multipart/form-data' } })
    ElMessage.success('文档解析与切块完成'); options.onSuccess({}); await load()
  } catch (error: any) { options.onError(error); ElMessage.error(error.response?.data?.detail || '上传失败') }
}
async function remove(file: Document) {
  await api.delete(`/knowledge/documents/${file.id}`); ElMessage.success('已删除'); await load()
}
async function saveLLMConfig() {
  savingLLM.value = true
  try {
    const { data } = await api.put<LLMConfig>('/admin/llm-config', {
      ...llmForm.value,
      api_key: llmForm.value.api_key || null,
    })
    llmConfig.value = data
    llmForm.value.api_key = ''
    ElMessage.success('大模型配置已保存并立即生效')
  } catch (error: unknown) {
    ElMessage.error(errorMessage(error, '保存大模型配置失败'))
  } finally {
    savingLLM.value = false
  }
}
async function testLLMConfig() {
  testingLLM.value = true
  try {
    const { data } = await api.post<{ success: boolean; message: string }>('/admin/llm-config/test')
    ElMessage.success(data.message || '模型连接成功')
  } catch (error: unknown) {
    ElMessage.error(errorMessage(error, '模型连接失败'))
  } finally {
    testingLLM.value = false
  }
}
onMounted(load)
</script>

<template>
  <div class="content-page">
    <header class="page-header roomy"><div><p class="eyebrow">OPERATIONS CONSOLE</p><h1>运营管理</h1><p>业务运行状态、知识资产与 Agent 执行概览</p></div><span class="online-chip"><i></i>系统运行正常</span></header>
    <section class="stats-grid">
      <article><span>用户总数</span><strong>{{ stats.users }}</strong><small>已注册账户</small></article><article><span>订单总数</span><strong>{{ stats.orders }}</strong><small>业务订单</small></article><article><span>开放工单</span><strong>{{ stats.open_tickets }}</strong><small>需要跟进</small></article><article><span>今日 Agent 调用</span><strong>{{ stats.today_agent_runs }}</strong><small>自动处理任务</small></article><article><span>会话数量</span><strong>{{ stats.conversations }}</strong><small>用户对话</small></article><article><span>知识文档</span><strong>{{ stats.knowledge_documents }}</strong><small>已解析资料</small></article>
    </section>
    <section v-if="auth.user?.role === 'admin'" class="panel-card llm-config-panel">
      <header>
        <div><p class="eyebrow">MODEL PROVIDER</p><h2>大模型 API 配置</h2><p>配置 OpenAI 兼容接口，保存后无需重启即可生效</p></div>
        <el-tag :type="llmConfig?.ready ? 'success' : 'warning'">{{ llmConfig?.ready ? '已连接配置' : '尚未完成' }}</el-tag>
      </header>
      <el-form label-position="top" class="llm-config-form">
        <el-form-item label="API Base URL">
          <el-input v-model="llmForm.base_url" placeholder="https://openrouter.ai/api/v1" />
        </el-form-item>
        <el-form-item label="模型名称">
          <el-input v-model="llmForm.model" placeholder="openrouter/free" />
        </el-form-item>
        <el-form-item label="API Key" class="api-key-field">
          <el-input v-model="llmForm.api_key" type="password" show-password autocomplete="new-password" :placeholder="llmConfig?.has_api_key ? '已安全保存，留空表示不修改' : '请输入 API Key'" />
          <small>密钥不会返回到浏览器，保存后输入框会自动清空。</small>
        </el-form-item>
        <el-form-item label="调用状态">
          <el-radio-group v-model="llmForm.enabled">
            <el-radio-button :value="true">启用</el-radio-button>
            <el-radio-button :value="false">停用</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <div class="llm-config-actions">
          <el-button type="primary" :loading="savingLLM" @click="saveLLMConfig">保存配置</el-button>
          <el-button :loading="testingLLM" :disabled="!llmConfig?.ready" @click="testLLMConfig">测试连接</el-button>
          <span>当前来源：{{ llmConfig?.source === 'admin' ? '管理界面' : '环境变量' }}</span>
        </div>
      </el-form>
    </section>
    <section class="panel-card knowledge-panel">
      <header>
        <div><p class="eyebrow">KNOWLEDGE BASE</p><h2>企业知识库</h2><p>选择知识库并打开文档，即可查看 Agent 实际检索的知识内容</p></div>
        <div class="header-actions"><el-button v-if="auth.user?.role === 'admin'" @click="baseDialog = true">新建知识库</el-button><el-upload v-if="auth.user?.role === 'admin'" :show-file-list="false" :http-request="upload" accept=".pdf,.docx,.txt,.md,.xlsx,.csv"><el-button type="primary">上传文档</el-button></el-upload></div>
      </header>
      <div class="knowledge-workspace">
        <aside class="knowledge-base-list">
          <button v-for="base in bases" :key="base.id" :class="{ active: base.id === activeBase }" @click="selectBase(base.id)">
            <span class="knowledge-base-icon">知</span>
            <div><strong>{{ base.name }}</strong><p>{{ base.description || '暂无知识库说明' }}</p><small>{{ base.document_count }} 份文档 · {{ base.chunk_count }} 个知识分段</small></div>
          </button>
          <div v-if="!bases.length" class="knowledge-empty">暂无知识库</div>
        </aside>
        <div class="knowledge-document-list">
          <div class="knowledge-summary"><div><strong>{{ activeBaseInfo?.name || '请选择知识库' }}</strong><p>{{ activeBaseInfo?.description }}</p></div><span>{{ documents.length }} 份文档</span></div>
          <el-table :data="documents" empty-text="该知识库中还没有文档">
            <el-table-column prop="filename" label="知识文档" min-width="230" />
            <el-table-column prop="file_type" label="类型" width="80"><template #default="{ row }"><span class="file-type">{{ row.file_type }}</span></template></el-table-column>
            <el-table-column prop="chunk_count" label="知识分段" width="100" />
            <el-table-column prop="status" label="状态" width="90"><template #default="{ row }"><el-tag type="success">{{ row.status }}</el-tag></template></el-table-column>
            <el-table-column label="更新时间" width="165"><template #default="{ row }">{{ serverDate(row.created_at).toLocaleString() }}</template></el-table-column>
            <el-table-column label="操作" width="135" fixed="right"><template #default="{ row }"><el-button link type="primary" @click="viewDocument(row)">查看内容</el-button><el-popconfirm v-if="auth.user?.role === 'admin'" title="确认删除该文档及切块？" @confirm="remove(row)"><template #reference><el-button link type="danger">删除</el-button></template></el-popconfirm></template></el-table-column>
          </el-table>
        </div>
      </div>
    </section>
    <el-dialog v-model="baseDialog" title="新建知识库" width="420px"><el-form label-position="top"><el-form-item label="名称"><el-input v-model="baseName" placeholder="例如：商品知识库" /></el-form-item><el-form-item label="访问范围"><el-select v-model="baseVisibility"><el-option label="仅内部人员" value="internal" /><el-option label="客户可见" value="public" /></el-select></el-form-item></el-form><template #footer><el-button @click="baseDialog = false">取消</el-button><el-button type="primary" :disabled="baseName.length < 2" @click="createBase">创建</el-button></template></el-dialog>
    <el-drawer v-model="previewOpen" size="min(760px, 92vw)" class="knowledge-preview-drawer">
      <template #header><div class="knowledge-preview-title"><p class="eyebrow">DOCUMENT CONTENT</p><h2>{{ previewDocument?.filename || '正在读取文档' }}</h2><span v-if="previewDocument">{{ previewDocument.knowledge_base_name }} · {{ previewDocument.chunks.length }} 个知识分段</span></div></template>
      <div v-loading="previewLoading" class="knowledge-preview-body">
        <el-input v-if="previewDocument" v-model="previewQuery" clearable placeholder="在当前文档中搜索标题或内容" class="knowledge-preview-search" />
        <article v-for="chunk in filteredChunks" :key="chunk.id" class="knowledge-chunk-card">
          <header><span>分段 {{ chunk.chunk_index + 1 }}</span><strong>{{ chunk.section || '正文内容' }}</strong><small v-if="chunk.page_number">第 {{ chunk.page_number }} 页</small></header>
          <p>{{ chunk.content }}</p>
        </article>
        <div v-if="previewDocument && !filteredChunks.length" class="knowledge-empty">没有找到包含“{{ previewQuery }}”的知识内容</div>
      </div>
    </el-drawer>
  </div>
</template>
