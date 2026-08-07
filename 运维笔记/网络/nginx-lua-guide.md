# Nginx Lua 语法与场景实践指南

> 文档版本：1.0  
> 适用读者：具备 Nginx 基础的开发工程师、运维工程师、SRE  
> 文档目标：掌握在 Nginx / OpenResty 中编写 Lua 的方式，并能按场景落地鉴权、限流、动态路由等常见能力  
> 技术栈：OpenResty（推荐）+ Lua 5.1 语法 + lua-nginx-module  
> 更新日期：2026-07-31

## 1. 文档概述

Nginx 本身擅长反向代理、负载均衡和静态资源，但遇到「按请求动态鉴权」「按用户灰度」「按 IP 限流」「改写 Header 后转发」等逻辑时，纯配置往往不够灵活。

**Nginx Lua** 指在 Nginx 请求处理链路中嵌入 Lua 脚本。常见实现是：

- **OpenResty**：以 Nginx 为核心、集成 `lua-nginx-module` 与常用 Lua 库的发行版（推荐）
- **lua-nginx-module**：给原生 Nginx 编译进 Lua 支持的模块

阅读本文后，你将能够：

1. 理解 Nginx 各处理阶段与 Lua 指令的对应关系
2. 使用 `ngx.*` API 读取请求、改写响应、控制流程
3. 在鉴权、限流、灰度、反代增强、调用 Redis/HTTP 等场景中写出可运行示例
4. 避开阻塞 IO、全局变量污染、阶段用错等常见坑

**核心结论先说清楚：**

```text
把「能用 Nginx 配置表达的规则」留给 Nginx；
把「需要动态判断、短逻辑、跨请求状态」交给 Lua；
把「复杂业务」留给上游应用服务。
```

## 2. 前置条件

### 2.1 环境要求

| 项目 | 建议 |
| --- | --- |
| 运行时 | OpenResty 稳定版（优先） |
| Lua 语法 | Lua 5.1 / LuaJIT（OpenResty 默认 LuaJIT） |
| 系统 | Linux 常见发行版均可；macOS 可用于本地试验 |
| 权限 | 能编辑 Nginx/OpenResty 配置并 reload |

> 普通官方 Nginx 默认**不带** Lua。若坚持用原生 Nginx，需自行编译 `lua-nginx-module`，并自行准备依赖库。本文示例默认按 OpenResty 写法。

### 2.2 必备基础知识

- 熟悉 `http` / `server` / `location`、`proxy_pass`、`upstream`
- 了解 HTTP 方法、Header、状态码
- 有一门脚本语言经验即可（不必先精通 Lua）

### 2.3 安装与验证

**做什么：**安装 OpenResty 并写一个最小可用接口。  
**为什么：**先确认 Lua 模块可用，再进入场景实践。  
**预期结果：**访问返回 `hello, nginx lua`。

以包管理器安装为例（发行版命令可能不同，**【需要确认】**）：

```bash
# Debian/Ubuntu 常见方式（以官方仓库说明为准）
sudo apt-get update
sudo apt-get install openresty

# 验证
openresty -v
```

最小配置（示例路径按 OpenResty 常见布局，实际路径以本机为准）：

```nginx
# /usr/local/openresty/nginx/conf/nginx.conf 片段
worker_processes  auto;

events {
    worker_connections  1024;
}

http {
    server {
        listen 8080;

        location /hello {
            default_type text/plain;
            content_by_lua_block {
                ngx.say("hello, nginx lua")
            }
        }
    }
}
```

```bash
sudo openresty -t
sudo openresty -s reload
curl -i http://127.0.0.1:8080/hello
```

预期响应体：

```text
hello, nginx lua
```

## 3. 核心概念

### 3.1 请求处理阶段与 Lua 指令

Nginx 处理一个 HTTP 请求会经过多个阶段（phase）。Lua 通过不同指令挂到对应阶段：

| 指令 | 阶段 | 典型用途 |
| --- | --- | --- |
| `init_by_lua*` | 进程加载配置时 | 加载模块、初始化全局只读数据 |
| `init_worker_by_lua*` | worker 启动时 | 定时器、每 worker 初始化 |
| `ssl_certificate_by_lua*` | TLS 握手证书选择 | 动态证书 |
| `rewrite_by_lua*` | rewrite | 改 URI、内部跳转、轻量预处理 |
| `access_by_lua*` | access | 鉴权、IP 黑白名单、准入控制 |
| `content_by_lua*` | content | 直接生成响应内容 |
| `balancer_by_lua*` | upstream 选择 | 自定义负载均衡 |
| `header_filter_by_lua*` | 响应头过滤 | 改响应头 |
| `body_filter_by_lua*` | 响应体过滤 | 改响应体（流式） |
| `log_by_lua*` | log | 自定义日志、指标上报 |

选择原则：

```text
要拦截请求（通过/拒绝）     → access_by_lua*
要改路径或做内部跳转       → rewrite_by_lua*
要自己产出 JSON/HTML       → content_by_lua*
只改响应头                 → header_filter_by_lua*
请求已结束，只做记录       → log_by_lua*
```

> 同一 `location` 里如果写了 `content_by_lua*`，通常就不要再指望同 location 的 `proxy_pass` 作为内容处理器同时生效——内容阶段一般二选一。反代增强更常见的是在 `access`/`rewrite`/`header_filter` 里改请求或响应，再配合 `proxy_pass`。

### 3.2 指令书写形式

```nginx
# 推荐：块内联，适合短逻辑
content_by_lua_block {
    ngx.say("ok")
}

# 适合中长逻辑：独立文件
content_by_lua_file /etc/openresty/lua/hello.lua;

# 旧写法（不推荐新项目使用）
# content_by_lua 'ngx.say("ok")';
```

### 3.3 关键对象

| 对象 | 含义 | 生命周期 |
| --- | --- | --- |
| `ngx.var.*` | Nginx 变量，如 `uri`、`host`、自定义变量 | 当前请求 |
| `ngx.req` | 请求方法、参数、Header、Body | 当前请求 |
| `ngx.header` | 响应头 | 当前请求 |
| `ngx.ctx` | 请求级 Lua 表，跨同请求多个阶段传数据 | 当前请求 |
| `ngx.shared.DICT` | 跨请求共享内存字典 | worker 间共享（需先声明） |
| 全局变量 `_G` | 全局状态 | 进程级；**请求间慎用** |

记住一句话：

```text
请求私有数据 → ngx.ctx
跨请求缓存/计数 → ngx.shared
配置层变量互通 → ngx.var
```

### 3.4 阻塞与非阻塞

OpenResty 的高性能来自「非阻塞」。在请求阶段：

- **推荐**：`ngx.socket.tcp`、`resty.http`、`resty.redis` 等 cosocket API
- **避免**：同步阻塞的 DNS、文件系统重 IO、普通 LuaSocket、长时间 `os.execute`

`ngx.sleep` 在支持 yield 的阶段是非阻塞让出；但并非所有阶段都允许随意挂起，阶段选错会直接报错。

## 4. Lua 语法速查（Nginx 场景常用）

OpenResty 使用的是 Lua 5.1 语法（经 LuaJIT）。以下只覆盖网关脚本最高频部分。

### 4.1 变量与类型

```lua
local name = "Ada"      -- 字符串
local n = 42            -- 数字
local ok = true         -- 布尔
local t = { a = 1 }     -- 表（唯一内建数据结构）
local f = function() end
local x = nil

-- 务必使用 local，避免污染全局且更快
```

### 4.2 表、条件、循环、函数

```lua
local user = {
    id = 1,
    roles = { "admin", "ops" },
}

if user.id > 0 then
    ngx.say("active")
elseif user.id == 0 then
    ngx.say("guest")
else
    ngx.say("invalid")
end

for i = 1, #user.roles do
    ngx.say(user.roles[i])
end

for k, v in pairs(user) do
    -- pairs 遍历哈希部分；ipairs 遍历数组部分
    ngx.log(ngx.INFO, k, "=", tostring(v))
end

local function starts_with(s, prefix)
    return string.sub(s, 1, #prefix) == prefix
end
```

### 4.3 模块组织

```lua
-- /etc/openresty/lua/auth.lua
local _M = {}

function _M.check_token(token)
    return token == "Bearer secret"
end

return _M
```

```nginx
lua_package_path "/etc/openresty/lua/?.lua;;";

server {
    location /api {
        access_by_lua_block {
            local auth = require "auth"
            local token = ngx.var.http_authorization
            if not auth.check_token(token) then
                return ngx.exit(401)
            end
        }

        content_by_lua_block {
            ngx.say("ok")
        }
    }
}
```

### 4.4 JSON

OpenResty 常用 `cjson` / `cjson.safe`：

```lua
local cjson = require "cjson.safe"

local obj = cjson.decode('{"a":1}')
if not obj then
    ngx.status = 400
    ngx.say('{"error":"invalid json"}')
    return ngx.exit(400)
end

ngx.header["Content-Type"] = "application/json"
ngx.say(cjson.encode({ ok = true, a = obj.a }))
```

## 5. 配置与指令用法

### 5.1 共享字典声明

跨请求计数、缓存、限流都依赖 `lua_shared_dict`（在 `http` 块声明）：

```nginx
http {
    lua_shared_dict my_cache 10m;
    lua_shared_dict limit_req_store 10m;

    # ...
}
```

### 5.2 与反向代理配合

常见模式：**Lua 做准入/改写，Nginx 继续反代**。

```nginx
location /app/ {
    access_by_lua_block {
        if ngx.var.http_x_api_key ~= "demo-key" then
            ngx.status = 403
            ngx.say("forbidden")
            return ngx.exit(403)
        end
    }

    proxy_set_header X-Request-Id $request_id;
    proxy_pass http://backend;
}
```

### 5.3 读取与设置 Nginx 变量

```nginx
set $user_id "";

access_by_lua_block {
    ngx.var.user_id = "u-1001"
}

add_header X-User-Id $user_id always;
```

注意：

1. 要在 Lua 里写的变量，通常需先用 `set $var "";` 声明
2. 某些内置变量只读
3. 变量值本质是字符串

## 6. 场景实践

以下示例均可放入 OpenResty 的 `server` 中验证。为便于阅读，省略了完整外围 `http/events` 骨架。

### 6.1 场景一：动态 JSON API

**做什么：**用 `content_by_lua*` 直接返回 JSON。  
**为什么：**适合网关旁路接口、健康信息、轻量聚合，不必再起一个后端。  
**预期结果：**`GET /api/ping?name=Ada` 返回 JSON。

```nginx
location /api/ping {
    default_type application/json;
    content_by_lua_block {
        local cjson = require "cjson"
        local args = ngx.req.get_uri_args()
        local name = args.name or "world"

        ngx.say(cjson.encode({
            message = "hello " .. name,
            uri = ngx.var.uri,
            time = ngx.now(),
        }))
    }
}
```

```bash
curl 'http://127.0.0.1:8080/api/ping?name=Ada'
```

### 6.2 场景二：鉴权（Bearer Token）

**做什么：**在 `access` 阶段校验 `Authorization`。  
**为什么：**未通过则尽早拒绝，避免进入反代或业务逻辑。  
**预期结果：**无 token 返回 401；合法 token 进入内容阶段。

```nginx
location /secure/ {
    access_by_lua_block {
        local auth = ngx.var.http_authorization
        if auth ~= "Bearer secret" then
            ngx.status = 401
            ngx.header["Content-Type"] = "application/json"
            ngx.say('{"error":"unauthorized"}')
            return ngx.exit(401)
        end
        -- 传给后续阶段
        ngx.ctx.user = "admin"
    }

    content_by_lua_block {
        ngx.say("welcome ", ngx.ctx.user)
    }
}
```

```bash
curl -i http://127.0.0.1:8080/secure/data
curl -i -H 'Authorization: Bearer secret' http://127.0.0.1:8080/secure/data
```

生产环境请改为验签 JWT、查缓存会话或调用认证服务；示例仅演示阶段与退出方式。

### 6.3 场景三：简单限流（shared dict）

**做什么：**按客户端 IP 限制每分钟请求次数。  
**为什么：**共享字典可在 worker 间共享计数，适合网关层粗粒度限流。  
**预期结果：**超限返回 429。

```nginx
http {
    lua_shared_dict rate_limit 10m;

    server {
        listen 8080;

        location /limited {
            access_by_lua_block {
                local dict = ngx.shared.rate_limit
                local key = "ip:" .. (ngx.var.remote_addr or "unknown")
                local limit = 60          -- 每分钟 60 次
                local ttl = 60

                local newval, err = dict:incr(key, 1, 0, ttl)
                if not newval then
                    ngx.log(ngx.ERR, "incr failed: ", err)
                    return  -- 限流组件失败时是否放行，按策略决定
                end

                if newval > limit then
                    ngx.status = 429
                    ngx.header["Retry-After"] = 60
                    ngx.say("too many requests")
                    return ngx.exit(429)
                end
            }

            content_by_lua_block {
                ngx.say("passed")
            }
        }
    }
}
```

更完整的滑动窗口、漏桶、集群限流可使用 `lua-resty-limit-traffic`。上述实现是教学向固定窗口计数。

### 6.4 场景四：灰度与 A/B 路由

**做什么：**按 Cookie 或 Header 决定内部跳转路径。  
**为什么：**网关可做流量染色，无需改客户端 URL。  
**预期结果：**带特定 Cookie 的用户进入 canary。

```nginx
location /service {
    rewrite_by_lua_block {
        local cookie = ngx.var.cookie_ab or ""
        local canary_header = ngx.var.http_x_canary or ""

        if cookie == "B" or canary_header == "1" then
            ngx.exec("/service-canary")
        end
    }

    proxy_pass http://app_stable;
}

location = /service-canary {
    internal;  # 仅允许内部跳转
    proxy_pass http://app_canary;
}
```

### 6.5 场景五：反向代理增强（改请求头 / 动态上游变量）

**做什么：**在转发前补充追踪头，并按条件切换上游。  
**为什么：**把网关横切逻辑集中在边缘，后端保持干净。  
**预期结果：**上游收到自定义头；特定用户打到专用上游。

```nginx
upstream app_a { server 10.0.0.11:8080; }
upstream app_b { server 10.0.0.12:8080; }

server {
    set $backend "app_a";

    location /proxy/ {
        access_by_lua_block {
            local uid = ngx.var.http_x_user_id or ""
            if uid ~= "" and tonumber(uid) and tonumber(uid) % 2 == 1 then
                ngx.var.backend = "app_b"
            end

            -- 若上游需要，可改请求头
            ngx.req.set_header("X-Gateway", "openresty")
            ngx.req.set_header("X-User-Id", uid)
        }

        proxy_pass http://$backend;
    }
}
```

### 6.6 场景六：调用 Redis

**做什么：**用 `resty.redis` 读取缓存用户信息。  
**为什么：**鉴权会话、黑名单、特性开关常放 Redis。  
**预期结果：**命中缓存直接返回；未命中返回 404 或回源。

```nginx
location /user {
    content_by_lua_block {
        local redis = require "resty.redis"
        local cjson = require "cjson.safe"
        local red = redis:new()
        red:set_timeouts(1000, 1000, 1000)

        local ok, err = red:connect("127.0.0.1", 6379)
        if not ok then
            ngx.status = 502
            ngx.say("redis connect failed: ", err)
            return ngx.exit(502)
        end

        local uid = ngx.var.arg_id or "1"
        local val, err = red:get("user:" .. uid)
        if not val or val == ngx.null then
            ngx.status = 404
            ngx.say('{"error":"not found"}')
            return ngx.exit(404)
        end

        -- 连接池复用
        local ok, err = red:set_keepalive(10000, 100)
        if not ok then
            ngx.log(ngx.WARN, "set_keepalive failed: ", err)
        end

        ngx.header["Content-Type"] = "application/json"
        -- 若 Redis 中已是 JSON 字符串可直接输出
        ngx.say(val)
    }
}
```

### 6.7 场景七：调用下游 HTTP 服务

**做什么：**网关聚合一个内部 HTTP 接口。  
**为什么：**适合 BFF 轻聚合、鉴权服务调用、配置中心拉取。  
**预期结果：**把下游 JSON 包装后返回。

```nginx
location /aggregate {
    content_by_lua_block {
        local http = require "resty.http"
        local cjson = require "cjson.safe"
        local httpc = http.new()
        httpc:set_timeout(2000)

        local res, err = httpc:request_uri("http://127.0.0.1:9001/meta", {
            method = "GET",
            headers = {
                ["X-Request-Id"] = ngx.var.request_id,
            },
        })

        if not res then
            ngx.status = 502
            ngx.say(cjson.encode({ error = err }))
            return ngx.exit(502)
        end

        ngx.status = res.status
        ngx.header["Content-Type"] = "application/json"
        ngx.say(cjson.encode({
            upstream_status = res.status,
            body = cjson.decode(res.body),
        }))
    }
}
```

> `resty.http` 属于 OpenResty 生态库；若环境缺失，需按发行版安装或放入 `lua_package_path`。【需要确认】本机是否已预装。

### 6.8 场景八：访问日志增强

**做什么：**在 `log_by_lua*` 中输出结构化字段。  
**为什么：**log 阶段不影响响应时延敏感路径，适合补充审计信息。  
**预期结果：**错误日志中看到自定义字段。

```nginx
location /audit {
    access_by_lua_block {
        ngx.ctx.user = ngx.var.http_x_user or "anonymous"
    }

    content_by_lua_block {
        ngx.say("done")
    }

    log_by_lua_block {
        ngx.log(ngx.INFO, "user=", ngx.ctx.user or "-",
            " uri=", ngx.var.uri,
            " status=", ngx.var.status)
    }
}
```

### 6.9 场景九：轻量防护规则

**做什么：**拦截明显恶意路径或超大查询串。  
**为什么：**边缘可挡掉一层扫描流量；复杂 WAF 请用专用方案。  
**预期结果：**命中规则返回 403。

```nginx
location / {
    access_by_lua_block {
        local uri = ngx.var.uri
        local args = ngx.var.args or ""

        if string.find(uri, "%.%.", 1, true)
            or string.find(string.lower(uri), "wp-login", 1, true)
            or #args > 2048 then
            ngx.status = 403
            ngx.say("forbidden")
            return ngx.exit(403)
        end
    }

    proxy_pass http://app_stable;
}
```

这只是示例级规则，不能替代专业 WAF。

## 7. 完整示例：鉴权 + 限流 + JSON API

把常见能力组合到一个可运行配置中。

```nginx
worker_processes auto;

events {
    worker_connections 1024;
}

http {
    lua_shared_dict rate_limit 10m;
    lua_package_path "/etc/openresty/lua/?.lua;;";

    server {
        listen 8080;
        server_name localhost;

        # 健康检查：无需鉴权
        location = /healthz {
            default_type text/plain;
            content_by_lua_block {
                ngx.say("ok")
            }
        }

        # 业务 API：限流 + Bearer 鉴权 + JSON 输出
        location /v1/hello {
            access_by_lua_block {
                -- 1) 限流
                local dict = ngx.shared.rate_limit
                local key = "v1:" .. (ngx.var.remote_addr or "unknown")
                local n, err = dict:incr(key, 1, 0, 60)
                if n and n > 120 then
                    ngx.status = 429
                    ngx.header["Content-Type"] = "application/json"
                    ngx.say('{"error":"rate_limited"}')
                    return ngx.exit(429)
                end

                -- 2) 鉴权
                local auth = ngx.var.http_authorization
                if auth ~= "Bearer secret" then
                    ngx.status = 401
                    ngx.header["Content-Type"] = "application/json"
                    ngx.say('{"error":"unauthorized"}')
                    return ngx.exit(401)
                end

                ngx.ctx.user = "demo"
            }

            content_by_lua_block {
                local cjson = require "cjson"
                local args = ngx.req.get_uri_args()

                ngx.header["Content-Type"] = "application/json"
                ngx.say(cjson.encode({
                    user = ngx.ctx.user,
                    echo = args.echo or "",
                    request_id = ngx.var.request_id,
                }))
            }

            log_by_lua_block {
                ngx.log(ngx.INFO, "user=", ngx.ctx.user or "-",
                    " status=", ngx.var.status)
            }
        }
    }
}
```

验证：

```bash
# 健康检查
curl -i http://127.0.0.1:8080/healthz

# 未带 token
curl -i 'http://127.0.0.1:8080/v1/hello?echo=hi'

# 正常请求
curl -i -H 'Authorization: Bearer secret' \
  'http://127.0.0.1:8080/v1/hello?echo=hi'
```

## 8. 常见问题与排查

| 现象 | 可能原因 | 解决方法 |
| --- | --- | --- |
| 配置测试报 unknown directive `content_by_lua_block` | 当前是原生 Nginx，未加载 Lua 模块 | 改用 OpenResty，或编译安装 `lua-nginx-module` |
| `no request ctx available` / API disabled | 在不支持的阶段调用了某些 API | 查官方 phase 兼容表，换到正确指令 |
| `attempt to yield across C-call boundary` 或 sleep/cosocket 报错 | 在禁止挂起的阶段做了非阻塞 IO | 把 IO 挪到 rewrite/access/content 等允许的阶段 |
| shared dict 为 nil | 未声明或名字写错 | 在 `http` 中加 `lua_shared_dict name size;` |
| `module 'resty.http' not found` | 库不在搜索路径 | 安装对应包或配置 `lua_package_path` |
| 变量赋值无效 | 未先 `set $var` | 先声明空值再在 Lua 中赋值 |
| 全局变量串请求 | 把请求状态放进了全局表 | 改用 `ngx.ctx` 或请求局部 `local` |
| reload 后逻辑未变 | 改的是未加载文件 / 缓存了旧模块 | 确认路径；必要时重启或设计可热更加载方式 |
| 性能突然下降 | 脚本里有阻塞 IO、正则过多、每请求创建连接 | 改 cosocket、连接池、减少每请求重计算 |

排查命令建议：

```bash
openresty -t
openresty -s reload
tail -f /usr/local/openresty/nginx/logs/error.log
```

## 9. 注意事项与最佳实践

1. **Lua 只放边缘短逻辑**：鉴权、限流、路由、头处理；复杂交易流程放后端。
2. **始终 `local`**：函数、模块引用、临时表都用局部变量。
3. **请求状态用 `ngx.ctx`**：不要用全局变量在请求间传递用户信息。
4. **共享字典要设容量与过期**：防止内存涨满；关键计数考虑失败兜底策略。
5. **优先非阻塞库**：Redis/HTTP/MySQL 用 `resty.*`，并 `set_keepalive`。
6. **阶段选对**：拒绝请求用 `access`；产出响应用 `content`；纯观测用 `log`。
7. **错误处理要明确**：连接失败时返回 502/503，并打日志，避免静默成功。
8. **安全**：示例中的明文 token 仅用于演示；生产用签名、短时凭证、最小权限。
9. **可测试性**：把规则拆到 `require` 模块，便于单测纯函数部分。
10. **可观测性**：为关键分支打 `ngx.log`，并透传 `X-Request-Id`。

适用与不适用：

| 适合 | 不太适合 |
| --- | --- |
| API 网关横切能力 | 大段业务编排、重 CPU 计算 |
| 边缘鉴权/限流/灰度 | 长耗时工作流、批量任务 |
| 轻量聚合与缓存加速 | 需要强事务一致性的核心交易 |

## 10. 总结

Nginx Lua（OpenResty）的价值，是在 Nginx 高性能事件模型里嵌入可编程能力：用阶段指令挂载逻辑，用 `ngx.*` 操作请求响应，用 `ngx.shared` 做跨请求状态，用 `resty.*` 访问 Redis/HTTP 等依赖。

掌握路径可以收敛为四步：

1. 先跑通 `content_by_lua_block` 的 Hello World  
2. 分清 `rewrite` / `access` / `content` / `log` 各自职责  
3. 按场景套用：鉴权、限流、灰度、反代增强、Redis/HTTP  
4. 把可复用逻辑模块化，并守住非阻塞与请求隔离两条底线  

### 下一步建议

1. 在本机用 OpenResty 落地第 7 节完整示例  
2. 把鉴权改为校验 JWT 或调用公司统一认证服务  
3. 限流升级为 `lua-resty-limit-traffic`，并加上监控指标  
4. 若已有网关代码仓库，把 `lua_package_path` 与配置模板纳入版本管理  

### 参考链接

- OpenResty 官方文档：<https://openresty.org/>  
- lua-nginx-module：<https://github.com/openresty/lua-nginx-module>  
- lua-resty-redis：<https://github.com/openresty/lua-resty-redis>  
- lua-resty-http：<https://github.com/ledgetech/lua-resty-http>
