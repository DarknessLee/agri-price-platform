<template>
  <div class="h5-shell">
    <router-view v-slot="{ Component }">
      <keep-alive>
        <component :is="Component" />
      </keep-alive>
    </router-view>
    <van-tabbar route safe-area-inset-bottom active-color="#1f5fd6" inactive-color="#8a94a6">
      <van-tabbar-item :to="{ name: 'home' }" icon="wap-home-o">首页</van-tabbar-item>
      <van-tabbar-item :to="{ name: 'prices' }" icon="chart-trending-o">行情</van-tabbar-item>
      <van-tabbar-item :to="{ name: 'forecast' }" icon="bar-chart-o">预测</van-tabbar-item>
      <van-tabbar-item :to="{ name: 'alerts' }" icon="warning-o">预警</van-tabbar-item>
      <van-tabbar-item :to="{ name: 'me' }" icon="user-o">我的</van-tabbar-item>
    </van-tabbar>
  </div>
</template>

<style scoped>
.h5-shell {
  min-height: 100vh;
  padding-bottom: calc(56px + env(safe-area-inset-bottom));
  background: #f4f6fa;
  box-sizing: border-box;
}
</style>
