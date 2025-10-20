# Telegram Group Management Bot

一个功能完整的电报群组管理机器人，具有智能验证、多语言支持、邀请统计和排行榜等功能。

## 🌟 主要功能

### 1. 🤖 智能机器人验证
- 新成员加入时自动发送数学题验证
- 5分钟超时限制，未通过验证自动踢出
- 防止机器人账号进入群组
- 不计入KOL邀请数量

### 2. 🌍 多语言支持
- 支持20种主流语言
- 用户可自由选择偏好语言
- 完整的本地化界面

### 3. 🔗 专属邀请链接
- 每个用户独立的邀请链接
- 实时统计邀请人数
- 详细的成员列表（分页显示）
- 追踪退群情况

### 4. 📊 全面统计排行
- 总邀请人数排行榜
- 被踢出人数排行榜
- 活跃成员数排行榜（总邀请-退群）
- 个人详细统计信息

### 5. 💡 用户友好界面
- 直观的命令菜单
- 交互式按钮界面
- 丰富的帮助文档

## 🏗️ 系统架构

### 架构图
```mermaid
graph TB
    A[Telegram Bot API] --> B[Bot Core Handler]
    B --> C[Authentication Module]
    B --> D[Language Module]
    B --> E[Invitation Module]
    B --> F[Statistics Module]

    C --> G[Math Challenge]
    C --> H[User Verification]

    D --> I[Language Selection]
    D --> J[Multilingual Messages]

    E --> K[Invite Link Generator]
    E --> L[Member Tracking]

    F --> M[Ranking System]
    F --> N[Statistics Dashboard]

    B --> O[(PostgreSQL Database)]
    P[Redis Cache] --> B
    Q[Logging System] --> B
```

### 数据库ER图
```mermaid
erDiagram
    Users {
        bigint user_id PK
        varchar username
        varchar first_name
        varchar last_name
        varchar language_code
        boolean is_verified
        timestamp created_at
        timestamp updated_at
        bigint invited_by_user_id FK
    }

    Invitations {
        varchar invite_code PK
        bigint user_id FK
        varchar invite_link
        integer total_invited
        integer total_left
        boolean is_active
        timestamp created_at
        timestamp expires_at
    }

    InvitationMembers {
        bigint id PK
        varchar invite_code FK
        bigint invited_user_id FK
        boolean has_left
        timestamp joined_at
        timestamp left_at
    }

    Challenges {
        bigint id PK
        bigint user_id FK
        varchar question
        varchar correct_answer
        varchar user_answer
        boolean is_solved
        integer attempts
        timestamp created_at
        timestamp solved_at
        timestamp expires_at
    }

    Users ||--o{ Invitations : creates
    Users ||--o{ Challenges : has
    Invitations ||--o{ InvitationMembers : contains
    Users ||--o{ InvitationMembers : member_of
    Users }o--|| Users : invited_by
```

## 📁 项目结构
```
tg-bot/
├── src/
│   ├── bot/
│   │   └── main.py                 # 主应用程序
│   ├── models/
│   │   └── __init__.py             # 数据库模型
│   ├── services/
│   │   ├── auth_service.py         # 认证服务
│   │   ├── invitation_service.py   # 邀请服务
│   │   ├── language_service.py     # 语言服务
│   │   └── statistics_service.py   # 统计服务
│   ├── handlers/
│   │   ├── start_handler.py        # 开始命令处理
│   │   ├── auth_handler.py         # 认证处理
│   │   ├── invitation_handler.py   # 邀请处理
│   │   └── ranking_handler.py      # 排行榜处理
│   └── utils/
│       ├── config.py               # 配置管理
│       ├── database.py             # 数据库连接
│       ├── redis_client.py         # Redis客户端
│       └── logger.py               # 日志系统
├── config/
│   └── languages.json              # 多语言配置
├── database/
│   └── init.sql                    # 数据库初始化脚本
├── docker-compose.yml              # Docker编排
├── Dockerfile                      # Docker镜像
├── deploy.sh                       # 部署脚本
├── requirements.txt                # Python依赖
├── .env.example                    # 环境变量示例
└── README.md                       # 项目文档
```

## 🚀 快速开始

### 1. 环境要求
- Python 3.11+
- PostgreSQL 12+
- Redis 6+
- Docker & Docker Compose (推荐)

### 2. 配置机器人

#### 创建Telegram机器人
1. 联系 [@BotFather](https://t.me/BotFather)
2. 发送 `/newbot` 创建新机器人
3. 获取 Bot Token
4. 设置机器人权限：
   - 允许添加到群组
   - 允许踢出用户
   - 允许读取所有消息

#### 配置群组
1. 将机器人添加到目标群组
2. 给予机器人管理员权限
3. 获取群组 Chat ID

### 3. 安装部署

#### 使用Docker (推荐)
```bash
# 1. 克隆项目
git clone <repository-url>
cd tg-bot

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 文件，填入必要配置

# 3. 部署
./deploy.sh
```

#### 手动安装
```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置数据库
# 创建PostgreSQL数据库并运行 database/init.sql

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env 文件

# 4. 启动机器人
python src/bot/main.py
```

### 4. 环境变量配置

在 `.env` 文件中配置以下参数：

```env
# 机器人配置
BOT_TOKEN=your_bot_token_here
GROUP_CHAT_ID=-1001234567890

# 数据库配置
DATABASE_URL=postgresql://username:password@localhost:5432/telegram_bot

# Redis配置
REDIS_URL=redis://localhost:6379/0

# 管理员用户ID（可选）
ADMIN_USER_IDS=123456789,987654321

# 验证设置
CHALLENGE_TIMEOUT=300        # 验证超时时间（秒）
MAX_CHALLENGE_ATTEMPTS=3     # 最大尝试次数

# Webhook（生产环境可选）
WEBHOOK_URL=https://your-domain.com/webhook
```

## 🎮 使用指南

### 机器人命令

| 命令 | 功能 | 示例 |
|------|------|------|
| `/start` | 显示帮助菜单 | `/start` |
| `/link` | 获取专属邀请链接 | `/link` |
| `/stats` | 查看个人邀请统计 | `/stats` |
| `/ranking` | 查看邀请排行榜 | `/ranking` |
| `/lang` | 更改语言偏好 | `/lang` |

### 工作流程

1. **新用户加入群组**
   - 机器人发送数学验证题
   - 用户需在5分钟内回答正确
   - 验证成功后选择偏好语言

2. **获取邀请链接**
   - 使用 `/link` 命令
   - 获得专属邀请链接
   - 查看邀请统计信息

3. **邀请统计**
   - 实时统计邀请人数
   - 追踪成员退群情况
   - 分页显示成员列表

4. **排行榜系统**
   - 总邀请数排行
   - 退群成员排行
   - 活跃成员排行

## 🛠️ 运维管理

### 日志监控
```bash
# 查看实时日志
docker-compose logs -f bot

# 查看错误日志
docker-compose logs bot | grep ERROR
```

### 数据库管理
```bash
# 访问数据库
docker-compose exec postgres psql -U telegram_user -d telegram_bot

# 备份数据库
docker-compose exec postgres pg_dump -U telegram_user telegram_bot > backup.sql

# 还原数据库
docker-compose exec -T postgres psql -U telegram_user telegram_bot < backup.sql
```

### 性能监控
- 访问 http://localhost:8080 使用Adminer管理数据库
- 监控Redis状态：`docker-compose exec redis redis-cli info`

## 🔧 自定义配置

### 添加新语言
1. 编辑 `config/languages.json`
2. 添加新的语言代码和翻译
3. 重启机器人

### 修改验证题类型
编辑 `src/services/auth_service.py` 中的 `generate_math_challenge` 方法

### 调整排行榜显示
修改 `src/utils/config.py` 中的分页设置

## 🐛 故障排除

### 常见问题

1. **机器人无法踢出用户**
   - 检查机器人是否有管理员权限
   - 确认群组设置允许机器人管理成员

2. **数据库连接失败**
   - 检查数据库服务是否运行
   - 验证连接字符串是否正确

3. **Redis连接问题**
   - 确认Redis服务状态
   - 检查Redis URL配置

4. **Webhook不工作**
   - 验证HTTPS证书
   - 检查防火墙设置

### 调试模式
设置环境变量 `LOG_LEVEL=DEBUG` 获取详细日志

## 📈 性能优化

- 使用Redis缓存提高响应速度
- 数据库索引优化查询性能
- 异步处理提高并发能力
- 后台任务清理过期数据

## 🔒 安全考虑

- 定期更新依赖包
- 使用强密码保护数据库
- 限制管理员权限
- 监控异常活动

## 🤝 贡献指南

1. Fork项目
2. 创建功能分支
3. 提交更改
4. 创建Pull Request

## 📄 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情

## 🆘 支持

如有问题或建议，请：
- 创建 [Issue](https://github.com/your-repo/issues)
- 联系项目维护者

---

**开发团队**
版本: 1.0.0
最后更新: 2024年