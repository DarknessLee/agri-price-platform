<template>
  <div class="state-page">
    <el-result icon="warning" title="无权访问" sub-title="当前账号缺少该页面的访问权限，请联系系统管理员分配角色权限。">
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
  min-height: calc(100vh - 120px);
  background: #fff;
  border-radius: var(--ap-radius);
}
</style>
