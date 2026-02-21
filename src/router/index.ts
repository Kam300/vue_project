import { createRouter, createWebHistory } from 'vue-router'
import { useAppStore } from '@/stores/appStore'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'landing',
      component: () => import('@/views/LandingView.vue')
    },
    {
      path: '/app',
      component: () => import('@/layouts/AppShell.vue'),
      children: [
        {
          path: '',
          redirect: '/app/members'
        },
        {
          path: 'members',
          name: 'members',
          component: () => import('@/views/app/MembersView.vue')
        },
        {
          path: 'members/new',
          name: 'member-new',
          component: () => import('@/views/app/MemberEditorView.vue')
        },
        {
          path: 'members/:id',
          name: 'member-edit',
          component: () => import('@/views/app/MemberEditorView.vue')
        },
        {
          path: 'tree',
          name: 'tree',
          component: () => import('@/views/app/TreeView.vue')
        },
        {
          path: 'photos',
          name: 'photos',
          component: () => import('@/views/app/PhotosAiView.vue')
        },
        {
          path: 'export',
          name: 'export',
          component: () => import('@/views/app/ExportImportView.vue')
        },
        {
          path: 'backup',
          name: 'backup',
          component: () => import('@/views/app/BackupView.vue')
        },
        {
          path: 'server',
          name: 'server',
          component: () => import('@/views/app/ServerPanelView.vue')
        },
        {
          path: 'settings',
          name: 'settings',
          component: () => import('@/views/app/SettingsView.vue')
        },
        {
          path: 'about',
          name: 'about',
          component: () => import('@/views/app/AboutView.vue')
        },
        {
          path: 'onboarding',
          name: 'onboarding',
          component: () => import('@/views/app/OnboardingView.vue')
        },
        {
          path: 'lock',
          name: 'lock',
          component: () => import('@/views/app/LockView.vue')
        }
      ]
    }
  ]
})

router.beforeEach(async (to) => {
  const appStore = useAppStore()
  if (!appStore.initialized) {
    await appStore.init()
  }

  const inAppScope = to.path.startsWith('/app')
  if (!inAppScope) return true

  const onboardingRoutes = new Set(['/app/onboarding'])
  const lockRoute = '/app/lock'

  if (appStore.requiresOnboarding && !onboardingRoutes.has(to.path)) {
    return '/app/onboarding'
  }

  if (!appStore.requiresOnboarding && onboardingRoutes.has(to.path)) {
    return '/app/members'
  }

  if (appStore.requiresLock && to.path !== lockRoute) {
    return '/app/lock'
  }

  if (!appStore.requiresLock && to.path === lockRoute) {
    return '/app/members'
  }

  return true
})

export default router
