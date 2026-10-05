# 明镜 · 要素式智能受理系统

> 面向人民调解受理工位的 AI 辅助系统，集成大模型对话、会话记忆持久化、流式输出与知识库检索能力。

## 技术栈

| 层级 | 技术 |
|---|---|
| 后端 | Python 3.14 / FastAPI / Uvicorn |
| 前端 | Vue 3 / Vite / Element Plus |
| 数据库 | MySQL 8（真相源）+ Redis（热缓存） |
| LLM | DeepSeek API（主）/ Ollama 本地模型（兜底降级） |
| 鉴权 | JWT (HS256) + bcrypt 密码哈希 |
| 检索 | BM25 + jieba 分词（RAG 基础组件） |

## 核心功能

- **AI 助手对话**：SSE 流式输出，逐 token 渲染，支持多轮上下文
- **会话记忆持久化**：MySQL + Redis 两层存储，支持降级与回放
- **会话管理**：历史会话列表、切换、删除，越权防护
- **登录鉴权**：JWT 单 token 方案，基于角色的接口隔离
- **采纳回流**：AI 回答的引用内容可一键采纳到案件文档

## 架构设计

### 会话记忆：MySQL + Redis 两层存储

```
用户发消息
    │
    ├─→ 写 Redis（微秒级热缓存）──────┐
    │                                  │
    └─→ 写 MySQL（真相源，异步）       │
                                       │
读取会话 ─→ Redis 命中 ──→ 直接返回    │
        └→ Redis 未命中 ─→ MySQL 回填 ─┘
        └→ Redis 异常   ─→ 降级直查 MySQL
```

- **Redis**：近 10 轮消息热缓存 + 用户会话索引，TTL 自动过期
- **MySQL**：所有会话与消息的永久保存，外键级联删除
- **降级策略**：Redis 故障时自动切 MySQL，保证服务不中断

### LLM 网关：云端 API → 本地 Ollama 降级链

```
请求 → 云端 DeepSeek API（主）
         └─ 失败 → Ollama 本地模型（兜底）
```

## 目录结构

```
mingjing-intake/
├── app/
│   ├── main.py              # FastAPI 入口，启动预热（Redis/LLM 客户端）
│   ├── api/                 # 接口层
│   │   ├── auth.py          #   登录 / 当前用户
│   │   ├── cases.py         #   案件列表
│   │   └── assist.py        #   AI 助手 5 接口（chat 为 SSE 流式）
│   ├── core/                # 基础能力
│   │   ├── config.py        #   环境配置读取
│   │   ├── db.py            #   MySQL 连接封装
│   │   ├── redis.py         #   Redis 连接池
│   │   ├── security.py      #   bcrypt + JWT
│   │   ├── deps.py          #   登录态依赖
│   │   └── id_gen.py        #   会话 ID 生成
│   ├── services/
│   │   └── session_service.py  # 会话记忆服务（Redis+MySQL 双写、降级、回放）
│   ├── llm/
│   │   └── provider.py      # LLM 网关（云端→本地降级链）
│   └── schemas/             # Pydantic 请求/响应模型
│
├── frontend/                # Vue3 + Vite 前端
│   ├── src/
│   │   ├── api/             # 接口封装（auth / cases / assist）
│   │   ├── components/
│   │   │   └── AiAssistantDrawer.vue  # AI 助手悬浮抽屉（SSE 流式 + 会话列表）
│   │   ├── views/           # 登录页 / 案件列表页
│   │   └── App.vue
│   └── dist/                # 构建产物，由后端同源托管
│
├── .env.example             # 环境变量模板
├── requirements.txt         # Python 依赖
└── 说明.md                  # 详细目录说明
```

## 快速开始

### 1. 环境准备

- Python 3.12+
- MySQL 8.0+
- Redis 6.0+

### 2. 后端启动

```bash
# 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env，填入 MySQL/Redis/LLM API Key 等配置

# 建库建表（执行 app 对应的 SQL，见说明文档）

# 启动
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

### 3. 前端启动

```bash
cd frontend
npm install
npm run dev      # 开发模式，访问 http://localhost:5173
# 或
npm run build    # 构建后由后端托管，访问 http://localhost:8000
```

## 安全设计

- 密码 bcrypt（cost=12）单向哈希，随机盐
- JWT 载荷不含密码，默认 24 小时过期
- 所有会话接口校验归属，防止越权访问
- .env 不入库，敏感配置与代码分离

## 特色亮点

1. **真流式输出**：基于 SSE + 生成器，LLM 逐 token 推送，首 token 延迟 < 1s
2. **两级存储降级**：Redis 挂了自动切 MySQL，会话数据零丢失
3. **启动预热**：服务启动时预建 Redis 连接与 LLM 客户端，消除首次请求冷启动
4. **LLM 降级链**：云端 API 故障自动 fallback 到本地 Ollama，保障可用性
