<template>
  <div class="state-page">
    <el-result icon="info" title="页面不存在" sub-title="您访问的地址不存在或已被调整，请从左侧菜单重新进入。">
      <template #extra>
        <el-button type="primary" @click="$router.replace('/dashboard')">返回驾驶舱</el-button>
      </template>
    </el-result>
  </div>
</template>

<style scoped>
.state-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  background: var(--ap-bg);
}
</style>
