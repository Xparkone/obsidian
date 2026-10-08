# Python 常见 Web 框架对比与选型指南

> 面向 Python 和 FastAPI 初学者，比较常见的 Web、API 和异步服务框架

## 一、先给结论

Python 框架没有绝对的“最好”，只有和需求是否匹配。

- **想学习现代 API 开发**：优先学习 FastAPI。
- **想做完整网站、后台管理和数据库业务**：优先考虑 Django。
- **想从最小代码开始，自己选择数据库和插件**：考虑 Flask。
- **想做异步、高并发、WebSocket 或长连接服务**：考虑 FastAPI、Sanic、Litestar、Tornado 或 Quart，再根据生态和团队经验选择。
- **想写 HTTP 客户端、爬虫、代理或异步网关**：优先考虑 aiohttp；它更像异步 HTTP 库和服务工具箱，不是“开箱即用的全栈框架”。
- **想做极简 API 或嵌入式小服务**：可以了解 Falcon、Bottle。
- **需要高度可组合的传统 WSGI 应用**：可以考虑 Pyramid。

对于你当前的学习目标，建议顺序是：

```text
Python 基础
  -> HTTP 和 JSON
  -> FastAPI
  -> Pydantic 和数据库
  -> Prometheus/Kubernetes API
  -> 测试、Docker、部署
```

不需要同时学习所有框架。先用 FastAPI 完成一个只读运维状态 API，再通过对比理解 Django、Flask 和其他框架的设计取舍，效果更好。

## 二、框架到底解决什么问题

不使用框架时，程序需要自己处理很多通用工作：

- 监听端口和接收 HTTP 请求。
- 根据 URL 和 HTTP 方法找到处理函数。
- 读取 Query、Path、Header、Cookie、Form 和 JSON Body。
- 生成 HTTP 状态码、响应头和响应体。
- 处理异常、日志、中间件和跨域。
- 和模板引擎、数据库、认证系统、缓存连接。
- 测试接口并生成接口文档。

Web 框架把这些通用工作整理成一套约定和 API。框架越“完整”，通常内置的东西越多；框架越“轻量”，通常越需要你自行选择和组装组件。

框架也会带来约束：

- 目录结构可能有固定习惯。
- 请求处理模型可能是同步、异步或两者结合。
- 数据库、模板、认证和路由方式可能有自己的推荐做法。
- 升级时需要遵守框架和扩展的兼容关系。

因此，框架的优点不只是“少写代码”，还包括团队协作、默认安全措施、项目结构和长期维护；缺点也不只是“学习成本高”，还包括约束、迁移成本和生态依赖。

## 三、先理解 WSGI 和 ASGI

### 3.1 WSGI

WSGI 是传统 Python Web 应用与 Web 服务器之间的接口规范。Flask、Pyramid、Bottle 等传统用法主要建立在 WSGI 生态上。

它适合：

- 普通同步请求。
- 传统 HTML 网站。
- 常规 CRUD 后台。
- 已有大量同步数据库和第三方库的项目。

同步并不等于慢。对于数据库查询、模板渲染和普通业务请求，合理的进程数、缓存和数据库连接池同样可以提供很好的表现。

### 3.2 ASGI

ASGI 是面向异步 Python Web 应用的接口规范，支持异步请求、WebSocket、长连接和流式响应。FastAPI、Litestar、Sanic、Quart 等框架以 ASGI 为核心或重点支持 ASGI。

它适合：

- 大量 I/O 等待，例如调用多个 HTTP 服务。
- WebSocket 和长轮询。
- 流式响应。
- 需要和 `asyncio` 生态结合的服务。

使用异步框架并不会自动让所有代码变快。如果在 `async def` 中调用阻塞的同步函数，仍然可能阻塞事件循环。异步框架需要配套使用异步 HTTP 客户端、异步数据库驱动，或把阻塞工作放到线程池/进程池中。

### 3.3 不要只看“性能排名”

框架性能会受到很多因素影响：

- 路由和中间件数量。
- JSON 序列化和数据校验。
- 数据库和外部 API 延迟。
- 连接池、缓存和日志。
- Worker 数量和部署方式。
- 业务代码是否阻塞。

“某框架基准测试更快”不能直接推出“它一定更适合你的业务”。实际选型应先看编程模型、生态、团队能力、部署约束和维护成本。

## 四、主要框架快速对比

| 框架 | 主要定位 | 常见协议模型 | 内置程度 | 主要优点 | 主要缺点 |
| --- | --- | --- | --- | --- | --- |
| Django | 全栈 Web 框架 | 以 WSGI 为主，也支持异步能力 | 高 | ORM、Admin、认证、表单、迁移和生态完整 | 约束多，API-only 项目可能显得重 |
| Flask | 轻量 Web 框架 | WSGI 为主，支持部分异步视图 | 低到中 | 简单、灵活、扩展多、学习入口好 | 需要自行选择项目结构、校验、认证和数据库组件 |
| FastAPI | API 和异步服务框架 | ASGI | 中 | 类型标注、校验、OpenAPI 文档、依赖注入 | 全栈网站、Admin、ORM 和认证需要自行组合 |
| Sanic | 异步 Web 框架和服务器 | ASGI | 中 | async-first，内置服务器，面向高并发 I/O | 生态和团队经验通常小于 Django/Flask |
| Tornado | 异步 Web 与网络库 | 自有异步模型并集成 asyncio | 中 | 长连接、WebSocket、长轮询和网络编程能力强 | 编程模型独特，普通 CRUD API 不一定是最省事的选择 |
| Litestar | 高性能、可组合 ASGI 框架 | ASGI | 中到高 | 依赖注入、OpenAPI、插件、安全组件较完整 | 社区和资料规模相对小，团队需要建立自己的约定 |
| aiohttp | 异步 HTTP 客户端和服务器库 | asyncio | 低 | HTTP 客户端能力强，适合爬虫、网关和集成服务 | 缺少全套 Web 框架约定，需要自己组装很多能力 |
| Quart | Flask API 的异步实现 | ASGI | 中 | Flask 风格、支持 async、WebSocket 和流式响应 | Flask 扩展不一定完全兼容，异步边界需要理解清楚 |
| Falcon | 极简 API 和微服务框架 | WSGI/ASGI | 低 | 关注性能、可靠性和最小抽象 | 功能较少，需要自行集成更多组件 |
| Pyramid | 可组合的通用 Web 框架 | WSGI 生态为主 | 中 | 从小应用扩展到复杂系统，配置灵活 | 学习和项目约定需要自行建立 |
| Bottle | 极简单文件微框架 | WSGI | 低 | 依赖少、适合原型和小工具 | 大型项目需要自行补足架构和生态 |

这张表用于建立方向感，不是性能测试结果，也不代表所有版本和插件的状态。

## 五、Django

### 5.1 定位

Django 是全栈 Web 框架，目标是让开发者快速构建完整的网站和数据驱动的 Web 应用。官方定位强调它提供大量开箱即用能力，包括用户认证、内容管理、站点地图、RSS 等，并且关注常见 Web 安全问题。[Django 官方概览](https://www.djangoproject.com/start/overview/)

常见组成：

- URL 路由。
- View 视图。
- Template 模板。
- ORM 数据库访问。
- Migration 数据库迁移。
- Admin 管理后台。
- Authentication 用户认证。
- Form 表单校验。
- Middleware 中间件。
- 测试工具。

### 5.2 最小示例风格

Django 通常不是只写一个 `main.py`，而是通过项目和应用组织代码：

```text
django-project/
├── manage.py
├── config/
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
└── users/
    ├── models.py
    ├── views.py
    ├── urls.py
    └── admin.py
```

这种结构适合长期维护的业务系统，但初学者需要理解项目、应用、配置、迁移和 ORM 之间的关系。

### 5.3 优点

- **功能完整**：数据库、认证、表单、后台、模板和迁移都有成熟方案。
- **适合业务系统**：用户、订单、内容、权限和后台管理等场景可以快速落地。
- **默认安全能力较多**：官方文档覆盖 SQL 注入、XSS、CSRF、点击劫持等常见风险。
- **生态成熟**：第三方插件、教程、招聘岗位和长期维护经验丰富。
- **约定清晰**：团队可以按 Django 的方式组织代码，减少项目初期的架构争论。

### 5.4 缺点

- **学习曲线较长**：需要同时学习项目结构、ORM、迁移、模板、Admin、Middleware 等。
- **框架约束较强**：不按推荐方式组织时，容易和框架机制发生冲突。
- **API-only 项目可能显得重**：如果只需要几个只读 API，Django 的完整能力未必都需要。
- **异步场景需要更谨慎**：Django 具备异步支持，但项目中的同步数据库驱动和同步第三方库仍然会影响整体模型。
- **组件替换成本较高**：当团队想完全替换 ORM、Admin 或模板体系时，需要评估框架内置功能的耦合。

### 5.5 适用场景

适合：

- 企业后台。
- CMS、内容平台和管理系统。
- 用户、权限、订单和报表系统。
- 需要成熟 ORM、Admin 和表单体系的项目。

不太适合：

- 只有几个轻量 API 的小服务。
- 需要高度定制通信协议的网络程序。
- 主要工作是异步 HTTP 聚合、WebSocket 或流式任务的服务。

## 六、Flask

### 6.1 定位

Flask 是轻量级 WSGI Web 框架。官方快速入门示例只需要创建应用对象、注册路由并返回响应，其他数据库、认证、表单和项目结构通常通过扩展或团队约定完成。[Flask 官方快速入门](https://flask.palletsprojects.com/en/stable/quickstart/)

最小示例：

```python
from flask import Flask

app = Flask(__name__)


@app.get("/")
def hello():
    return {"message": "Hello Flask"}
```

启动开发服务：

```bash
flask --app app run
```

### 6.2 优点

- **入门简单**：路由、请求、响应和模板的概念比较直接。
- **自由度高**：数据库、认证、序列化和目录结构可以按项目选择。
- **扩展丰富**：常见需求通常能找到成熟扩展。
- **适合渐进式开发**：可以从单文件原型逐步拆分为模块化项目。
- **大量历史项目使用**：排障资料和迁移经验较多。

### 6.3 缺点

- **架构需要自行决定**：项目变大后，蓝图、服务层、数据访问层和配置管理需要团队统一规范。
- **API 能力不完全内置**：请求模型校验、OpenAPI 文档、数据库和认证通常需要额外组件。
- **扩展质量和兼容性不一**：升级 Flask 或 Python 时，需要检查扩展维护状态。
- **异步不是核心编程模型**：Flask 现在支持部分 async 视图，但其 WSGI 处理模型和同步生态仍然是重要约束。[Flask 异步文档](https://flask.palletsprojects.com/en/stable/async-await/)

### 6.4 适用场景

适合：

- 小型到中型 Web 应用。
- 内部工具和管理页面。
- 需要逐步建立项目结构的团队。
- 已有 Flask 经验和扩展积累的系统。

如果项目主要是异步 I/O，可以比较 Quart、FastAPI、Sanic 或 Litestar，而不是只给 Flask 的视图函数添加 `async`。

## 七、FastAPI

### 7.1 定位

FastAPI 面向 API 和现代异步 Web 服务，建立在 Python 类型标注、Pydantic 数据处理、Starlette/ASGI 生态和 OpenAPI 标准之上。官方文档展示了自动参数校验、JSON 转换、Swagger UI、ReDoc 和 OpenAPI 文档能力。[FastAPI 官方第一步教程](https://fastapi.tiangolo.com/tutorial/first-steps/)

最小示例：

```python
from fastapi import FastAPI

app = FastAPI(title="ops-status-api")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
```

启动：

```bash
python -m uvicorn main:app --reload
```

自动文档：

```text
http://127.0.0.1:8000/docs
http://127.0.0.1:8000/redoc
```

### 7.2 主要能力

- Path、Query、Header、Cookie 和 Body 参数解析。
- Pydantic 请求和响应模型。
- 类型校验和清晰的错误响应。
- OpenAPI、Swagger UI 和 ReDoc。
- 依赖注入。
- Middleware、中间件和生命周期钩子。
- WebSocket 和流式响应。
- 适合接入 Prometheus、Kubernetes、数据库和外部 HTTP 服务。

### 7.3 优点

- **适合 API 学习和开发**：路由、类型标注、请求模型和返回模型关系清楚。
- **自动生成接口文档**：减少手工维护 API 文档的工作。
- **类型标注有实际作用**：参数类型同时用于编辑器提示、校验、转换和文档生成。
- **异步支持自然**：适合 I/O 密集型服务，但前提是依赖库也配合异步。
- **适合拆成小型服务**：可以只引入 API 所需的组件，和 Docker、CI/CD、Kubernetes 配合方便。
- **便于做只读运维接口**：例如节点状态、Prometheus 查询、服务端点和主机指标。

### 7.4 缺点

- **不是全栈网站框架**：用户认证、Admin、ORM、模板和迁移需要自行选择。
- **生态组合多**：SQLAlchemy、SQLModel、Tortoise、Alembic、各种认证库之间需要做架构决策。
- **异步容易被误用**：在 `async def` 中调用阻塞的同步库，可能阻塞事件循环。
- **类型标注是前提**：如果团队不理解 Python 类型、Pydantic 和依赖注入，代码会显得复杂。
- **业务边界需要自己设计**：路由、schemas、services、clients、repositories 等目录没有唯一标准。

### 7.5 适用场景

适合：

- REST API 和内部 API。
- Prometheus、Kubernetes、CMDB 和运维平台接口。
- AI 推理和模型服务的 HTTP 封装。
- 需要自动 OpenAPI 文档的服务。
- 多个异步外部服务的聚合接口。

选择 FastAPI 时要补齐：

- 数据库和迁移。
- 认证授权。
- 日志和请求 ID。
- 超时和重试。
- 测试和契约验证。
- Docker、进程管理和部署检查。

## 八、Sanic

### 8.1 定位

Sanic 同时提供异步 Web 框架和 Web 服务器，官方文档强调它基于 `async/await`、支持 ASGI，并以速度、扩展和生产部署为目标。[Sanic 官方介绍](https://sanic.dev/en/guide/introduction.html)

示例风格：

```python
from sanic import Sanic
from sanic.response import json

app = Sanic("ops-api")


@app.get("/healthz")
async def healthz(request):
    return json({"status": "ok"})
```

### 8.2 优点

- async-first，异步代码表达直接。
- 自带服务器，开发和部署入口比较统一。
- 适合高并发 I/O、WebSocket 和流式场景。
- API 设计相对轻量，控制力较强。

### 8.3 缺点

- 团队和社区规模通常小于 Django、Flask 和 FastAPI。
- async-first 要求团队理解事件循环、非阻塞 I/O 和阻塞库隔离。
- API 校验、数据库、认证和后台等能力仍需要额外组件。
- 从 Flask 或 Django 迁移时，不能只做少量语法替换。

### 8.4 适用场景

- 高并发异步 API。
- WebSocket、实时推送和长连接。
- 对服务器和事件循环有明确控制需求的服务。

如果团队更重视自动 OpenAPI、Pydantic 和学习资料，FastAPI 往往更容易作为第一选择。

## 九、Tornado

### 9.1 定位

Tornado 同时是 Python Web 框架和异步网络库。官方文档把它的优势放在非阻塞网络 I/O、长轮询、WebSocket 和大量长连接上，并提供 HTTP 客户端、服务器和事件循环能力。[Tornado 官方介绍](https://www.tornadoweb.org/en/stable/guide/intro.html)

### 9.2 优点

- 长连接和 WebSocket 能力成熟。
- 同时提供客户端和服务器端网络组件。
- 可以处理长轮询和持续连接场景。
- 对网络协议、连接和事件循环有较强控制力。

### 9.3 缺点

- 编程模型和 FastAPI、Flask 不完全相同。
- 普通 CRUD API 需要写的基础代码可能更多。
- 线程安全、事件循环和阻塞代码边界需要特别注意。
- 新项目团队可能更容易从 ASGI 通用框架开始。

### 9.4 适用场景

- 长连接服务。
- WebSocket 服务。
- 代理、网关、长轮询和网络编程。
- 已有 Tornado 代码和团队经验的系统。

## 十、Litestar

### 10.1 定位

Litestar 是一个可组合的 ASGI 框架，官方文档列出依赖注入、安全组件、OpenAPI、MessagePack、中间件和插件等能力。[Litestar 官方文档](https://docs.litestar.dev/2/)

### 10.2 优点

- ASGI 和类型标注支持较完整。
- 内置依赖注入、OpenAPI、插件和中间件能力。
- 适合希望在轻量和完整之间取得平衡的团队。
- 可以通过 Controller、Router 和 Handler 组织大型应用。

### 10.3 缺点

- 社区认知和第三方资料通常不如 Django、Flask、FastAPI 广泛。
- 团队需要建立自己的最佳实践和项目模板。
- 如果团队已经大量使用 FastAPI，迁移收益需要用真实需求证明。

### 10.4 适用场景

- 新建的中大型 ASGI API。
- 需要比最小 API 框架更多内置组件的项目。
- 团队愿意深入框架并维护统一工程规范的服务。

## 十一、aiohttp

### 11.1 定位

aiohttp 是基于 `asyncio` 的 HTTP 客户端和服务器库，官方文档同时覆盖 Client 和 Server 能力。它非常适合写 HTTP 客户端、爬虫、代理、异步网关和外部服务集成。

### 11.2 优点

- 异步 HTTP 客户端能力强。
- 适合并发调用多个外部 API。
- 对连接、会话、超时和流式传输有较直接的控制。
- 依赖的 Web 框架约束较少，适合做底层集成组件。

### 11.3 缺点

- 不提供 FastAPI 那样完整的参数模型和自动 API 文档体验。
- 数据校验、依赖注入、认证、项目结构和错误模型需要自行设计。
- 对初学者来说，需要同时理解 `asyncio`、Session、连接池和超时。

### 11.4 适用场景

- Prometheus 或其他 HTTP API 的异步采集器。
- 批量访问多个服务的聚合器。
- 爬虫、代理和下载服务。
- 作为 FastAPI 的底层 HTTP 客户端组件。

一个常见组合是：FastAPI 负责对外提供 API，aiohttp 或 httpx 负责调用外部异步服务。

## 十二、Quart

### 12.1 定位

Quart 是 Flask API 的 asyncio 实现，基于 ASGI。官方文档说明，熟悉 Flask 的开发者可以较容易迁移，但需要把相关处理改成 `async` 和 `await`。[Quart 官方文档](https://quart.palletsprojects.com/en/latest/)

### 12.2 优点

- 保留 Flask 风格的路由和开发体验。
- 支持异步请求、WebSocket、流式响应和长时间任务。
- 适合已有 Flask 经验、又需要 ASGI 的团队。
- 可以逐步迁移 Flask 风格的项目结构。

### 12.3 缺点

- Flask 扩展不一定完全兼容。
- 同步和异步代码混用时，边界容易变复杂。
- 自动数据模型和 OpenAPI 体验通常需要额外扩展。
- 新项目如果主要是类型驱动 API，FastAPI 可能更直接。

## 十三、Falcon

Falcon 是面向 REST API 和微服务的极简框架，同时支持 WSGI/ASGI 方向。官方定位强调可靠性、正确性和规模化性能。[Falcon 官方文档](https://falcon.readthedocs.io/)

优点：

- 抽象层较少，控制力强。
- 适合 API 和微服务。
- 关注稳定、低开销和明确的 HTTP 行为。

缺点：

- 开箱即用能力少于 Django。
- 自动校验、文档、数据库和认证需要自行组合。
- 初学者需要理解更多 HTTP 和中间件细节。

适合：对 API 边界、请求处理性能和低层控制有明确要求的团队。

## 十四、Pyramid

Pyramid 是一个可组合的 Web 框架，官方描述强调它小巧、快速，并可以从简单应用逐步扩展到复杂系统。[Pyramid 官方文档](https://docs.pylonsproject.org/projects/pyramid/en/latest/)

优点：

- 配置和组合方式灵活。
- 可以从小项目逐步扩展。
- 适合需要自定义路由、视图、认证和持久层的系统。
- 传统 WSGI 生态和文档比较完整。

缺点：

- 需要团队自己建立更多工程约定。
- 新手学习路径没有 Django 那么集中，也没有 FastAPI 那么直接。
- 新项目在招聘和社区资料方面需要评估当地生态。

## 十五、Bottle

Bottle 是一个轻量级 WSGI 微框架，官方文档强调它单文件、依赖少，提供路由、模板、请求数据和开发服务器等基础能力。[Bottle 官方文档](https://bottle.readthedocs.io/en/stable/)

优点：

- 安装和运行非常简单。
- 依赖少，适合小工具、原型和教学示例。
- 可以作为单文件程序分发。

缺点：

- 大型项目的目录、依赖、认证和数据层需要自行设计。
- 自动 API 文档、请求模型和现代异步能力不是主要卖点。
- 业务增长后，容易需要重新补齐工程能力。

## 十六、什么时候用哪个框架

### 场景一：完整业务网站和管理后台

优先看 Django：

- 用户、角色、权限、表单、后台和数据库模型较多。
- 团队希望使用成熟的一体化框架。
- 业务更像内容平台、运营后台、订单和管理系统。

### 场景二：只提供 API

优先比较 FastAPI、Flask、Litestar、Falcon：

- FastAPI：类型标注、Pydantic、OpenAPI 和异步 API。
- Flask：简单、灵活、已有 Flask 扩展或团队经验。
- Litestar：希望使用更完整的 ASGI 组件体系。
- Falcon：希望减少抽象并控制 API 层行为。

### 场景三：异步外部服务聚合

优先比较 FastAPI、aiohttp、Sanic、Litestar：

- 对外暴露 API：FastAPI 或 Litestar。
- 主要工作是并发调用外部 HTTP 服务：aiohttp 作为客户端工具。
- 需要同时掌握服务器和事件循环：Sanic。

### 场景四：WebSocket、实时推送和长连接

优先比较 FastAPI、Sanic、Tornado、Quart：

- 已有 Flask 经验：Quart。
- 需要网络库和长连接能力：Tornado。
- 需要现代 ASGI API：FastAPI 或 Sanic。

### 场景五：小脚本、内部工具或教学原型

可以考虑 Flask 或 Bottle：

- Flask 便于逐步扩展。
- Bottle 适合单文件、依赖少的简单工具。

## 十七、从 FastAPI 迁移和对比时要看什么

不要只比较路由装饰器的写法，应从以下方面比较：

### 17.1 请求和响应模型

- 参数在哪里声明。
- 类型错误如何处理。
- 是否自动转换 JSON、日期和 UUID。
- 是否有统一的响应模型。

### 17.2 数据库

- 是否自带 ORM。
- 迁移工具是否成熟。
- 是否支持异步数据库驱动。
- 事务、连接池和查询日志如何处理。

### 17.3 认证和授权

- 是否提供用户模型和会话。
- JWT、OAuth2、Cookie 和 API Key 如何接入。
- 权限控制放在哪一层。
- 默认安全配置是否明确。

### 17.4 文档和测试

- 是否生成 OpenAPI。
- 是否有测试客户端。
- 是否能对请求和响应做契约验证。
- 文档是否和代码自动保持一致。

### 17.5 部署模型

- 需要 WSGI 还是 ASGI 服务器。
- 是否支持优雅退出、健康检查和多进程。
- 容器中如何传入配置和密钥。
- 是否能方便地接入日志、指标和链路追踪。

## 十八、适合你的学习建议

你现在正在学习 FastAPI，并且目标和 Prometheus、Kubernetes、运维状态 API 有关，建议采用下面的路线：

### 第一步：先把 FastAPI 基础学完

掌握：

- `FastAPI()` 应用对象。
- `@app.get()` 和 `@app.post()` 路由。
- Path、Query、Header 和 Body 参数。
- Pydantic 模型。
- `response_model` 和状态码。
- 依赖注入。
- 异常处理。
- `/docs` 和 OpenAPI。

### 第二步：用一个项目练完整流程

在 `python/fastapi-prometheus-status` 中练习：

- `/healthz` 进程健康检查。
- `/api/v1/status` 汇总状态。
- Prometheus HTTP API 查询。
- Kubernetes 节点和服务状态。
- `healthy`、`degraded`、`unknown` 的区别。
- 超时、无数据和下游错误处理。

### 第三步：再对比 Flask 和 Django

建议顺序：

```text
FastAPI -> Flask -> Django
```

这样可以先掌握 API 和类型校验，再理解轻量框架如何组装，最后学习完整 Web 框架如何把 ORM、Admin、认证和模板整合起来。

### 第四步：有真实需求后再学异步专项框架

只有在遇到下面的需求时，再深入 Sanic、Tornado、Quart 或 aiohttp：

- WebSocket 或大量长连接。
- 高并发异步网关。
- 大量并发 HTTP 调用。
- 需要直接控制事件循环和网络协议。

## 十九、选型检查清单

在项目开始前，回答这些问题：

- 这是完整网站、管理后台，还是纯 API？
- 是否需要 ORM、迁移、用户、权限和 Admin？
- 是否有大量异步 I/O、WebSocket 或长连接？
- 团队已经熟悉哪个框架？
- 需要自动 OpenAPI 文档吗？
- 需要哪些数据库、消息队列、缓存和认证组件？
- 目标部署环境支持 WSGI、ASGI 还是两者都可以？
- 需要维护多久，未来是否会拆成多个服务？
- 官方文档、第三方扩展和团队招聘是否足够？
- 发生故障时，团队是否能读懂框架日志和调用栈？

### 一个简单的决策表

| 需求 | 优先考虑 | 需要重点确认 |
| --- | --- | --- |
| 企业后台和内容系统 | Django | ORM、Admin、权限和迁移 |
| 学习 API 和现代类型校验 | FastAPI | Pydantic、OpenAPI、异步边界 |
| 小型服务和快速原型 | Flask | 项目结构、扩展和部署 |
| 异步高并发 API | FastAPI、Sanic、Litestar | 非阻塞依赖、连接池和压测 |
| WebSocket 和长连接 | Tornado、FastAPI、Sanic、Quart | 心跳、断线、广播和资源回收 |
| 异步 HTTP 客户端和采集器 | aiohttp | Session、超时、重试和连接池 |
| 极简 REST 微服务 | Falcon | 校验、文档和组件整合 |
| 单文件小工具 | Bottle | 后续扩展边界和安全 |

## 二十、常见误区

### 误区一：框架越重越不好

框架完整意味着它替你做了更多决策。对于需要 Admin、认证、ORM 和表单的业务系统，完整框架可能反而减少重复劳动。

### 误区二：异步框架一定更快

如果业务主要等待 I/O，并且依赖库也支持异步，异步模型可能提高并发利用率。如果代码里大量使用阻塞数据库、阻塞 HTTP 客户端或 CPU 密集计算，单纯把函数改成 `async def` 不会自动解决问题。

### 误区三：接口有 `/docs` 就代表生产质量高

自动文档只说明接口描述可以生成。生产质量还要看：

- 认证和授权。
- 输入校验和敏感信息处理。
- 超时和重试。
- 日志、指标和追踪。
- 测试、备份、回滚和部署验证。

### 误区四：性能测试数字可以直接决定选型

基准测试要和真实业务结构、数据库、网络延迟、日志和部署配置一起看。先定义接口的延迟、吞吐、错误率和资源预算，再进行针对性的压测。

## 二十一、官方资料

- [Django Overview](https://www.djangoproject.com/start/overview/)
- [Django Documentation](https://docs.djangoproject.com/)
- [Flask Quickstart](https://flask.palletsprojects.com/en/stable/quickstart/)
- [Flask Async Support](https://flask.palletsprojects.com/en/stable/async-await/)
- [FastAPI Tutorial](https://fastapi.tiangolo.com/tutorial/)
- [FastAPI Features](https://fastapi.tiangolo.com/features/)
- [Sanic Introduction](https://sanic.dev/en/guide/introduction.html)
- [Tornado Introduction](https://www.tornadoweb.org/en/stable/guide/intro.html)
- [Litestar Documentation](https://docs.litestar.dev/2/)
- [aiohttp Documentation](https://docs.aiohttp.org/en/stable/)
- [Quart Documentation](https://quart.palletsprojects.com/en/latest/)
- [Falcon Documentation](https://falcon.readthedocs.io/)
- [Pyramid Documentation](https://docs.pylonsproject.org/projects/pyramid/en/latest/)
- [Bottle Documentation](https://bottle.readthedocs.io/en/stable/)

> 框架版本、Python 版本和第三方扩展都会变化。正式项目选型前，应重新检查目标版本的官方文档、支持周期、依赖兼容性和实际部署方式。
