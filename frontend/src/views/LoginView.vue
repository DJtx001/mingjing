<template>
  <div class="login-page">
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

        <div class="demo-tip">演示账号：lisi 密码：123456（普通用户，对知识库的权限仅查看与上传）如有问题联系管理员3112028466@qq.com</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
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
  justify-content: flex-end;                /* 卡片右置：左侧与中部让给背景画面 */
  padding-right: clamp(12px, 1.5vw, 30px);  /* 卡片再次贴右 */
  /* 天平背景图：恢复全屏铺满（cover），焦点保留微偏左 */
  background:
    url('../assets/login-bg.jpg') 55% center / cover no-repeat,
    linear-gradient(135deg, #0e1c38 0%, #1d3a6e 55%, #2b5fad 100%);
  position: relative;
  overflow: hidden;
}

.login-card {
  display: flex;
  width: 860px;
  max-width: 92vw;
  min-height: 520px;
  border-radius: 20px;
  overflow: hidden;
  box-shadow: 0 24px 70px rgba(5, 15, 35, 0.5);
  position: relative;
  z-index: 1;
}

/* 左侧品牌区 */
.brand-panel {
  width: 44%;
  padding: 52px 44px;
  display: flex;
  flex-direction: column;
  /* 深蓝实底：完全不透明，与顶栏/主界面同族 */
  background: linear-gradient(160deg, #16294a 0%, #0b1a33 100%);
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
/* 「明镜」艺术字：楷体 + 金色渐变 + 光晕，呼应「明镜高悬」 */
.brand-name h1 {
  margin: 0;
  font-size: 44px;
  letter-spacing: 12px;
  text-indent: 12px;              /* 补偿字距造成的右侧空隙，视觉居中 */
  font-family: "STKaiti", "KaiTi", "楷体", serif;
  font-weight: 700;
  background: linear-gradient(180deg, #ffffff 15%, #f0dfae 55%, #d9b96a 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  color: transparent;
  filter: drop-shadow(0 2px 12px rgba(240, 223, 174, 0.4));
}
.brand-name h1::after {
  content: '';
  display: block;
  width: 76px;
  height: 2px;
  margin-top: 16px;
  text-indent: 0;
  background: linear-gradient(90deg, #d9b96a, rgba(217, 185, 106, 0));
}
.brand-name p { margin: 4px 0 0; font-size: 13px; letter-spacing: 2px; color: rgba(255, 255, 255, 0.75); }
.slogan {
  margin: 44px 0 26px;
  font-size: 17px;
  line-height: 1.8;
  letter-spacing: 1px;
  color: rgba(255, 255, 255, 0.92);
  font-family: "STZhongsong", "SimSun", "宋体", serif;
}
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
.login-btn {
  width: 100%; font-size: 15px; letter-spacing: 8px; border: none;
  background-image: linear-gradient(135deg, #2b5fad 0%, #4a80d4 100%);
  box-shadow: 0 6px 20px rgba(43, 95, 173, 0.38);
  transition: all 0.25s;
}
.login-btn:hover {
  box-shadow: 0 9px 26px rgba(43, 95, 173, 0.5);
  transform: translateY(-1px);
}
.demo-tip {
  margin-top: 8px;
  padding: 9px 12px;
  font-size: 15px;
  color: #4a5b76;
  background: #f0f5fc;
  border-radius: 6px;
  text-align: center;
}

/* 窄屏：卡片回居中（背景图仍铺满） */
@media (max-width: 1180px) {
  .login-page { justify-content: center; padding-right: 0; }
}
@media (max-width: 760px) {
  .brand-panel { display: none; }
  .form-panel { padding: 40px 32px; }
}
</style>
