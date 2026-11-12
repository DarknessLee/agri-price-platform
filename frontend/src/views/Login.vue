<template>
  <div class="login-page">
    <div class="login-bg">
      <div class="glow glow-1" />
      <div class="glow glow-2" />
    </div>

    <div class="login-wrap">
      <section class="brand-panel">
        <div class="brand-head">
          <div class="brand-logo">农</div>
          <div>
            <h1>农产品价格监测预测分析平台</h1>
            <p>采集 · 治理 · 监测 · 预测 · 预警 · 决策支持</p>
          </div>
        </div>

        <ul class="feature-list">
          <li v-for="item in features" :key="item.title">
            <el-icon :size="18"><component :is="item.icon" /></el-icon>
            <div>
              <strong>{{ item.title }}</strong>
              <span>{{ item.desc }}</span>
            </div>
          </li>
        </ul>

        <div class="brand-foot">
          <span>数据覆盖 5 类农产品 · 6 个主产区 · 12 个重点市场</span>
          <span>日频价格序列持续更新</span>
        </div>
      </section>

      <section class="form-panel">
        <div class="form-card">
          <h2>账号登录</h2>
          <p class="form-sub">请使用单位分配的账号访问平台</p>

          <el-form ref="formRef" :model="form" :rules="rules" size="large" @submit.prevent>
            <el-form-item prop="username">
              <el-input v-model="form.username" placeholder="用户名" autocomplete="username" @keyup.enter="submit">
                <template #prefix><el-icon><User /></el-icon></template>
              </el-input>
            </el-form-item>
            <el-form-item prop="password">
              <el-input
                v-model="form.password"
                type="password"
                placeholder="密码"
                show-password
                autocomplete="current-password"
                @keyup.enter="submit"
              >
                <template #prefix><el-icon><Lock /></el-icon></template>
              </el-input>
            </el-form-item>
            <el-button type="primary" size="large" class="submit-btn" :loading="loading" @click="submit">
              登 录
            </el-button>
          </el-form>

          <div class="role-hint">
            <span class="hint-title">快捷填入</span>
            <div class="role-chips">
              <button v-for="acc in accounts" :key="acc.username" type="button" class="role-chip" @click="fill(acc)">
                {{ acc.label }}
              </button>
            </div>
            <p class="hint-note">初始管理员：admin / Admin@2026</p>
          </div>
        </div>
        <p class="copyright">农产品价格监测预测分析平台 · 信息中心</p>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const loading = ref(false)
const formRef = ref<FormInstance>()
const form = reactive({ username: 'admin', password: 'Admin@2026' })

const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

const features = [
  { icon: 'TrendCharts', title: '全链条价格监测', desc: '日频采集、同比环比、区域价差与季节波动实时呈现' },
  { icon: 'Aim', title: '多模型智能预测', desc: '季节分解、Holt-Winters、梯度提升与组合模型互为验证' },
  { icon: 'Warning', title: '分级预警闭环', desc: '规则引擎识别异常波动，处置流程全程留痕' },
]

const accounts = [
  { label: '系统管理员', username: 'admin', password: 'Admin@2026' },
  { label: '分析师', username: 'analyst01', password: 'Analyst@2026' },
  { label: '值班人员', username: 'operator01', password: 'Operator@2026' },
  { label: '观察员', username: 'viewer01', password: 'Viewer@2026' },
]

function fill(acc: { username: string; password: string }) {
  form.username = acc.username
  form.password = acc.password
}

async function submit() {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  loading.value = true
  try {
    await auth.login(form.username.trim(), form.password)
    ElMessage.success(`欢迎回来，${auth.displayName}`)
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/dashboard'
    router.replace(redirect)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '登录失败，请稍后重试')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 32px;
  background: radial-gradient(circle at 12% 18%, #1d3f78 0%, #101f38 45%, #0a1526 100%);
  overflow: hidden;
}

.login-bg .glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.5;
}

.glow-1 {
  width: 520px;
  height: 520px;
  background: #1f5fd6;
  top: -160px;
  left: -80px;
}

.glow-2 {
  width: 460px;
  height: 460px;
  background: #1c9c8b;
  bottom: -180px;
  right: -60px;
  opacity: 0.35;
}

.login-wrap {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1.05fr) minmax(360px, 0.95fr);
  width: min(1080px, 100%);
  min-height: 560px;
  border-radius: 20px;
  overflow: hidden;
  box-shadow: 0 30px 80px rgba(0, 0, 0, 0.45);
  background: rgba(13, 26, 48, 0.72);
  backdrop-filter: blur(10px);
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.brand-panel {
  display: flex;
  flex-direction: column;
  gap: 34px;
  padding: 46px 44px;
  color: #e7eefb;
}

.brand-head {
  display: flex;
  gap: 14px;
  align-items: flex-start;
}

.brand-logo {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 46px;
  height: 46px;
  border-radius: 12px;
  background: linear-gradient(135deg, #2f7bff, #17479f);
  font-size: 24px;
  font-weight: 700;
  color: #fff;
  flex-shrink: 0;
}

.brand-head h1 {
  margin: 0;
  font-size: 24px;
  letter-spacing: 1px;
  line-height: 1.35;
}

.brand-head p {
  margin: 8px 0 0;
  font-size: 13px;
  color: #9db0cd;
  letter-spacing: 2px;
}

.feature-list {
  display: flex;
  flex-direction: column;
  gap: 18px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.feature-list li {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.feature-list .el-icon {
  margin-top: 3px;
  color: #5b9bff;
}

.feature-list strong {
  display: block;
  font-size: 14px;
  font-weight: 600;
}

.feature-list span {
  display: block;
  margin-top: 4px;
  font-size: 12.5px;
  color: #93a7c6;
  line-height: 1.6;
}

.brand-foot {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: auto;
  font-size: 12px;
  color: #7f94b4;
}

.form-panel {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  padding: 46px 40px;
  background: #fff;
}

.form-card {
  width: 100%;
  max-width: 340px;
}

.form-card h2 {
  margin: 0;
  font-size: 24px;
  color: #16233a;
}

.form-sub {
  margin: 8px 0 26px;
  font-size: 13px;
  color: #8b9aae;
}

.submit-btn {
  width: 100%;
  margin-top: 6px;
  height: 44px;
  font-size: 15px;
  letter-spacing: 4px;
}

.role-hint {
  margin-top: 26px;
  padding-top: 18px;
  border-top: 1px dashed #e4e9f2;
}

.hint-title {
  font-size: 12px;
  color: #98a6b8;
}

.role-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.role-chip {
  padding: 5px 12px;
  border: 1px solid #dce4f0;
  border-radius: 14px;
  background: #f7f9fd;
  color: #41546e;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.role-chip:hover {
  border-color: var(--ap-primary);
  color: var(--ap-primary);
  background: #eef4ff;
}

.hint-note {
  margin: 10px 0 0;
  font-size: 12px;
  color: #a3b0c2;
}

.copyright {
  margin: 0;
  font-size: 12px;
  color: #a3b0c2;
}

@media (max-width: 900px) {
  .login-wrap {
    grid-template-columns: 1fr;
    min-height: 0;
  }

  .brand-panel {
    padding: 30px 26px 10px;
    gap: 22px;
  }

  .brand-foot {
    display: none;
  }

  .form-panel {
    padding: 26px;
  }
}
</style>
