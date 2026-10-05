<template>
  <div class="login-page">
    <!-- 背景装饰 -->
    <div class="bg-deco deco-1"></div>
    <div class="bg-deco deco-2"></div>
    <div class="bg-deco deco-3"></div>

    <div class="login-card">
      <!-- 左侧品牌区 -->
      <div class="brand-panel">
        <div class="brand-head">
          <div class="logo">⚖</div>
          <div class="brand-name">
            <h1>明镜</h1>
            <p>要素式智能受理系统</p>
          </div>
        </div>
        <p class="slogan">让每一起纠纷的受理，快一步、准一分。</p>
        <ul class="features">
          <li><span class="dot"></span>要素式立案，智能提取案件要素</li>
          <li><span class="dot"></span>法条案例混合检索，RAG 智能助手</li>
          <li><span class="dot"></span>文书自动生成，复核签发一键流转</li>
        </ul>
        <div class="brand-footer">Intelligent Case Intake Platform</div>
      </div>

      <!-- 右侧表单区 -->
      <div class="form-panel">
        <h2>欢迎登录</h2>
        <p class="form-tip">请输入账号和密码进入受理工作台</p>

        <el-form :model="form" size="large" @submit.prevent="handleLogin">
          <el-form-item>
            <el-input v-model="form.username" placeholder="账号" clearable @keyup.enter="handleLogin" />
          </el-form-item>
          <el-form-item>
            <el-input v-model="form.password" type="password" placeholder="密码" show-password
                      @keyup.enter="handleLogin" />
          </el-form-item>
          <el-form-item>
            <el-button class="login-btn" type="primary" :loading="loading" @click="handleLogin">
              {{ loading ? '登录中…' : '登 录' }}
            </el-button>
          </el-form-item>
        </el-form>

        <div class="demo-tip">演示账号：zhangming / 123456（受理员），admin 或 lisi / admin123（管理员）</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { login } from '../api/auth.js'

const emit = defineEmits(['login-success'])

const form = reactive({ username: '', password: '' })
const loading = ref(false)

async function handleLogin() {
  if (!form.username.trim() || !form.password) {
    ElMessage.warning('请输入账号和密码')
    return
  }
  loading.value = true
  try {
    const data = await login({ username: form.username.trim(), password: form.password })
    ElMessage.success(`欢迎回来，${data.user.name}`)
    emit('login-success', data)
  } catch (err) {
    ElMessage.error(err.message || '登录失败，请稍后重试')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #0e1c38 0%, #1d3a6e 55%, #2b5fad 100%);
  position: relative;
  overflow: hidden;
}
.bg-deco {
  position: absolute;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.045);
  pointer-events: none;
}
.deco-1 { width: 560px; height: 560px; top: -180px; left: -140px; }
.deco-2 { width: 420px; height: 420px; bottom: -140px; right: -100px; }
.deco-3 { width: 220px; height: 220px; bottom: 120px; left: 22%; background: rgba(255, 255, 255, 0.03); }

.login-card {
  display: flex;
  width: 860px;
  max-width: 92vw;
  min-height: 520px;
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.4);
  position: relative;
  z-index: 1;
}

/* 左侧品牌区 */
.brand-panel {
  width: 44%;
  padding: 52px 44px;
  display: flex;
  flex-direction: column;
  background: linear-gradient(160deg, rgba(43, 95, 173, 0.35) 0%, rgba(14, 28, 56, 0.55) 100%);
  backdrop-filter: blur(4px);
  color: #fff;
}
.brand-head { display: flex; align-items: center; gap: 14px; }
.logo {
  width: 54px; height: 54px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.14);
  border: 1px solid rgba(255, 255, 255, 0.25);
  display: flex; align-items: center; justify-content: center;
  font-size: 28px;
}
.brand-name h1 { margin: 0; font-size: 30px; letter-spacing: 6px; }
.brand-name p { margin: 4px 0 0; font-size: 13px; letter-spacing: 2px; color: rgba(255, 255, 255, 0.75); }
.slogan { margin: 44px 0 26px; font-size: 17px; line-height: 1.8; color: rgba(255, 255, 255, 0.92); }
.features { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 16px; font-size: 13.5px; color: rgba(255, 255, 255, 0.8); }
.features li { display: flex; align-items: center; gap: 10px; }
.dot { width: 6px; height: 6px; border-radius: 50%; background: #7db2ff; box-shadow: 0 0 8px #7db2ff; flex: none; }
.brand-footer { margin-top: auto; font-size: 12px; letter-spacing: 3px; color: rgba(255, 255, 255, 0.4); }

/* 右侧表单区 */
.form-panel {
  flex: 1;
  background: #fff;
  padding: 56px 56px 40px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}
.form-panel h2 { margin: 0 0 8px; font-size: 24px; color: #1f2d3d; }
.form-tip { margin: 0 0 30px; font-size: 13px; color: #909399; }
.login-btn { width: 100%; font-size: 15px; letter-spacing: 8px; }
.demo-tip {
  margin-top: 8px;
  padding: 9px 12px;
  font-size: 12px;
  color: #4a5b76;
  background: #f0f5fc;
  border-radius: 6px;
  text-align: center;
}

@media (max-width: 760px) {
  .brand-panel { display: none; }
  .form-panel { padding: 40px 32px; }
}
</style>
