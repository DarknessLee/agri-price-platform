import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/Login.vue'),
    meta: { title: '登录', public: true },
  },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'dashboard',
        component: () => import('@/views/Dashboard.vue'),
        meta: { title: '综合驾驶舱', group: '总览', permission: 'dashboard:view', icon: 'Odometer' },
      },
      {
        path: 'monitor/prices',
        name: 'monitor-prices',
        component: () => import('@/views/monitor/PriceMonitor.vue'),
        meta: { title: '价格监测', group: '价格监测', permission: 'monitor:view', icon: 'TrendCharts' },
      },
      {
        path: 'monitor/analysis',
        name: 'monitor-analysis',
        component: () => import('@/views/monitor/Analysis.vue'),
        meta: { title: '监测分析', group: '价格监测', permission: 'monitor:view', icon: 'DataAnalysis' },
      },
      {
        path: 'forecast/short',
        name: 'forecast-short',
        component: () => import('@/views/forecast/ShortForecast.vue'),
        meta: { title: '短期预测', group: '预测分析', permission: 'forecast:view', icon: 'Aim' },
      },
      {
        path: 'forecast/batch',
        name: 'forecast-batch',
        component: () => import('@/views/forecast/BatchForecast.vue'),
        meta: { title: '批量预测', group: '预测分析', permission: 'forecast:view', icon: 'Files' },
      },
      {
        path: 'forecast/models',
        name: 'forecast-models',
        component: () => import('@/views/forecast/ModelManage.vue'),
        meta: { title: '模型管理', group: '预测分析', permission: 'forecast:view', icon: 'Cpu' },
      },
      {
        path: 'forecast/drift',
        name: 'forecast-drift',
        component: () => import('@/views/forecast/ModelDrift.vue'),
        meta: { title: '模型监测', group: '预测分析', permission: 'forecast:view', icon: 'Monitor' },
      },
      {
        path: 'alert/list',
        name: 'alert-list',
        component: () => import('@/views/alert/AlertList.vue'),
        meta: { title: '预警信息', group: '预警处置', permission: 'alert:view', icon: 'Warning' },
      },
      {
        path: 'alert/rules',
        name: 'alert-rules',
        component: () => import('@/views/alert/AlertRules.vue'),
        meta: { title: '预警规则', group: '预警处置', permission: 'alert:view', icon: 'SetUp' },
      },
      {
        path: 'scenario',
        name: 'scenario',
        component: () => import('@/views/scenario/ScenarioSim.vue'),
        meta: { title: '情景推演', group: '情景与报告', permission: 'scenario:view', icon: 'MagicStick' },
      },
      {
        path: 'report',
        name: 'report',
        component: () => import('@/views/report/ReportCenter.vue'),
        meta: { title: '分析报告', group: '情景与报告', permission: 'report:view', icon: 'Document' },
      },
      {
        path: 'data/sources',
        name: 'data-sources',
        component: () => import('@/views/data/DataSource.vue'),
        meta: { title: '数据源管理', group: '数据治理', permission: 'data:view', icon: 'Coin' },
      },
      {
        path: 'data/quality',
        name: 'data-quality',
        component: () => import('@/views/data/Quality.vue'),
        meta: { title: '数据质量', group: '数据治理', permission: 'data:view', icon: 'CircleCheck' },
      },
      {
        path: 'data/import',
        name: 'data-import',
        component: () => import('@/views/data/ImportData.vue'),
        meta: { title: '数据导入', group: '数据治理', permission: 'data:view', icon: 'Upload' },
      },
      {
        path: 'admin/users',
        name: 'admin-users',
        component: () => import('@/views/admin/Users.vue'),
        meta: { title: '用户管理', group: '系统管理', permission: 'admin:user', icon: 'User' },
      },
      {
        path: 'admin/roles',
        name: 'admin-roles',
        component: () => import('@/views/admin/Roles.vue'),
        meta: { title: '角色权限', group: '系统管理', permission: 'admin:role', icon: 'Lock' },
      },
      {
        path: 'admin/base',
        name: 'admin-base',
        component: () => import('@/views/admin/BaseData.vue'),
        meta: { title: '基础数据', group: '系统管理', permission: 'admin:base', icon: 'Grid' },
      },
      {
        path: 'admin/audit',
        name: 'admin-audit',
        component: () => import('@/views/admin/AuditLogs.vue'),
        meta: { title: '操作审计', group: '系统管理', permission: 'admin:audit', icon: 'Memo' },
      },
      {
        path: 'admin/tasks',
        name: 'admin-tasks',
        component: () => import('@/views/admin/Tasks.vue'),
        meta: { title: '任务调度', group: '系统管理', permission: 'admin:task', icon: 'Timer' },
      },
      {
        path: 'admin/monitor',
        name: 'admin-monitor',
        component: () => import('@/views/admin/Monitor.vue'),
        meta: { title: '系统监控', group: '系统管理', permission: 'admin:task', icon: 'Monitor' },
      },
      {
        path: 'open-api',
        name: 'open-api',
        component: () => import('@/views/OpenApi.vue'),
        meta: { title: '开放 API', group: '系统管理', icon: 'Connection' },
      },
    ],
  },
  {
    path: '/screen',
    name: 'screen',
    component: () => import('@/views/Screen.vue'),
    meta: { title: '数据大屏', permission: 'dashboard:view' },
  },
  {
    path: '/forbidden',
    name: 'forbidden',
    component: () => import('@/views/Forbidden.vue'),
    meta: { title: '无权访问' },
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/NotFound.vue'),
    meta: { title: '页面不存在' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (to.meta.public) {
    if (auth.isLoggedIn && to.name === 'login') return { path: '/dashboard' }
    return true
  }
  if (!auth.isLoggedIn) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (!auth.user) {
    try {
      await auth.fetchMe()
    } catch {
      auth.reset()
      return { path: '/login', query: { redirect: to.fullPath } }
    }
  }
  const permission = to.meta.permission as string | undefined
  if (permission && !auth.hasPerm(permission)) {
    return { path: '/forbidden', query: { from: to.fullPath } }
  }
  return true
})

router.afterEach((to) => {
  const title = (to.meta.title as string) || ''
  document.title = title ? `${title} · 农产品价格监测预测分析平台` : '农产品价格监测预测分析平台'
})

export default router
