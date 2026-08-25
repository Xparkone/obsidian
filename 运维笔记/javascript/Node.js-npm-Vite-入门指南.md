# Node.js、npm、Vite 入门指南

## 一句话结论

- **Node.js**：让 JavaScript 可以在浏览器之外运行的运行环境。
- **npm**：安装和管理 JavaScript 第三方包，并执行项目脚本的工具。
- **Vite**：面向现代前端项目的开发服务器和构建工具。

三者最常见的关系是：**先安装 Node.js，使用随 Node.js 提供的 npm 安装项目依赖，再通过 npm 启动 Vite。**

```text
操作系统
└── Node.js                         运行 JavaScript
    └── npm                         管理依赖、执行脚本
        └── 项目中的 Vite           开发服务、热更新、生产构建
            └── Vue / React / 原生 JS 应用
```

它们不是同一种东西，也不是互相替代的三个产品。

---

## 一、先理解 JavaScript 在哪里运行

JavaScript 最初主要运行在浏览器中。浏览器除了执行 JavaScript，还提供 DOM、`window`、`document` 等网页 API。

Node.js 把 JavaScript 引擎带到了浏览器之外，并提供文件、网络、进程等服务端 API：

```text
浏览器中的 JavaScript                    Node.js 中的 JavaScript
├── 操作网页 DOM                         ├── 读写文件
├── 响应点击事件                         ├── 启动 HTTP 服务
├── 调用浏览器 Web API                   ├── 执行命令行脚本
└── 运行前端页面逻辑                     └── 运行前端构建工具
```

需要注意：

- Node.js 不是一门新语言，运行的仍然是 JavaScript。
- Node.js 不是浏览器，默认没有 `window` 和 `document`。
- 浏览器也不能直接使用 Node.js 的 `fs` 等文件系统模块。

---

## 二、Node.js 是什么

Node.js 是开源、跨平台的 JavaScript 运行环境，基于 V8 JavaScript 引擎。它可以用来开发：

- Web API 和后端服务；
- 命令行工具和自动化脚本；
- WebSocket、网关等网络应用；
- 前端工程工具，例如 Vite、ESLint 和 TypeScript 编译器。

### 1. 最小示例

创建 `hello.js`：

```javascript
const message = "Hello from Node.js";
console.log(message);
```

执行：

```bash
node hello.js
```

这里的 `node` 是 Node.js 提供的命令，它负责读取并运行 JavaScript 文件。

### 2. Node.js 和前端的关系

浏览器负责运行最终的网页代码；Node.js 通常负责运行开发阶段的工具：

```text
开发阶段                                        用户访问阶段
源代码 ──Node.js/Vite──> HTML、CSS、JS 静态文件 ──浏览器──> 页面
```

因此，普通 Vite 单页应用构建完成后，生产环境通常只需要部署 `dist/` 中的静态文件，不一定需要 Node.js 常驻运行。服务端渲染项目或 Node.js 后端除外。

### 3. 常用命令

```bash
# 查看 Node.js 版本
node --version

# 执行 JavaScript 文件
node app.js

# 进入交互式环境
node
```

---

## 三、npm 是什么

npm 既指 JavaScript 软件包生态，也常指它的命令行工具。日常开发中，npm 主要负责：

- 从 npm registry 下载依赖；
- 记录项目依赖及其版本；
- 根据锁文件复现依赖树；
- 执行 `package.json` 中定义的脚本；
- 发布和管理 JavaScript 包。

通过 Node.js 官方安装包或常见 Node.js 版本管理器安装 Node.js 后，通常会同时得到 npm：

```bash
node --version
npm --version
```

### 1. npm 管理的关键文件和目录

```text
my-project/
├── package.json          项目说明、依赖声明、可执行脚本
├── package-lock.json     精确记录本次解析出的依赖树
├── node_modules/         实际安装到本机的依赖
└── src/                  项目源代码
```

#### `package.json`

示例：

```json
{
  "name": "my-project",
  "private": true,
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "devDependencies": {
    "vite": "^8.0.0"
  }
}
```

字段含义：

| 字段 | 作用 |
|------|------|
| `name` | 项目或软件包名称 |
| `private` | 防止项目被误发布到公共 registry |
| `scripts` | 项目命令的名称和实际执行内容 |
| `dependencies` | 应用运行时需要的依赖 |
| `devDependencies` | 开发、测试或构建阶段需要的依赖 |

#### `package-lock.json`

`package.json` 可能声明一个版本范围，而 `package-lock.json` 记录实际解析出的精确版本和依赖关系。应用项目通常应把锁文件提交到 Git，使本地、CI 和其他开发人员尽可能安装相同的依赖树。

#### `node_modules/`

这里存放下载后的依赖，通常体积较大且可由锁文件重新生成，一般不提交到 Git。

### 2. 常用 npm 命令

```bash
# 创建 package.json
npm init -y

# 按 package.json 安装依赖，并更新锁文件
npm install

# 安装运行时依赖
npm install axios

# 安装开发依赖
npm install --save-dev vite

# 删除依赖
npm uninstall axios

# 执行 package.json 中的脚本
npm run dev
npm run build

# 查看可执行脚本
npm run

# 查看依赖树
npm ls --depth=0
```

### 3. `npm install` 和 `npm ci` 的区别

| 命令 | 典型场景 | 行为 |
|------|----------|------|
| `npm install` | 本地开发、增删依赖 | 可更新 `package-lock.json` |
| `npm ci` | CI、可重复构建 | 要求已有锁文件，按锁文件全新安装，不修改锁文件 |

CI 流水线通常优先使用：

```bash
npm ci
npm run build
```

### 4. `npm run`、`npx` 和 `npm create`

- `npm run dev`：运行当前项目 `package.json` 中名为 `dev` 的脚本。
- `npx vite`：查找并执行软件包提供的命令，优先使用项目本地版本。
- `npm create vite@latest`：运行 Vite 提供的项目创建工具；它不是把 Vite 永久安装为全局命令。

项目工具优先安装在项目中并通过脚本执行，便于团队固定版本，不建议为方便而随意全局安装。

---

## 四、Vite 是什么

Vite 是现代前端开发工具，主要提供两部分能力：

1. 开发服务器：在本地提供页面访问、模块处理和热模块替换（HMR）。
2. 生产构建：处理和优化源代码，输出可部署的静态资源。

Vite 不是：

- JavaScript 运行环境；
- npm 的替代品；
- Vue 或 React 这样的 UI 框架；
- 默认意义上的生产 Web 服务器。

Vite 可以服务原生 JavaScript，也可通过模板和插件支持 Vue、React 等框架。

### 1. Vite 常用命令

脚手架创建的项目通常包含以下脚本：

```json
{
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  }
}
```

对应命令：

```bash
# 启动本地开发服务器，源代码改动后快速更新页面
npm run dev

# 构建生产文件，默认输出到 dist/
npm run build

# 在本机预览 dist/ 构建结果
npm run preview
```

`vite preview` 用于本地检查构建结果，不应直接当作生产服务器。生产环境可按项目形态选择 Nginx、对象存储加 CDN、容器静态服务器或平台托管服务。

### 2. Vite 在开发和生产阶段的行为

| 阶段 | 命令 | 主要行为 | 结果 |
|------|------|----------|------|
| 开发 | `npm run dev` | 启动开发服务器、按需处理模块、HMR | 本地开发地址 |
| 构建 | `npm run build` | 打包、压缩、生成带哈希的资源 | `dist/` 目录 |
| 预览 | `npm run preview` | 本地提供已构建文件 | 构建结果检查地址 |
| 生产 | 由部署方案决定 | 对外提供构建产物 | 正式站点 |

---

## 五、三者如何一起工作

以执行 `npm run dev` 为例：

```text
你输入 npm run dev
        │
        ▼
npm 读取 package.json 中的 scripts.dev
        │
        ▼
npm 找到 node_modules/.bin/vite
        │
        ▼
Node.js 运行 Vite
        │
        ▼
Vite 启动开发服务器并处理前端源代码
        │
        ▼
浏览器访问本地地址并显示页面
```

可以用一个不完全严谨但容易理解的类比：

| 工具 | 类比 | 实际作用 |
|------|------|----------|
| Node.js | 发动机 | 提供 JavaScript 运行环境 |
| npm | 仓库管理员和任务入口 | 下载依赖、管理版本、执行脚本 |
| Vite | 前端施工工具 | 启动开发环境并生成生产文件 |

---

## 六、从零创建一个 Vite 项目

下面使用原生 JavaScript 模板，避免先引入 Vue 或 React 的额外概念。

### 1. 检查环境

```bash
node --version
npm --version
```

建议安装受支持的 Node.js LTS 版本。Vite 对 Node.js 的最低版本要求会随 Vite 大版本变化；截至 2026-08-25，Vite 官方入门文档标注的要求是 Node.js `20.19+` 或 `22.12+`，部分模板可能要求更高版本。执行前应以当前官方文档和项目 `package.json` 的 `engines` 字段为准。

### 2. 创建项目

```bash
npm create vite@latest my-vite-app -- --template vanilla
cd my-vite-app
npm install
npm run dev
```

终端会显示本地访问地址，默认常见地址为：

```text
http://localhost:5173/
```

端口被占用时，Vite 可能自动选择其他端口，应以终端实际输出为准。

### 3. 查看目录

典型目录如下，具体内容可能随模板版本变化：

```text
my-vite-app/
├── index.html
├── package.json
├── package-lock.json
├── node_modules/
├── public/
└── src/
    ├── main.js
    └── style.css
```

Vite 把项目根目录的 `index.html` 作为开发入口之一，并处理其中引用的 JavaScript 和 CSS。

### 4. 修改并观察热更新

编辑 `src/main.js` 或 `src/style.css` 并保存。开发服务器运行时，浏览器通常会立即更新，不需要手工重新执行构建命令。

### 5. 构建并预览

```bash
npm run build
npm run preview
```

检查构建目录：

```bash
find dist -maxdepth 2 -type f -print
```

看到 `dist/index.html` 和资源文件只说明静态构建已经生成；是否能够正式上线，还要验证部署配置、路由回退、环境变量、后端 API、跨域、缓存和 HTTPS。

---

## 七、版本、依赖和环境变量

### 1. 版本范围

常见依赖声明：

```json
{
  "devDependencies": {
    "vite": "^8.0.0"
  }
}
```

常见符号的简化理解：

| 写法 | 含义 |
|------|------|
| `8.0.0` | 只接受指定版本 |
| `^8.0.0` | 通常允许升级到兼容的 `8.x` 版本 |
| `~8.0.0` | 通常允许补丁版本升级 |
| `latest` | registry 当前标记的最新版本，结果会随时间变化 |

真正安装的版本以 `package-lock.json` 和下面的命令结果为准：

```bash
npm ls vite
node --version
npm --version
```

### 2. Vite 环境变量

Vite 客户端代码默认只暴露以 `VITE_` 开头的环境变量：

```dotenv
VITE_API_BASE_URL=https://api.example.com
```

JavaScript 中读取：

```javascript
const apiBaseUrl = import.meta.env.VITE_API_BASE_URL;
```

客户端变量会进入浏览器可见的构建产物，**不能存放密码、Token、数据库连接串或其他秘密信息**。前端需要使用秘密信息时，应由后端保管并通过受控接口完成操作。

---

## 八、常见问题与排查

### 1. `node: command not found`

说明当前 shell 找不到 Node.js：

```bash
command -v node
echo "$PATH"
```

检查是否尚未安装、版本管理器是否未加载，或终端是否需要重新打开。

### 2. `npm: command not found`

先确认 Node.js 和 npm 是否来自同一套安装：

```bash
command -v node
command -v npm
node --version
npm --version
```

不要在原因不明时直接用 `sudo npm install -g ...` 绕过问题，这可能造成全局目录权限混乱。

### 3. `Missing script: "dev"`

当前目录的 `package.json` 没有 `dev` 脚本，或者命令在错误目录执行：

```bash
pwd
test -f package.json && sed -n '1,160p' package.json
npm run
```

### 4. `vite: command not found`

若使用 `npm run dev` 仍提示找不到 Vite，通常是依赖未安装或安装不完整：

```bash
npm ls vite
test -x node_modules/.bin/vite && echo "vite executable exists"
npm install
```

如果仓库有有效的 `package-lock.json`，CI 或干净重装场景可使用 `npm ci`。

### 5. Node.js 版本不满足要求

```bash
node --version
npm ls vite
```

根据 Vite 错误信息、官方兼容要求以及项目的 `engines` 字段选择 Node.js 版本。升级前应确认同一仓库中的其他工具是否兼容。

### 6. 端口被占用

先以 Vite 的终端输出为准。需要指定端口时：

```bash
npm run dev -- --port 5174
```

查看端口占用：

```bash
lsof -nP -iTCP:5173 -sTCP:LISTEN
```

### 7. 删除 `node_modules` 能否解决所有问题

不能。删除并重装只适用于依赖目录损坏、平台二进制不匹配等部分场景。操作前先保留错误信息并检查：

```bash
node --version
npm --version
npm ls --depth=0
git status --short
```

不要无依据地删除 `package-lock.json`；这会重新解析依赖树，可能引入与原环境不同的版本。

---

## 九、安全和生产注意事项

- 只从可信来源安装包，安装前检查包名、维护者、版本和项目地址，防止拼写相近的恶意包。
- npm 包安装时可能执行生命周期脚本；处理不可信仓库时应先审查 `package.json` 和依赖来源。
- `npm audit` 是依赖漏洞线索，不等于应用一定可被利用，也不等于执行自动修复后就安全；需要结合实际依赖路径、运行环境和公告判断。
- 不把 `.env` 中的敏感信息提交到 Git，也不把秘密信息放进 `VITE_*` 变量。
- `npm run build` 成功只证明构建命令完成，不代表页面、API、权限、监控和生产发布全部正常。
- 生产发布至少应验证页面加载、静态资源、前端路由、后端 API、错误日志和回滚方式。

---

## 十、常用命令速查

```bash
# 环境
node --version
npm --version
command -v node
command -v npm

# 创建 Vite 原生 JavaScript 项目
npm create vite@latest my-vite-app -- --template vanilla

# 项目依赖
npm install
npm ci
npm ls --depth=0

# 开发与构建
npm run dev
npm run build
npm run preview

# 查看项目脚本和 Vite 版本
npm run
npm ls vite
```

---

## 十一、容易混淆的说法

| 说法 | 是否准确 | 说明 |
|------|----------|------|
| “Node.js 是前端框架” | 不准确 | 它是 JavaScript 运行环境 |
| “npm 是下载网站” | 不完整 | npm 还包括 CLI 和 registry 等组成部分 |
| “Vite 是 Vue” | 不准确 | Vite 可配合 Vue，也支持 React 和原生 JS 等 |
| “装了 Node.js 就装了 Vite” | 不准确 | Vite 通常作为项目依赖单独安装 |
| “`npm run dev` 在运行 npm 网站” | 不准确 | npm 正在执行项目定义的 `dev` 脚本 |
| “Vite 构建后线上必须运行 Node.js” | 不一定 | 纯静态站点可直接部署 `dist/`，SSR 等场景另论 |

---

## 十二、官方资料

- [Node.js 官方介绍](https://nodejs.org/learn)
- [Node.js 官方下载页](https://nodejs.org/en/download)
- [npm 官方说明](https://docs.npmjs.com/about-npm/)
- [npm CLI 文档](https://docs.npmjs.com/cli/)
- [Vite 官方入门文档](https://vite.dev/guide/)
- [Vite 功能说明](https://vite.dev/guide/features)

文档中的版本要求与脚手架目录可能随软件更新而变化，实际使用时以项目锁文件、错误输出和当前官方文档为准。
