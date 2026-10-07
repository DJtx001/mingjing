# 明镜 · 要素式智能受理系统

> 面向人民调解受理工位的全栈 AI 辅助系统，集成 **RAG 检索增强**、**要素式受理引擎**、**双路混合召回**、**三级分流核验** 与 **会话记忆持久化** 能力，为基层调解员提供可溯源、可审计、低延迟的智能受理体验。

## 技术栈

| 层级 | 技术 |
|---|---|
| 后端 | Python 3.14 / FastAPI / Uvicorn |
| 前端 | Vue 3 / Vite / Element Plus |
| 数据库 | MySQL 8（真相源）+ Redis（热缓存） |
| 向量库 | Chroma（稠密向量，cosine 相似度，HNSW 索引） |
| Embedding | 阿里云 DashScope text-embedding-v3（1024 维，批处理 + 退避重试） |
| 对象存储 | 阿里云 OSS（法条/案例原文、附件、导出文书） |
| LLM | DeepSeek API（主）/ Ollama 本地模型（兜底降级） |
| 鉴权 | JWT (HS256) + bcrypt（cost=12）密码哈希 |
| 检索 | 向量语义召回 + 距离阈值过滤 + 案例父块上溯 |

## 核心功能

### 🤖 RAG 智能问答（检索增强生成）
- **双 Collection 向量库**：法条 `laws_v1` + 案例 `case_refs_v1` 独立索引，支持版本化重建
- **语义召回**：DashScope text-embedding-v3 向量化，cosine 距离阈值过滤（≤0.42 才采信），宁缺毋滥
- **案例父子块**：1 个父块摘要 + 4 个段（案情/诉请/结果/评析）子块，命中子块自动上溯父块，上下文更完整
- **引用溯源**：AI 回答带 `[1] [2]` 引用标注，点击直达法条原文 / 案例卡片，杜绝"幻觉"
- **采纳回流**：AI 引用的法条/案例可一键采纳进案件文档，形成数据闭环

### ⚖️ 要素式受理引擎（核心创新）
- **要素抽取**：LLM 按纠纷类型 Schema（民间借贷/物业/婚姻/侵权）从陈述中抽取要素，附**置信度**与**原文引句**
- **三层溯源·层①**：每个要素值回链到陈述原文 offset，受理员可核对"AI 从哪句话得出的"
- **人工确认双轨**：受理员确认/修正/标缺失，修正理由回流（数据飞轮），覆盖式重抽取保留审计
- **规则核验引擎**：R1~R7 硬规则（关键词匹配）+ 核心要素缺失检查 → **三级分流**：自动通过 / 待人工复核 / 建议不予受理
- **配置化不发版**：要素 Schema、抽取 Prompt、核验规则均存知识库表，改配置即生效

### 📊 统计分析
- **知识库维度**：法条/案例存量、向量灌库覆盖率、法律部门分布
- **AI 助手维度**：会话数、提问量、首 token 延迟、引用采纳率、无依据率、调用趋势

### 💬 AI 助手与会话
- **SSE 真流式输出**：逐 token 渲染，首 token 延迟 < 1s，引用卡片实时挂载
- **会话记忆持久化**：MySQL（真相源）+ Redis（热缓存）两层存储，Redis 故障自动降级
- **可拖动 AI 入口**：右下角悬浮胶囊按钮，自由拖动记忆位置
- **越权防护**：所有会话/案件接口校验归属，操作日志全程审计

### 📚 知识库管理
- 法条/案例 `.md` 文件解析入库（按条切分 / 四段式），原文备份 OSS
- PDF / 文本在线预览，规则 / Schema / 提示词可视化编辑
- 一键重建向量索引（reindex 后台任务，幂等可续跑，坏条自动隔离）

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

### RAG 检索链路：双路召回 + 引用溯源

```
用户提问
    │
    ▼
DashScope Embedding 向量化
    │
    ├─→ Chroma laws_v1（法条稠密检索）──┐
    │      cosine 距离 ≤0.42 阈值过滤    │
    ├─→ Chroma case_refs_v1（案例检索）─┤
    │      子块命中 → 上溯父块摘要        │
    │                                   ▼
    │                          build_context 拼装参考材料
    │                                   │
    ▼                                   ▼
DeepSeek LLM 生成回答 ←── 带 [1][2] 引用标注的 Prompt
    │
    ▼
SSE 流式返回（引用卡片实时挂载）
```

### 要素受理流程：抽取 → 确认 → 核验 → 分流

```
当事人陈述
    │
    ▼
LLM 要素抽取（Schema 驱动，附置信度 + 原文引句 offset）
    │
    ▼
受理员人工确认 / 修正 / 标缺失（理由回流）
    │
    ▼
R1~R7 规则引擎核验（关键词 + 核心要素缺失检查）
    │
    ├─→ auto_pass（自动通过）
    ├─→ pending_review（待人工复核）
    └─→ reject_suggestion（建议不予受理）
```

### 向量灌库：幂等可续跑的 reindex 任务

- 块 ID 由 MySQL 主键推导，重跑覆盖不重复
- 批处理容错：整批失败逐条重试，坏条隔离（`vector_synced=2`）不阻塞其余
- 中断后从 `vector_synced=0` 处自动续跑，无需任务队列

## 目录结构

```
mingjing-intake/
├── app/
│   ├── main.py              # FastAPI 入口，启动预热（Redis/LLM 客户端）
│   ├── api/                 # 接口层
│   │   ├── auth.py          #   登录 / 当前用户
│   │   ├── cases.py         #   案件列表 / 新建案件（触发要素抽取）
│   │   ├── assist.py        #   AI 助手（chat 为 SSE 流式，含 RAG 召回）
│   │   ├── intake.py        #   受理流程（要素表 / 核验报告 / 补充询问）
│   │   ├── kb.py            #   知识库管理（法条/案例/规则/Schema/提示词 + OSS 文件）
│   │   ├── stats.py         #   统计分析（知识库 / AI 助手使用）
│   │   └── logs.py          #   操作日志查询
│   ├── core/                # 基础能力
│   │   ├── config.py        #   环境配置读取（含 OSS / Embedding）
│   │   ├── db.py            #   MySQL 连接封装
│   │   ├── redis.py         #   Redis 连接池
│   │   ├── security.py      #   bcrypt + JWT
│   │   ├── deps.py          #   登录态依赖
│   │   └── id_gen.py        #   会话 ID 生成
│   ├── services/
│   │   ├── session_service.py   # 会话记忆服务（Redis+MySQL 双写、降级、回放）
│   │   ├── intake_service.py    # 受理流程引擎（要素抽取/核验分流/状态流转）
│   │   ├── retrieval_service.py # RAG 检索召回（向量+阈值过滤+引用拼装）
│   │   ├── reindex_service.py   # 向量灌库后台任务（幂等可续跑）
│   │   ├── vector_service.py    # Chroma 向量库（双 Collection）
│   │   ├── kb_parser.py         # 法条/案例 .md 解析器（按条/四段切分）
│   │   ├── oss_service.py       # 阿里云 OSS 上传/下载/删除/列表
│   │   └── audit_service.py     # 操作日志审计记录
│   ├── llm/
│   │   ├── provider.py      # LLM 网关（云端→本地降级链）
│   │   └── embedding.py     # Embedding 封装（批处理 + 退避重试）
│   └── schemas/             # Pydantic 请求/响应模型
│
├── frontend/                # Vue3 + Vite 前端
│   ├── src/
│   │   ├── api/             # 接口封装（auth / cases / assist / intake / kb / stats / logs）
│   │   ├── components/
│   │   │   └── AiAssistantDrawer.vue  # AI 助手悬浮抽屉（SSE 流式 + 可拖动入口 + 会话列表）
│   │   ├── views/           # 登录 / 案件列表 / 新建案件 / 知识库 / 统计 / 操作日志
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
# OSS 配置（可选，用于法条/案例文件存储）：
#   OSS_ACCESS_KEY_ID / OSS_ACCESS_KEY_SECRET
#   OSS_ENDPOINT=oss-cn-beijing.aliyuncs.com
#   OSS_BUCKET=your-bucket-name
# Embedding 配置（RAG 检索必需）：
#   EMBEDDING_API_KEY / EMBEDDING_BASE_URL（DashScope openai 兼容）
#   EMBEDDING_MODEL=text-embedding-v3

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

1. **可溯源的 RAG**：AI 回答每条引用都可点击直达法条原文 / 案例卡片，cosine 距离阈值过滤杜绝"弱相关硬引用"
2. **要素式受理引擎**：LLM 抽取 + 人工确认 + 规则核验三级分流，每个要素回链原文 offset，全程可审计
3. **案例父子块检索**：命中子块自动上溯父块摘要，检索精度与上下文完整性兼得
4. **幂等向量灌库**：坏条自动隔离、中断自动续跑，灌库任务可安全重跑
5. **真流式输出**：基于 SSE + 生成器，LLM 逐 token 推送，首 token 延迟 < 1s
6. **两级存储降级**：Redis 挂了自动切 MySQL，会话数据零丢失
7. **LLM 降级链**：云端 API 故障自动 fallback 到本地 Ollama，保障可用性
8. **配置化不发版**：要素 Schema、抽取 Prompt、核验规则全部存库，改配置即时生效
