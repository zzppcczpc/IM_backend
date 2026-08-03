# Pure IM Backend

从 DeepTalk 项目精简而来的纯IM系统后端，支持多人同时在线聊天。

## ✨ 功能特性

### 核心功能
- **WebSocket实时聊天** - 支持多人同时在线群聊
- **多设备登录** - 同一用户可多设备同时在线
- **消息持久化** - MongoDB存储，支持历史消息查询
- **消息撤回/删除** - 支持消息撤回和删除操作
- **好友系统** - 添加好友、好友请求审核
- **群组管理** - 创建群聊、成员管理、私聊

### 新增优化功能
- **在线状态显示** - 实时显示群组成员在线状态
- **消息发送确认** - 发送者收到消息送达确认
- **离线消息补发** - 断线重连后自动获取离线消息
- **心跳保活机制** - WebSocket长连接心跳检测
- **高效消息广播** - asyncio.gather并行广播
- **连接统计API** - 实时查看在线用户数和连接数

## 📡 WebSocket消息类型

| 类型 | 方向 | 说明 |
|------|------|------|
| `ping/pong` | 双向 | 心跳保活 |
| `text` | 客户端→服务器 | 发送文本消息 |
| `message` | 服务器→客户端 | 收到新消息 |
| `message_sent` | 服务器→客户端 | 消息发送成功确认 |
| `revoke` | 双向 | 撤回消息 |
| `delete` | 双向 | 删除消息 |
| `new` | 双向 | 新话题标记 |
| `connected` | 服务器→客户端 | 连接成功确认 |
| `user_join` | 服务器→客户端 | 用户加入通知 |
| `user_leave` | 服务器→客户端 | 用户离开通知 |
| `online_users` | 双向 | 在线用户列表 |
| `history` | 双向 | 历史消息 |
| `offline_messages` | 服务器→客户端 | 离线消息补发 |

## 🚀 快速启动

```bash
# 1. 进入目录
cd pure_im_backend

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env，配置MongoDB连接和密钥

# 4. 启动服务
python run.py
```

启动后：
- API文档: http://localhost:8000/docs
- WebSocket: ws://localhost:8000/api/chat/ws/{token}
- 健康检查: http://localhost:8000/health

## 📁 目录结构

```
pure_im_backend/
├── app/
│   ├── models/              # 数据模型
│   │   ├── user.py          # 用户模型
│   │   ├── group.py         # 群组模型
│   │   ├── message.py       # 消息模型（含撤回/删除字段）
│   │   ├── file.py          # 文件模型
│   │   └── token_blacklist.py
│   ├── routes/              # API路由
│   │   ├── chat.py          # WebSocket聊天（核心）
│   │   ├── group_route.py   # 群组管理
│   │   ├── user_route.py    # 用户/好友管理
│   │   ├── file_route.py    # 文件上传下载
│   │   └── auth.py          # 认证注册登录
│   ├── schemas/             # Pydantic验证模型
│   ├── utils/               # 工具函数
│   │   ├── websocket_manager.py  # WebSocket连接管理器（优化版）
│   │   ├── auth.py          # JWT认证
│   │   ├── security.py      # 密码哈希/Token生成
│   │   ├── file_handler.py  # 文件处理
│   │   ├── locales.py       # 国际化
│   │   └── log.py           # 日志
│   ├── config.py            # 配置管理
│   ├── database.py          # MongoDB连接
│   └── main.py              # FastAPI应用入口
├── templates/               # Jinja2模板
├── static/                  # 静态文件
├── requirements.txt         # 依赖列表
├── run.py                   # 启动脚本
├── .env.example             # 环境变量示例
└── README.md                # 项目说明
```

## 🔌 WebSocket连接示例

### 连接流程

```javascript
// 1. 连接WebSocket
const ws = new WebSocket('ws://localhost:8000/api/chat/ws/YOUR_TOKEN');

// 2. 收到连接确认
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.type === 'connected') {
    console.log('连接成功', data.content);
  }
};

// 3. 发送心跳
ws.send(JSON.stringify({ type: 'ping' }));

// 4. 发送消息
ws.send(JSON.stringify({
  type: 'text',
  group_id: 'GROUP_ID',
  content: '你好！',
  at_list: []
}));

// 5. 收到消息确认
// {"type": "message_sent", "content": {"message_id": "...", "success": true}}

// 6. 收到群组消息
// {"type": "message", "data": {...}}
```

## 📊 API统计

| 模块 | HTTP接口 | WebSocket接口 |
|------|----------|---------------|
| 认证 | 8 | 0 |
| 用户 | 11 | 0 |
| 群组 | 14 | 0 |
| 文件 | 5 | 0 |
| 聊天 | 2 | 2 |
| **总计** | **40** | **2** |

## 🔧 配置项

| 配置 | 说明 | 默认值 |
|------|------|--------|
| DATABASE_URL | MongoDB连接 | mongodb://localhost:27017 |
| SECRET_KEY | JWT密钥 | 需要自定义 |
| MAX_FILE_SIZE | 文件大小限制 | 10MB |
| OPENAPI_DOCS | 是否开启API文档 | True |

## 🗄️ 数据库

需要 MongoDB，创建两个数据库：
- `xboom` - 用户、群组、文件管理
- `chat` - 消息存储（每个群组一个collection）