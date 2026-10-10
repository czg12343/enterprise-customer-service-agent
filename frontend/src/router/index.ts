import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import AppLayout from '../layouts/AppLayout.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: () => import('../views/LoginView.vue') },
    {
      path: '/',
      component: AppLayout,
      meta: { requiresAuth: true },
      children: [
        { path: '', redirect: '/chat' },
        { path: 'chat', component: () => import('../views/ChatView.vue') },
        { path: 'orders', component: () => import('../views/OrdersView.vue') },
        {
          path: 'products',
          component: () => import('../views/ProductsView.vue'),
          meta: { roles: ['admin'] },
        },
        { path: 'tickets', component: () => import('../views/TicketsView.vue') },
        { path: 'retrieval', component: () => import('../views/RetrievalView.vue'), meta: { roles: ['service', 'admin'] } },
        {
          path: 'handoffs',
          component: () => import('../views/HandoffView.vue'),
          meta: { roles: ['service', 'admin'] },
        },
        {
          path: 'evaluation',
          component: () => import('../views/EvaluationView.vue'),
          meta: { roles: ['service', 'admin'] },
        },
        {
          path: 'admin',
          component: () => import('../views/AdminView.vue'),
          meta: { roles: ['service', 'admin'] },
        },
      ],
    },
  ],
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.meta.requiresAuth && !auth.isAuthenticated) return '/login'
  if (to.path === '/login' && auth.isAuthenticated) return '/chat'
  const roles = to.meta.roles as string[] | undefined
  if (roles && (!auth.user || !roles.includes(auth.user.role))) return '/chat'
})

export default router
