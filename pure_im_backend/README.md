# Pure IM Backend

这是一个独立开发的即时通信与 AI 知识库项目后端，基于 FastAPI、MongoDB、Milvus 和本地 BGE-M3，提供即时通信、群聊 AI 和知识库检索能力。

## 当前功能

### 即时通信

- WebSocket 群聊和私聊
- 多用户、多设备同时在线
- 消息持久化、历史消息和离线消息
- 消息撤回、删除、引用和转发
- 好友、群组、群成员和管理员管理
- 群公告、禁言、置顶和未读消息
- WebSocket 心跳、在线状态和消息广播

### AI 对话

- 平台统一配置 AI 服务，用户不需要填写 API Key
- OpenAI-compatible AI 接口调用
- 群聊中触发 AI 回复
- AI 回复流式生成和增量广播
- 同群成员可以实时看到 AI 生成过程
- 停止 AI 生成
- AI 调用日志和 Token 统计
- AI 消息引用触发它的用户消息
- 成功完成的群聊 AI 问答自动保存为历史 QA

### 知识库和检索

- 创建、修改和删除知识库
- 上传 PDF、DOCX、PPTX、XLSX、CSV、TXT、MD 文件
- 文档解析和 Chunk 切分
- 使用本地 BGE-M3 生成 Dense/Sparse 向量
- 使用 Milvus 保存和检索文件 Chunk
- 保存并检索群聊历史 AI 问答
- BM25 关键词检索
- Dense 向量检索
- 使用 RRF 融合 BM25 和 Dense 排名
- 使用 BGE Reranker 对融合结果重排
- Embedding、Milvus 和 Reranker 不可用时支持降级

FAQ 自动抽取功能目前暂缓，后续再根据练习需要补充。

绑定知识库的群聊已经支持将检索结果拼接到 RAG Prompt，并以非流式方式生成带引用来源的 AI 回复；未绑定知识库的群聊继续使用普通 AI 流式回复。

## 技术栈

- Python 3.10
- FastAPI
- Uvicorn
- MongoDB 7
- Milvus 2.5
- etcd
- MinIO
- Vue 3 前端
- BGE-M3：`BAAI/bge-m3`
- BGE Reranker：`BAAI/bge-reranker-v2-m3`
- `rank-bm25`

## 快速启动

### 1. 启动 Docker 依赖

项目中的 `docker-compose.yml` 会统一启动 MongoDB、etcd、MinIO 和 Milvus。

如果是第一次使用，先创建 Compose 使用的 MongoDB 外部数据卷：

```powershell
docker volume create mongodb_data
```

然后启动全部依赖：

```powershell
Set-Location -LiteralPath "D:\Lenovo\桌面\IM\IM_backend\pure_im_backend"
docker compose up -d
docker compose ps
```

服务端口：

| 服务 | 地址 |
|---|---|
| MongoDB | `localhost:27017` |
| Milvus | `http://127.0.0.1:19530` |
| MinIO API | `http://127.0.0.1:9000` |
| MinIO 控制台 | `http://127.0.0.1:9001` |

停止依赖：

```powershell
docker compose down
```

`volumes/` 和 Docker 数据卷用于保存运行数据，不要提交到 Git。

### 2. 创建 Python 环境并安装依赖

在 Anaconda Prompt 中执行：

```powershell
conda create -n im-backend python=3.10 -y
conda activate im-backend
Set-Location -LiteralPath "D:\Lenovo\桌面\IM\IM_backend\pure_im_backend"
python -m pip install -r requirements.txt
python -m pip check
```

如果环境已经创建，只需要执行：

```powershell
conda activate im-backend
Set-Location -LiteralPath "D:\Lenovo\桌面\IM\IM_backend\pure_im_backend"
python -m pip install -r requirements.txt
```

### 3. 配置环境变量

复制 `.env.example` 为 `.env`，至少配置平台 AI 服务：

```dotenv
AI_PROVIDER=openai_compatible
AI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
AI_API_KEY=your-ai-api-key
AI_MODEL_NAME=qwen-plus
```

Embedding 默认使用本地 BGE-M3：

```dotenv
EMBEDDING_PROVIDER=local_bge_m3
BGE_M3_MODEL_NAME=BAAI/bge-m3
BGE_M3_DEVICE=auto
BGE_M3_USE_FP16=False
```

Milvus 默认连接本机 Docker 服务：

```dotenv
MILVUS_URI=http://127.0.0.1:19530
MILVUS_DB_NAME=default
MILVUS_FILE_CHUNKS_COLLECTION=file_chunks
MILVUS_CHAT_HISTORY_QA_COLLECTION=chat_history_qa
```

BGE-M3 和 Reranker 使用懒加载，第一次执行向量化或重排时可能会从 Hugging Face 下载模型。

### 4. 启动后端

```powershell
conda activate im-backend
Set-Location -LiteralPath "D:\Lenovo\桌面\IM\IM_backend\pure_im_backend"
python run.py
```

启动后：

- API 文档：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/health`
- WebSocket：`ws://127.0.0.1:8000/api/chat/ws/{token}`

### 5. 启动前端

在新的 PowerShell 窗口执行：

```powershell
Set-Location -LiteralPath "D:\Lenovo\桌面\IM\IM_front\front_IM"
npm install
npm run dev
```

前端默认地址：

```text
http://127.0.0.1:5173
```

前端可以通过以下环境变量修改后端地址：

```dotenv
VITE_API_BASE=http://127.0.0.1:8000
VITE_WS_BASE=ws://127.0.0.1:8000
```

## 常用 AI 和检索接口

| 接口 | 说明 |
|---|---|
| `GET /api/ai/health` | AI 服务健康检查 |
| `GET /api/ai/provider-config` | 查看平台 AI 配置状态 |
| `GET /api/ai/usage/stats` | 查看当前用户 AI 调用和 Token 统计 |
| `POST /api/ai/chat` | 最小 AI 聊天接口 |
| `PUT /api/chat/stop` | 停止群聊 AI 流式生成 |
| `POST /api/chat/history-qa/search` | 检索当前群聊历史 AI 问答 |
| `GET /api/vector/embedding/health` | Embedding 健康检查 |
| `POST /api/vector/embedding/test` | 测试文本向量化 |
| `GET /api/vector/milvus/health` | Milvus 健康检查 |
| `POST /api/vector/milvus/file-chunks/initialize` | 初始化文件 Chunk 向量集合 |
| `POST /api/knowledge-bases/{id}/search` | 检索知识库文件 Chunk |

## 群聊 AI 流程

```text
用户在群聊发送问题
    -> 保存用户消息
    -> 群聊未绑定知识库：使用普通 AI 流式回复
    -> 群聊已绑定知识库：检索 Chunk、拼装 RAG Prompt
    -> 非流式调用 AI，保存带 citations 的 AI 消息
    -> AI 成功结束后保存聊天历史 QA
    -> 使用 BGE-M3 向量化问题并写入 chat_history_qa
```

停止生成或 AI 调用失败时，不会保存历史 QA。

## 检索流程

```text
用户输入 query
    -> BM25 关键词召回
    -> Dense 向量召回
    -> RRF 融合和去重
    -> Reranker 重排
    -> 返回 top_n 结果
```

知识库文件 Chunk 和聊天历史 QA 使用不同的 Milvus 集合：

- `file_chunks`：知识库文件 Chunk
- `chat_history_qa`：群聊历史 AI 问答

## 目录结构

```text
pure_im_backend/
├── app/
│   ├── models/                  # MongoDB 业务模型
│   ├── routes/                  # FastAPI 路由
│   ├── schemas/                # 请求和响应模型
│   ├── utils/
│   │   ├── ai_service.py       # 平台 AI 调用
│   │   ├── embedding_service.py# BGE-M3 Embedding
│   │   ├── milvus_service.py   # Milvus 集合、写入和检索
│   │   ├── bm25.py             # rank-bm25 适配器
│   │   ├── hybrid_search.py    # RRF 融合
│   │   ├── reranker_service.py # BGE Reranker
│   │   ├── knowledge_base_*.py # 文件解析、切分、向量化和检索
│   │   └── chat_history_qa.py  # 历史 QA 保存和检索
│   ├── config.py               # 配置
│   ├── database.py             # MongoDB 连接
│   └── main.py                 # FastAPI 应用入口
├── scripts/                    # 测试数据脚本
├── static/                     # 静态资源
├── templates/                  # 模板
├── uploads/                    # 上传文件运行目录
├── volumes/                    # Milvus 运行数据，不提交
├── docker-compose.yml          # MongoDB、Milvus 依赖
├── requirements.txt            # Python 依赖
├── run.py                      # 后端启动脚本
└── README.md
```

## 数据库

MongoDB 使用两个数据库：

- `xboom`：用户、群组、知识库、文件、AI 调用日志和聊天历史 QA
- `chat`：每个群组一个消息集合

Milvus 使用两个主要集合：

- `file_chunks`
- `chat_history_qa`
