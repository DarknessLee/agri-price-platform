import { createRouter, createWebHistory } from 'vue-router';

import TabLayout from '@/layouts/TabLayout.vue';
import { getToken } from '@/api/client';

const router = createRouter({
  history: createWebHistory('/m/'),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/Login.vue'),
      meta: { title: '登录', public: true },
    },
    {
      path: '/',
      component: TabLayout,
      children: [
        {
          path: '',
          name: 'home',
          component: () => import('@/views/Home.vue'),
          meta: { title: '首页', tab: 'home' },
        },
        {
          path: 'prices',
          name: 'prices',
          component: () => import('@/views/Prices.vue'),
          meta: { title: '价格行情', tab: 'prices' },
        },
        {
          path: 'forecast',
          name: 'forecast',
          component: () => import('@/views/Forecast.vue'),
          meta: { title: '价格预测', tab: 'forecast' },
        },
        {
          path: 'alerts',
          name: 'alerts',
          component: () => import('@/views/Alerts.vue'),
          meta: { title: '预警', tab: 'alerts' },
        },
        {
          path: 'me',
          name: 'me',
          component: () => import('@/views/Me.vue'),
          meta: { title: '我的', tab: 'me' },
        },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
});

router.beforeEach((to) => {
  const logged = Boolean(getToken());
  if (!to.meta.public && !logged) {
    return { path: '/login', query: { redirect: to.fullPath } };
  }
  if (to.path === '/login' && logged) {
    return { path: '/' };
  }
  document.title = to.meta.title ? `${to.meta.title} · 农产品价格平台` : '农产品价格平台';
  return true;
});

export default router;
