import { createApp } from 'vue'
import { createPinia } from 'pinia'
import {
  ElButton,
  ElConfigProvider,
  ElDialog,
  ElDrawer,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElForm,
  ElFormItem,
  ElInput,
  ElLoading,
  ElOption,
  ElPopconfirm,
  ElRadioButton,
  ElRadioGroup,
  ElSelect,
  ElTable,
  ElTableColumn,
  ElTag,
  ElUpload,
} from 'element-plus'
import 'element-plus/dist/index.css'
import './styles/global.css'
import App from './App.vue'
import router from './router'

const app = createApp(App).use(createPinia()).use(router)
const components = [
  ElButton,
  ElConfigProvider,
  ElDialog,
  ElDrawer,
  ElDropdown,
  ElDropdownItem,
  ElDropdownMenu,
  ElForm,
  ElFormItem,
  ElInput,
  ElOption,
  ElPopconfirm,
  ElRadioButton,
  ElRadioGroup,
  ElSelect,
  ElTable,
  ElTableColumn,
  ElTag,
  ElUpload,
]
components.forEach((component) => app.use(component))
app.use(ElLoading)
app.mount('#app')
