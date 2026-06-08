# 生活管家 Agent 项目实施清单

## 1. 文档信息

- 文档版本：v0.1
- 创建日期：2026-06-08
- 关联文档：`PRD.md`、`TECHNICAL_IMPLEMENTATION.md`、`DATABASE_DESIGN.md`
- 目标：把生活管家 Agent MVP 从工程初始化推进到公众号真实可用。

## 2. 技术栈总览

## 2.1 应用与 Agent

- Python 3.11 或 3.12
- FastAPI：微信公众号回调、健康检查、内部管理接口
- LangChain：模型适配、Prompt、工具封装
- LangGraph：Agent 状态机、意图路由、工具执行编排
- Pydantic、pydantic-settings：配置、请求和结构化数据校验
- httpx：调用微信、DeepSeek、天气和资讯接口

## 2.2 数据与基础设施

- 阿里云轻量应用服务器：MVP 初期默认部署方式
- Docker Compose：所有服务基于 Docker 镜像部署
- PostgreSQL：MVP 初期以 Docker 镜像同机部署，后续升级阿里云 RDS PostgreSQL
- Redis：MVP 初期以 Docker 镜像同机部署，后续升级阿里云 Redis/Tair
- Alembic：数据库迁移
- SQLAlchemy 2.x：Repository 和 ORM
- 本地文件日志：MVP 初期使用，后续升级阿里云 SLS
- 阿里云云监控：后续生产告警
- 环境变量：MVP 初期密钥管理，后续升级阿里云 KMS
- APScheduler：MVP 初期任务扫描，后续升级阿里云 EventBridge 或独立 Worker
- OSS：后续文件和知识库预留

## 2.3 测试与工程质量

- pytest、pytest-asyncio：单元测试和集成测试
- ruff：代码检查和格式约束
- Docker Compose：本地和阿里云轻量应用服务器上运行 FastAPI、PostgreSQL、Redis、APScheduler、Nginx/Caddy

MVP Docker 服务：

- `app`：FastAPI + LangGraph 应用服务。
- `scheduler`：APScheduler 任务扫描服务，与 `app` 使用同一镜像、不同启动命令。
- `postgres`：PostgreSQL 数据库。
- `redis`：Redis 缓存、锁和短期状态。
- `nginx` 或 `caddy`：HTTPS 和反向代理。
- `migrate`：Alembic 数据库迁移一次性任务。

## 3. MVP 节点总览

| 节点 | 名称 | MVP 目标 | 通过后具备的能力 |
|---|---|---|---|
| M0 | 项目与资源准备 | 配置、账号、云资源、密钥齐备 | 可以开始本地和云上联调 |
| M1 | 基础工程骨架 | FastAPI、本地环境、日志、健康检查 | 已完成：应用可启动、可观测 |
| M2 | 数据库与用户编号 | 核心表、迁移、Repository、`public_user_id` | 用户和业务数据可落库 |
| M3 | 微信公众号基础链路 | 微信校验、消息收发、关注事件 | 公众号可真实互动 |
| M4 | DeepSeek 与 Agent 骨架 | LLMProvider、LangGraph 基础流 | 用户消息可进入 Agent |
| M5 | 提醒与待办闭环 | 创建、查询、删除提醒 | 生活管理主功能可用 |
| M6 | 主动推送与调度 | 到期任务扫描、微信推送、重试 | 提醒可以主动触达 |
| M7 | 每日简报 | 订阅、天气、RSS、定时生成 | 用户可收到早报 |
| M8 | 生活问答与记忆 | 问答、长期偏好、删除记忆 | Agent 具备个性化基础 |
| M9 | 管理与运维 | 内部接口、脚本、日志、告警 | 可以内测和排障 |
| M10 | 云上发布验收 | 生产部署、公众号真实验收 | MVP 可进入小范围内测 |

## 4. M0：项目与资源准备

## 4.1 要完成的事情

- 确认微信公众号服务号配置：
  - AppID、AppSecret、Token、EncodingAESKey。
  - 服务器配置权限。
  - 自定义菜单权限。
  - 用户标签能力。
  - 模板消息、订阅消息或客服消息权限。

- 确认 DeepSeek 配置：
  - API Key。
  - Base URL。
  - 最新可用模型 ID。
  - 超时、限流、预算。

- 确认阿里云资源：
  - 地域和 VPC。
  - 轻量应用服务器实例。
  - 安全组和公网 IP。
  - 数据盘和备份策略。
  - Docker 与 Docker Compose 运行环境。
  - 后续升级所需的 RDS PostgreSQL、Redis/Tair、SLS、EventBridge、OSS 预算。

- 确认域名与 HTTPS：
  - 微信回调用公网 HTTPS 地址。
  - 证书和备案。

## 4.2 MVP 节点

M0-MVP：所有外部依赖可以被测试脚本访问。

## 4.3 测试与验证

- DeepSeek 测试调用返回文本。
- PostgreSQL 连接成功。
- Redis 连接成功。
- 轻量应用服务器上应用可以启动并写入本地日志。
- 微信公众号后台服务器 URL 校验通过。

## 4.4 交付物

- `.env.example`
- 阿里云轻量应用服务器与 Docker Compose 资源清单
- 微信公众号配置清单
- DeepSeek 配置清单

## 5. M1：基础工程骨架

## 5.1 要完成的事情

- 初始化 Python 工程。
- 建立目录结构：

```text
src/app/
  api/
  agent/
  models/
  repositories/
  services/
  workers/
tests/
migrations/
configs/
scripts/
```

- 配置 FastAPI。
- 配置 pydantic-settings。
- 建立 JSON 结构化日志。
- 增加 `request_id`。
- 增加健康检查：
  - `GET /healthz`
  - `GET /readyz`
- 本地 Docker Compose 跑 PostgreSQL 和 Redis。
- 准备轻量应用服务器 Docker Compose 部署方式：
  - FastAPI 容器。
  - PostgreSQL 容器。
  - Redis 容器。
  - APScheduler Worker 容器。
  - Nginx/Caddy 反向代理和 HTTPS 容器。
- 引入基础依赖：
  - `fastapi`
  - `uvicorn`
  - `sqlalchemy`
  - `alembic`
  - `asyncpg`
  - `redis`
  - `httpx`
  - `langchain`
  - `langgraph`
  - `pytest`
  - `pytest-asyncio`
  - `ruff`

## 5.2 MVP 节点

M1-MVP：本地应用可以启动，健康检查和基础日志可用。

## 5.3 测试与验证

- `ruff check .`
- `pytest`
- `/healthz` 返回 200。
- `/readyz` 可以检查数据库和 Redis。
- 日志中包含 `request_id`。

## 5.4 交付物

- FastAPI 基础项目
- 配置模块
- 日志模块
- 本地启动说明
- Docker Compose 配置
- Docker 镜像构建配置

## 6. M2：数据库与用户编号

## 6.1 要完成的事情

- 按 `DATABASE_DESIGN.md` 建立 Alembic migration。
- 创建 P0/P1 核心表：
  - `users`
  - `id_sequences`
  - `user_profiles`
  - `reminders`
  - `subscriptions`
  - `message_logs`
  - `scheduled_jobs`
  - `wechat_tokens`
- 可选创建 P2 表：
  - `life_records`
- 实现 `public_user_id` 生成服务：
  - 产品码 2 位。
  - 渠道码 2 位。
  - 年份 2 位。
  - 序列号 7 位。
  - 校验位 1 位。
  - 数据库中使用 `bigint`。
  - 使用 `id_sequences`、事务和行锁保证并发唯一。
- 建立 Repository：
  - UserRepository。
  - ReminderRepository。
  - SubscriptionRepository。
  - UserProfileRepository。
  - MessageLogRepository。
  - ScheduledJobRepository。
  - WechatTokenRepository。
- 封装 Redis key：
  - `wechat:access_token:{app_id}`
  - `lock:scheduled_job:{job_id}`
  - `idempotency:wechat_msg:{msg_id}`
  - `conversation:{public_user_id}`
  - `rate_limit:{openid_hash}`

## 6.2 MVP 节点

M2-MVP：新用户可以落库，并自动生成唯一 `public_user_id`。

## 6.3 测试与验证

- Alembic 空库迁移成功。
- `users.public_user_id` 唯一索引生效。
- `public_user_id` 14 位范围约束生效。
- 校验位计算正确。
- 并发创建用户时编号不重复。
- Repository CRUD 测试通过。
- 到期任务扫描只返回 `pending` 且到期的任务。

## 6.4 交付物

- Alembic migration
- SQLAlchemy models
- Repository 层
- `public_user_id` 生成服务
- 数据库测试用例

## 7. M3：微信公众号基础链路

## 7.1 要完成的事情

- 实现微信服务器校验：
  - `signature`
  - `timestamp`
  - `nonce`
  - `echostr`
- 实现 XML 解析：
  - 文本消息。
  - 关注事件。
  - 取消关注事件。
  - 菜单点击事件。
- 实现被动回复 XML。
- 实现用户创建和状态更新：
  - 首次消息创建用户。
  - 关注事件激活用户。
  - 取消关注事件将用户标记为 `unsubscribed`。
- 实现消息日志写入。
- 实现 access_token 管理：
  - 获取。
  - Redis 缓存。
  - 数据库记录。
  - 失败重试。
- 实现公众号菜单初始化脚本。
- 实现用户标签初始化脚本。

## 7.2 MVP 节点

M3-MVP：真实微信用户关注服务号后，可以发送文本并收到回复。

## 7.3 测试与验证

- 微信签名校验单测。
- XML 解析单测。
- XML 回复生成单测。
- 模拟微信回调集成测试。
- 微信后台服务器配置校验通过。
- 真实微信发送“你好”，服务号返回固定回复。
- 关注、取消关注事件写入日志并更新用户状态。

## 7.4 交付物

- `/api/wechat/callback`
- 微信消息解析模块
- 微信回复生成模块
- access_token 服务
- 菜单初始化脚本
- 标签初始化脚本

## 8. M4：DeepSeek 与 Agent 骨架

## 8.1 要完成的事情

- 实现 `LLMProvider` 抽象。
- 实现 `DeepSeekProvider`。
- 加入超时、重试、错误分类。
- 记录模型耗时和调用状态。
- 建立 LangGraph State：
  - `user_id`
  - `public_user_id`
  - `openid`
  - `raw_message`
  - `intent`
  - `slots`
  - `tool_result`
  - `final_response`
- 建立基础节点：
  - `input_guardrail`
  - `context_loader`
  - `intent_router`
  - `tool_executor`
  - `response_composer`
- 先实现最小意图：
  - `general_qa`
  - `create_reminder`
  - `query_reminder`
  - `unknown`

## 8.2 MVP 节点

M4-MVP：公众号消息可以进入 LangGraph，并由 DeepSeek 生成可返回的文本。

## 8.3 测试与验证

- DeepSeek 测试调用成功。
- 模拟 DeepSeek 超时时有兜底回复。
- 输入“你好”进入 `general_qa` 或欢迎回复。
- 输入“明早 8 点提醒我带身份证”能识别为提醒意图。
- Agent 异常不影响微信回调返回。

## 8.4 交付物

- `LLMProvider`
- `DeepSeekProvider`
- LangGraph 基础图
- Agent State
- 基础 Prompt
- 意图识别样例测试集

## 9. M5：提醒与待办闭环

## 9.1 要完成的事情

- 实现提醒创建工具：
  - 一次性提醒。
  - 周期提醒预留。
  - 缺失时间或事项时追问。
- 实现提醒查询工具：
  - 今日提醒。
  - 未来提醒。
  - 未完成待办。
- 实现提醒删除工具：
  - 单个删除。
  - 多个匹配时要求确认。
- 实现待办：
  - 无时间任务作为待办。
  - 完成待办。
- 实现时间解析：
  - “明早 8 点”
  - “今晚 8 点”
  - “每周三晚上”
  - “工作日早上 8 点”
- 创建提醒时写入：
  - `reminders`
  - `scheduled_jobs`
  - `message_logs`

## 9.2 MVP 节点

M5-MVP：用户可以通过公众号创建、查询、删除提醒。

## 9.3 测试与验证

- 创建提醒后数据库有 `reminders` 记录。
- 创建带时间提醒后有 `scheduled_jobs` 记录。
- “今天有什么提醒”返回正确列表。
- 删除提醒后状态变更为 `cancelled` 或 `deleted`。
- 多个同名提醒时不直接批量删除，需要确认。

## 9.4 交付物

- Reminder 工具
- 时间解析模块
- 提醒相关 Agent 节点
- 提醒功能测试用例

## 10. M6：主动推送与任务调度

## 10.1 要完成的事情

- 实现任务扫描器：
  - 扫描 `scheduled_jobs.next_run_at <= now()`。
  - 只执行 `pending` 任务。
  - 使用 Redis 锁或数据库锁防重复。
- 实现提醒推送：
  - 调用微信主动推送接口。
  - 成功后更新任务状态。
  - 失败后记录错误和重试次数。
- 实现重试策略：
  - 最大重试次数。
  - 下一次重试时间。
  - 永久失败状态。
- 实现取消关注保护：
  - `users.status = unsubscribed` 时不推送。
- 部署调度触发方式：
  - MVP 初期使用 APScheduler。
  - 后续正式内测可升级为阿里云 EventBridge 或独立调度 Worker。

## 10.2 MVP 节点

M6-MVP：到期提醒可以主动推送到微信，且不会重复推送。

## 10.3 测试与验证

- 创建一分钟后的提醒。
- 到期扫描器能找到任务。
- 推送成功后任务状态更新。
- 重复扫描不会重复推送。
- 模拟微信推送失败后进入重试。
- 用户取消关注后不发送推送。

## 10.4 交付物

- 任务扫描器
- 微信推送服务
- 任务锁
- 重试逻辑
- APScheduler Worker
- EventBridge 调用入口升级预留

## 11. M7：每日简报

## 11.1 要完成的事情

- 实现简报订阅：
  - 创建订阅。
  - 查询订阅。
  - 取消订阅。
- 接入天气 API：
  - 根据默认城市或用户偏好城市获取天气。
  - 天气失败时跳过天气模块。
- 接入 RSS 或开放新闻 API：
  - 白名单来源。
  - 标题、链接、发布时间。
  - 去重和过期过滤。
- 生成简报：
  - 今日天气。
  - 今日提醒。
  - 资讯 3-5 条。
  - 来源标注。
  - 微信短文本格式。
- 定时推送：
  - 根据 `subscriptions.next_push_at` 生成或扫描任务。
  - 到点生成简报并推送。

## 11.2 MVP 节点

M7-MVP：用户可以订阅每日简报，并在指定时间收到天气、提醒和资讯摘要。

## 11.3 测试与验证

- “每天早上 8 点给我发天气和科技新闻”创建订阅。
- “取消每日简报”取消订阅。
- RSS 解析和去重单测通过。
- 无天气或新闻数据时仍能生成可读简报。
- 简报包含来源。
- 到点推送成功。

## 11.4 交付物

- Briefing 工具
- 天气服务
- RSS 服务
- 简报生成 Prompt
- 简报订阅测试用例

## 12. M8：生活问答与长期记忆

## 12.1 要完成的事情

- 实现生活问答 Prompt：
  - 简洁。
  - 可执行。
  - 高风险问题带提示。
  - 政策类问题建议查官方渠道。
- 实现偏好识别：
  - 默认城市。
  - 饮食禁忌。
  - 资讯偏好。
  - 推送偏好。
  - 时区。
- 实现偏好写入：
  - 只保存明确长期偏好。
  - 按 `profile_key` 判断同类别。
  - 按 merge strategy 执行覆盖、集合追加或 JSON patch。
- 实现偏好查询：
  - “你记住了我哪些偏好？”
- 实现偏好删除：
  - 删除单条。
  - 删除全部。
  - 删除全部前确认。
- 问答和简报读取偏好：
  - 城市。
  - 饮食禁忌。
  - 资讯类别。

## 12.2 MVP 节点

M8-MVP：用户可以问生活问题，系统可以保存、查询、删除长期偏好，并在回答和简报中使用偏好。

## 12.3 测试与验证

- “我不吃香菜，以后记住”写入 `user_profiles`。
- “你记住了我哪些偏好”返回偏好列表。
- “删除我不吃香菜这条”删除单条偏好。
- “删除我的所有记忆”要求确认。
- “空气炸锅怎么清洗”返回生活问答。
- “感冒了能喝咖啡吗”返回谨慎建议和风险提示。

## 12.4 交付物

- QA Agent 节点
- Memory Agent 节点
- UserProfile 工具
- 偏好 Schema 和 merge strategy
- 问答和记忆测试用例

## 13. M9：管理与运维

## 13.1 要完成的事情

MVP 不做完整 Web 后台，但需要内部管理能力。

- 内部管理接口：
  - 查询用户数量。
  - 查询消息日志。
  - 查询待推送任务。
  - 查询订阅。
  - 手动触发任务扫描。
  - 手动触发简报。
- 管理接口鉴权。
- 初始化脚本：
  - 菜单初始化。
  - 标签初始化。
  - 资讯源初始化。
- 日志与指标：
  - 微信回调响应时间。
  - Agent 执行耗时。
  - DeepSeek 调用失败率。
  - 工具调用失败率。
  - 推送成功率。
  - 定时任务积压数。
- 告警：
  - 5xx 增多。
  - 模型失败率升高。
  - 推送失败率升高。
  - 任务积压。
  - PostgreSQL 或 Redis 连接失败。

## 13.2 MVP 节点

M9-MVP：内部可以查看运行状态、手动触发关键任务，并能收到基础异常告警。

## 13.3 测试与验证

- 管理接口无 token 返回 401。
- 管理接口有 token 返回数据。
- 手动触发任务扫描成功。
- 手动触发简报成功。
- 本地结构化日志可以按 `request_id` 检索。
- 模拟错误后告警规则可触发。

## 13.4 交付物

- 内部管理 API
- 管理鉴权
- 运维脚本
- 本地结构化日志字段
- SLS 日志升级预留
- 告警配置清单

## 14. M10：云上发布与 MVP 验收

## 14.1 要完成的事情

- 准备 Dockerfile。
- 准备生产环境变量。
- 执行数据库迁移。
- 部署应用到阿里云轻量应用服务器。
- 配置 HTTPS 域名。
- 配置微信公众号服务器 URL。
- 配置 APScheduler。
- 接入轻量应用服务器 Docker Compose 中的 PostgreSQL、Redis。
- 配置本地日志轮转；后续升级 SLS。
- 配置基础告警。
- 做生产冒烟测试。

## 14.2 MVP 节点

M10-MVP：真实公众号用户可以完成提醒、简报、问答、记忆的核心闭环。

## 14.3 测试与验证

- `/healthz` 正常。
- `/readyz` 正常。
- 微信发送“你好”有回复。
- 微信发送“明早 8 点提醒我带身份证”创建成功。
- 到期提醒主动推送成功。
- 微信发送“每天早上 8 点给我发天气和科技新闻”订阅成功。
- 手动触发简报推送成功。
- 微信发送“我不吃香菜，以后记住”保存成功。
- 微信发送“你记住了我哪些偏好”返回正确。
- 微信发送“删除我的所有记忆”要求确认。

## 14.4 交付物

- 生产部署服务
- 生产配置
- 数据库迁移记录
- 微信公众号服务器配置
- APScheduler 调度器配置
- MVP 验收记录

## 15. MVP 验收总清单

| 能力 | 验收方式 | 状态 |
|---|---|---|
| 微信服务器校验 | 微信后台 URL 校验通过 | 待做 |
| 微信文本消息 | 真实微信发送消息并收到回复 | 待做 |
| 用户创建 | 首次消息创建 `users` 和 `public_user_id` | 待做 |
| 提醒创建 | “明早 8 点提醒我带身份证” | 待做 |
| 提醒查询 | “今天有什么提醒” | 待做 |
| 提醒删除 | “取消带身份证的提醒” | 待做 |
| 主动提醒 | 到期微信推送 | 待做 |
| 简报订阅 | “每天早上 8 点给我发天气和科技新闻” | 待做 |
| 简报推送 | 到点收到天气、提醒、资讯 | 待做 |
| 生活问答 | “空气炸锅怎么清洗” | 待做 |
| 长期偏好 | “我不吃香菜，以后记住” | 待做 |
| 查询记忆 | “你记住了我哪些偏好” | 待做 |
| 删除记忆 | 删除单条和全部记忆 | 待做 |
| 日志检索 | 本地结构化日志按 `request_id` 查询 | 待做 |
| 任务重试 | 模拟推送失败后重试 | 待做 |
| 告警 | 模拟错误触发告警 | 待做 |

## 16. 推荐开发顺序

推荐严格按以下顺序推进：

1. M0 项目与资源准备。
2. M1 基础工程骨架。
3. M2 数据库与用户编号。
4. M3 微信公众号基础链路。
5. M4 DeepSeek 与 Agent 骨架。
6. M5 提醒与待办闭环。
7. M6 主动推送与任务调度。
8. M7 每日简报。
9. M8 生活问答与长期记忆。
10. M9 管理与运维。
11. M10 云上发布与 MVP 验收。

其中 M0-M6 是最小核心闭环。完成 M6 后，产品已经具备“公众号里创建提醒并主动推送”的基础价值；M7-M8 再补齐生活管家的资讯和问答能力。
