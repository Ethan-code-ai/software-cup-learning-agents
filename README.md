# 基于大模型的个性化资源生成与学习多智能体系统

**中国软件杯 A3 团队参赛作品，全国三等奖。** 本仓库包含项目源码、测试、启动脚本、开发文档与演示材料。

快速查看：[演示视频](文档与演示视频/演示视频.mp4) · [系统开发说明书](文档与演示视频/01-系统开发说明书.docx) · [演示PPT](文档与演示视频/项目演示PPT.pptx) · [获奖证书](获奖证书.pdf) · [本地运行指南](deployment/README.md)。

本项目是第十五届中国软件杯大赛 **A3 赛题**参赛作品，面向高校课程学习场景，围绕学生画像、课程知识库、知识点关系、学习路径、个性化资源、智能辅导和学习评价，构建由多个专业 Agent 协同工作的智能学习系统。

项目以 **数据结构课程**为演示场景，将学生的自然语言学习目标转化为结构化画像和可执行的学习计划，再由资源生成、智能辅导、测验评价等 Agent 协同完成学习支持，并通过可追溯的执行记录展示系统的判断过程与依据。

## 一、项目定位

### 1.1 面向的学习问题

高校课程学习中，学生通常需要在大量讲义、题目、代码案例和拓展资料中自行筛选内容。不同学生在知识基础、学习目标、可用时间和薄弱知识点方面存在差异，统一的学习材料难以同时满足不同学习节奏。

本项目以“**理解学生—分析课程—规划路径—生成资源—辅导练习—评价反馈**”为主线，将大模型的自然语言理解能力与课程知识库、知识点关系和多智能体协同机制结合，为学生提供具有课程依据、学习顺序和反馈机制的个性化学习体验。

### 1.2 项目特色

- **对话式学习画像**：通过自然语言对话提取学生的学习目标、基础水平、学习偏好、可用时间、薄弱环节和资源偏好等信息，形成六维学习画像。
- **多智能体分工协作**：由画像构建、学习规划、资源生成、智能辅导、测验生成、学习评价和画像更新等 Agent 分别承担专业职责。
- **知识库 grounded generation**：回答、资源和测验以课程资料检索结果为依据，保留来源引用和检索信息，降低脱离课程内容的生成风险。
- **学习结果驱动反馈**：学生完成测验后，系统根据作答结果生成评价、薄弱点和后续建议，并将学习证据用于画像更新。
- **可解释执行过程**：系统记录 Agent 的输入摘要、输出摘要、决策依据、执行阶段、模型来源、降级状态和引用来源，前端以时间线形式展示。
- **工程化实现**：采用前后端分离结构、统一 API 契约、SQLite 演示数据库、PowerShell 启动脚本和自动化验证脚本，支持离线演示与科大讯飞星火 MaaS 比赛入口。

## 二、已实现功能

### 2.1 学生画像与学习入口

- 支持学生通过自然语言描述学习目标、课程基础和学习安排。
- 自动构建六个画像维度：

  - `learning_goal`：学习目标
  - `foundation_level`：基础水平
  - `learning_preference`：学习偏好
  - `available_time`：可用学习时间
  - `weak_points`：薄弱知识点
  - `resource_preference`：资源偏好

- 支持画像查看、删除、学习数据关联和基于学习轨迹的更新。
- 提供基础薄弱型、考试冲刺型、算法实践型等演示画像，便于快速进入不同学习场景。

### 2.2 课程知识库与文档解析

- 支持课程资料粘贴和文件导入。
- 支持解析 `.txt`、`.md`、`.pdf`、`.docx` 和 `.pptx` 文件。
- PDF 优先使用 `pypdf` 提取文本；对于无文本层的扫描 PDF，可选用 `pypdfium2 + pytesseract` 进行 OCR。
- Word 文档支持段落与表格文本提取；PowerPoint 支持幻灯片文本和表格文本提取。
- 文档导入后自动切分为知识片段，保存文档、片段、来源引用和解析状态。
- 支持文档列表、文档详情、片段查看、非种子文档删除和单文档 `reindex`。
- 支持 `course/demo` 与 `private` 文档范围过滤，避免不同资料范围相互污染。

### 2.3 个性化学习路径

- 根据学生画像、课程知识点关系和自然语言学习目标识别目标知识点。
- 结合先修关系、薄弱点、学习时间和测验准备意图生成阶段化学习路径。
- 学习路径包含目标知识点、学习活动、资源类型、预估时长、完成标准和学习顺序。
- 对小测或期末准备类目标提供结构化规划；目标无法可靠映射到课程知识点时，系统返回明确的目标解析结果，不扩展生成无依据的课程内容。

### 2.4 五类个性化学习资源

系统通过 Resource Agent 面向目标知识点生成以下五类资源：

| 资源类型 | 功能说明 |
|---|---|
| `guided_note` | 结构化知识讲解与学习要点 |
| `practice_questions` | 针对性练习题与训练建议 |
| `mind_map` | 知识点关系与复习结构展示 |
| `extended_reading` | 与当前知识点相关的拓展阅读 |
| `coding_case` | 面向数据结构与算法的代码实践案例 |

针对教学视频类资源，系统提供由服务端生成并校验的结构化动画场景描述，前端根据课程知识点渲染复杂度、线性表、栈队列、树、图、查找和排序等可视化过程，用于展示算法状态变化和关键步骤。

### 2.5 Tutor 智能辅导

- 支持围绕当前课程资料进行自然语言提问。
- 支持多轮对话、Markdown 渲染、数学公式渲染和逐步输出式交互。
- 检索课程知识库后生成带来源依据的回答。
- 前端展示来源卡片、引用片段、检索模式、匹配信息和重排原因，帮助学生理解回答依据。
- 当模型调用失败、超时或输出不符合结构要求时，系统按照配置切换至稳定的规则策略，并保留状态说明。

### 2.6 Quiz 与 Evaluator

- Quiz Agent 根据目标知识点和课程资料生成结构化、多题型测验。
- 支持学生在线提交答案并获取即时结果。
- Evaluator Agent 输出评分、知识点反馈、薄弱环节和下一步学习建议。
- 测验提交结果进入 Agent 执行记录，并触发学生画像更新。

### 2.7 防幻觉与内容安全

系统在模型调用前、知识检索后和模型输出后设置确定性安全边界：

- 拦截高置信度的 Prompt Injection 输入。
- 拦截涉及凭据窃取、恶意代码、危险操作和其他高风险内容的请求。
- 过滤知识库检索结果中的指令注入片段，只将通过安全检查的片段交给 Agent。
- 校验 Tutor、Resource 和 Quiz 的引用是否来自本次实际检索结果。
- 对危险代码、敏感信息、未支持断言和伪造引用执行输出检查。
- 通过 `safety_status`、`safety_message` 和 Agent trace 将 `passed`、`blocked`、`degraded` 等状态反馈给前端。

安全策略用于约束系统的输入、检索和输出边界；学术内容的可靠性由课程资料质量、检索结果、引用校验、Critic 检查和人工验收共同保障。

### 2.8 Agent 执行追踪

系统在数据库中记录 `agent_runs` 和 `agent_run_steps`，每次运行可追踪：

- 输入摘要
- 输出摘要
- Agent 类型
- 执行阶段
- 决策依据
- Provider 与 Model
- 执行时长
- fallback 或降级原因
- grounded source 与引用信息

前端以 Agent 时间线呈现 `Input`、`Output`、`Decision` 和安全状态，使多智能体协同过程可观察、可解释、可复核。

## 三、系统架构

### 3.1 总体架构

```text
┌─────────────────────────────────────────────────────────────┐
│ React + TypeScript + Vite + Tailwind CSS 前端                │
│ 学习工作台 · 知识库 · 学习路径 · 资源卡片 · Tutor · Quiz     │
│ Agent 时间线 · 来源面板 · 安全状态 · 动画场景渲染            │
└──────────────────────────────┬──────────────────────────────┘
                               │ REST API / JSON
┌──────────────────────────────▼──────────────────────────────┐
│ FastAPI API Layer                                            │
│ 路由、参数校验、响应模型、异常处理                            │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│ Domain Services                                               │
│ Profile · Course · Knowledge Base · Learning Path             │
│ Resource · Tutor · Assessment · Document · Safety             │
└───────────────┬───────────────────────┬──────────────────────┘
                │                       │
┌───────────────▼──────────────┐ ┌──────▼──────────────────────┐
│ Multi-Agent Layer             │ │ Adapter Layer               │
│ Router / Planner              │ │ LLMProvider                 │
│ ProfileBuilder / Updater      │ │ EmbeddingProvider           │
│ Resource / Tutor / Quiz       │ │ DocumentParser              │
│ Evaluator / Critic            │ │ Protocols                   │
└───────────────┬──────────────┘ └──────┬──────────────────────┘
                │                       │
                └──────────────┬────────┘
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ SQLite 演示数据库 · 课程知识库 · 文档片段 · Agent 执行记录    │
│ 学生画像 · 学习路径 · 资源 · Quiz · 作答结果 · 引用信息       │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 多智能体职责

| Agent / 模块 | 主要职责 |
|---|---|
| Router Agent | 识别业务意图，将请求路由到对应学习流程 |
| Profile Builder Agent | 从自然语言对话中抽取并构建学生画像 |
| Planner Agent | 根据课程知识点、先修关系和画像生成学习路径 |
| Resource Agent | 生成讲解、练习、思维导图、拓展阅读和代码案例 |
| Tutor Agent | 基于课程知识库进行 grounded 问答 |
| Quiz Agent | 根据知识点和学习目标生成结构化测验 |
| Evaluator Agent | 评价作答结果并生成反馈与下一步建议 |
| Profile Updater Agent | 根据学习轨迹和测验结果更新学生画像 |
| Critic / Safety | 检查引用、安全状态、危险输出和结构化结果 |

### 3.3 关键数据流

```text
自然语言学习目标
        │
        ▼
Profile Builder ──► 六维学生画像
        │
        ▼
Router ──► Planner ──► 个性化学习路径
                              │
              ┌───────────────┼────────────────┐
              ▼               ▼                ▼
        Resource Agent   Tutor Agent      Quiz Agent
              │               │                │
              └───────────────┴────────────────┘
                              ▼
                    学习资源 / 问答 / 测验
                              │
                              ▼
                    Evaluator ──► 画像更新
                              │
                              ▼
                        Agent trace
```

### 3.4 技术栈

| 层次 | 技术选型 |
|---|---|
| 前端 | React 19、TypeScript、Vite、Tailwind CSS |
| 前端内容渲染 | `react-markdown`、`remark-math`、`rehype-katex` |
| 后端 | Python 3.11+、FastAPI、Pydantic、Uvicorn |
| 数据访问 | SQLAlchemy、SQLite |
| 文档解析 | `pypdf`、`python-docx`、PowerPoint 文本解析、可选 Tesseract OCR |
| LLM 接入 | OpenAI-compatible `LLMProvider`，支持科大讯飞星火 MaaS 等兼容接口 |
| 向量检索 | SQLite 向量表 + Python cosine similarity；支持 keyword / vector / hybrid 模式 |
| 测试 | Python `unittest`、前端 production build、Playwright smoke test |
| 工程脚本 | Windows PowerShell、npm、项目级验证脚本 |

## 四、主要 API

### 学生画像与课程

- `GET /api/v1/student-profiles`
- `POST /api/v1/student-profiles`
- `POST /api/v1/student-profiles/from-dialogue`
- `GET /api/v1/student-profiles/{profile_id}`
- `DELETE /api/v1/student-profiles/{profile_id}`
- `POST /api/v1/student-profiles/{profile_id}/update-from-trace`
- `GET /api/v1/courses/{course_id}/graph`

### 知识库与文档

- `POST /api/v1/courses/{course_id}/documents`
- `POST /api/v1/courses/{course_id}/documents/upload`
- `GET /api/v1/courses/{course_id}/documents`
- `GET /api/v1/documents/{document_id}`
- `DELETE /api/v1/documents/{document_id}`
- `POST /api/v1/documents/{document_id}/reindex`
- `GET /api/v1/documents/{document_id}/chunks`
- `POST /api/v1/knowledge/search`

### 学习流程与 Agent 执行

- `POST /api/v1/learning-paths`
- `GET /api/v1/learning-paths/{path_id}`
- `POST /api/v1/resources/generate`
- `POST /api/v1/tutor/ask`
- `POST /api/v1/quizzes/generate`
- `POST /api/v1/quizzes/{quiz_id}/attempts`
- `GET /api/v1/agent-runs/{run_id}`

### 演示数据

- `GET /api/v1/demo-data/status`
- `POST /api/v1/demo-data/load`
- `POST /api/v1/demo-data/reset-user-data`

## 五、部署与运行

### 5.1 环境要求

- Windows PowerShell
- Python 3.11 或更高版本
- Node.js 20.19+ 或 22.12+
- npm
- 如需扫描 PDF OCR：安装 Tesseract，并配置 `TESSERACT_CMD`

### 5.2 安装依赖

在仓库根目录执行：

```powershell
python -m pip install -e .
Set-Location src/frontend
npm ci
Set-Location ../..
```

### 5.3 启动本地演示

```powershell
./scripts/run-local.ps1
```

启动脚本会自动完成以下工作：

1. 设置本地演示环境变量。
2. 启动 FastAPI 后端。
3. 加载课程和演示数据。
4. 启动 Vite 前端开发服务。
5. 输出前端和后端访问地址。

默认地址：

- 前端：`http://127.0.0.1:5173`
- 后端：`http://127.0.0.1:8000`

停止系统时，在运行脚本的 PowerShell 窗口按 `Ctrl+C`。

### 5.4 自定义端口与快速检查

```powershell
./scripts/run-local.ps1 -BackendPort 8010 -FrontendPort 5175
./scripts/run-local.ps1 -SmokeOnly
```

如果本机没有 Microsoft Edge，可让 Playwright 使用 Chromium：

```powershell
$env:PLAYWRIGHT_CHANNEL = 'chromium'
```

### 5.5 科大讯飞星火 MaaS 比赛入口

比赛演示使用科大讯飞星火 MaaS 的 OpenAI-compatible 接口。API Key 只从环境变量读取，不写入仓库、前端构建产物或 Agent trace。

```powershell
[Environment]::SetEnvironmentVariable('XFYUN_SPARK_API_KEY', '<your-api-key>', 'User')
./scripts/run-competition-spark.ps1
```

该入口默认启用以下 LLM 能力：

- Profile Builder
- Planner
- Resource
- Tutor
- Quiz
- Evaluator
- Profile Updater

本地离线入口仍可直接使用规则策略运行，适合展示界面、课程知识库、学习路径和交互流程：

```powershell
./scripts/run-local.ps1
```

### 5.6 RAG 检索模式

系统默认使用无需外部 API 的 SQLite keyword retrieval。根据演示环境可以选择：

| 模式 | 配置 | 说明 |
|---|---|---|
| Keyword | `RAG_RETRIEVAL_MODE=keyword` | 基于课程片段文本匹配，适合离线演示 |
| Vector | `RAG_RETRIEVAL_MODE=vector` | 使用向量表与 Python cosine similarity |
| Hybrid | `RAG_RETRIEVAL_MODE=hybrid` | 融合关键词与向量检索，适合真实资料演示 |

启用向量检索时，需要额外配置 embedding provider、模型和 API Key，详细参数见 [`deployment/README.md`](deployment/README.md)。

### 5.7 完整验证

```powershell
./scripts/verify.ps1
```

验证脚本覆盖 Python 编译检查、后端测试、依赖一致性检查、后端构建、前端依赖安装、前端 production build 和 Playwright 浏览器 smoke test。

## 六、推荐演示流程

1. 启动 `./scripts/run-competition-spark.ps1`，或使用 `./scripts/run-local.ps1` 进行离线演示。
2. 进入学习工作台，确认学生画像和课程知识点图谱。
3. 在知识库中粘贴课程资料或上传文档，查看文档解析状态、片段数量和来源信息。
4. 输入自然语言学习目标，展示六维画像和目标知识点识别结果。
5. 生成个性化学习路径，展示学习节点、活动安排、预估时长和完成标准。
6. 生成讲解、练习题、思维导图、拓展阅读和代码案例等学习资源。
7. 进入 Tutor，围绕 BFS、DFS、栈、队列、链表或复杂度分析提问，查看 grounded source。
8. 生成 Quiz 并提交答案，查看 Evaluator 的评分、薄弱点和下一步建议。
9. 查看画像更新和 Agent trace，展示多智能体协同的执行顺序、决策依据、安全状态和引用来源。
10. 对 Prompt Injection 等异常输入进行安全策略演示，确认系统返回拦截状态并保留可追溯记录。

## 七、作品提交材料

按照 A3 初赛作品提交要求，作品提交应包含以下内容：

- **可完整运行的项目文件**：`src/`、`data/`、`deployment/`、`scripts/`、`pyproject.toml`、前端 `package.json` 与 `package-lock.json`、`README.md`。
- **配套文档**：系统开发说明书、测试说明书、部署与运行说明、AI Coding 工具使用说明、第三方依赖与开源协议说明。
- **演示材料**：项目演示 PPT、时长不超过 7 分钟的演示视频及视频脚本。
- **合规材料**：直接依赖和传递依赖的许可证、NOTICE 及相关来源说明。

仓库通过 `.gitignore` 排除真实环境配置、虚拟环境、`node_modules`、缓存、测试生成文件、日志和本机运行数据库。演示数据库由启动脚本和种子数据生成。运行方法与部署参数见 [本地运行指南](deployment/README.md)，参赛配套材料见 [文档与演示视频](文档与演示视频/)。

## 八、项目文档

- [系统开发说明书](文档与演示视频/01-系统开发说明书.docx)
- [测试说明书](文档与演示视频/02-测试说明书.docx)
- [部署与运行说明书](文档与演示视频/03-部署与运行说明.docx)
- [AI Coding 与开源合规说明](文档与演示视频/04-AI%20Coding与开源合规说明.docx)
- [项目演示 PPT](文档与演示视频/项目演示PPT.pptx)
- [演示视频](文档与演示视频/演示视频.mp4)
- [获奖证书](获奖证书.pdf)
- [源码版安装与运行指南](deployment/README.md)
- [环境变量配置示例](deployment/local.env.example)

## 九、开源与 AI Coding 合规

本项目的业务逻辑、Agent 协作流程、课程知识库组织、前后端交互和演示系统由参赛团队自主设计与实现。项目使用的第三方框架、依赖、AI 工具和模型服务均在提交文档中记录名称、来源、版本与许可证信息。

项目不在仓库中保存任何真实 API Key、个人隐私数据或外部服务凭据；模型服务通过 `LLMProvider` adapter 接入，便于在比赛环境中切换科大讯飞星火 MaaS 与本地规则策略，并保持统一的业务接口。
