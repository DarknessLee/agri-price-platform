<template>
  <div class="h5-shell">
    <router-view v-slot="{ Component }">
      <keep-alive>
        <component :is="Component" />
      </keep-alive>
    </router-view>
    <van-tabbar v-model="active" route safe-area-inset-bottom active-color="#1f5fd6" inactive-color="#8a94a6">
      <van-tabbar-item to="/" icon="wap-home-o">首页</van-tabbar-item>
      <van-tabbar-item to="/prices" icon="chart-trending-o">行情</van-tabbar-item>
      <van-tabbar-item to="/forecast" icon="bar-chart-o">预测</van-tabbar-item>
      <van-tabbar-item to="/alerts" icon="warning-o">预警</van-tabbar-item>
      <van-tabbar-item to="/me" icon="user-o">我的</van-tabbar-item>
    </van-tabbar>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue';

const active = ref(0);
</script>

<style scoped>
.h5-shell {
  min-height: 100vh;
  padding-bottom: calc(56px + env(safe-area-inset-bottom));
  background: #f4f6fa;
  box-sizing: border-box;
}
</style>
