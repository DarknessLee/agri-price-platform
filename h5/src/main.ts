import { createPinia } from 'pinia';
import { createApp } from 'vue';
import Vant from 'vant';

import 'vant/lib/index.css';
import '@/styles/index.css';

import App from './App.vue';
import router from './router';

const app = createApp(App);
app.use(createPinia());
app.use(router);
// 全局注册 Vant 组件：TabLayout 与各页面使用 van-* 标签，避免运行时无法解析组件
app.use(Vant);
app.mount('#app');
