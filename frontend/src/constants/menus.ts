import type { MenuNode } from '@/types'

export const FALLBACK_MENUS: MenuNode[] = [
  { key: 'dashboard', title: '综合驾驶舱', path: '/dashboard', icon: 'Odometer', permission: 'dashboard:view' },
  {
    key: 'monitor',
    title: '价格监测',
    path: '/monitor',
    icon: 'TrendCharts',
    permission: 'monitor:view',
    children: [
      { key: 'monitor-prices', title: '价格监测', path: '/monitor/prices', icon: 'DataLine', permission: 'monitor:view' },
      { key: 'monitor-analysis', title: '监测分析', path: '/monitor/analysis', icon: 'DataAnalysis', permission: 'monitor:view' },
    ],
  },
  {
    key: 'forecast',
    title: '预测分析',
    path: '/forecast',
    icon: 'Aim',
    permission: 'forecast:view',
    children: [
      { key: 'forecast-short', title: '短期预测', path: '/forecast/short', icon: 'Aim', permission: 'forecast:view' },
      { key: 'forecast-batch', title: '批量预测', path: '/forecast/batch', icon: 'Files', permission: 'forecast:view' },
      { key: 'forecast-models', title: '模型管理', path: '/forecast/models', icon: 'Cpu', permission: 'forecast:view' },
    ],
  },
  {
    key: 'alert',
    title: '预警处置',
    path: '/alert',
    icon: 'Warning',
    permission: 'alert:view',
    children: [
      { key: 'alert-list', title: '预警信息', path: '/alert/list', icon: 'Warning', permission: 'alert:view' },
      { key: 'alert-rules', title: '预警规则', path: '/alert/rules', icon: 'SetUp', permission: 'alert:view' },
    ],
  },
  {
    key: 'scenario-report',
    title: '情景与报告',
    path: '/scenario',
    icon: 'MagicStick',
    children: [
      { key: 'scenario', title: '情景推演', path: '/scenario', icon: 'MagicStick', permission: 'scenario:view' },
      { key: 'report', title: '分析报告', path: '/report', icon: 'Document', permission: 'report:view' },
    ],
  },
  {
    key: 'data',
    title: '数据治理',
    path: '/data',
    icon: 'Coin',
    permission: 'data:view',
    children: [
      { key: 'data-sources', title: '数据源管理', path: '/data/sources', icon: 'Coin', permission: 'data:view' },
      { key: 'data-quality', title: '数据质量', path: '/data/quality', icon: 'CircleCheck', permission: 'data:view' },
      { key: 'data-import', title: '数据导入', path: '/data/import', icon: 'Upload', permission: 'data:view' },
    ],
  },
  {
    key: 'admin',
    title: '系统管理',
    path: '/admin',
    icon: 'Setting',
    children: [
      { key: 'admin-users', title: '用户管理', path: '/admin/users', icon: 'User', permission: 'admin:user' },
      { key: 'admin-roles', title: '角色权限', path: '/admin/roles', icon: 'Lock', permission: 'admin:role' },
      { key: 'admin-base', title: '基础数据', path: '/admin/base', icon: 'Grid', permission: 'admin:base' },
      { key: 'admin-audit', title: '操作审计', path: '/admin/audit', icon: 'Memo', permission: 'admin:audit' },
      { key: 'admin-tasks', title: '任务调度', path: '/admin/tasks', icon: 'Timer', permission: 'admin:task' },
      { key: 'open-api', title: '开放 API', path: '/open-api', icon: 'Connection' },
    ],
  },
]
