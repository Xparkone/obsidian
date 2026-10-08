# Python 基础数据结构学习指南

> 面向 FastAPI 初学者的列表、元组、字典与集合入门

## 学习目标

这份笔记帮助初学者理解 Python 中最常用的容器类型，并把它们用于实际程序。读完后，你应该能够：

- 区分列表、元组、字典和集合的用途。
- 创建、读取、修改、删除和遍历这些数据结构。
- 看懂 FastAPI 接口中的 JSON 数据。
- 根据数据特点选择合适的结构。
- 识别索引、键、重复值、空值和可变性带来的常见问题。

## 先记住四个结论

- **列表 `list`**：有顺序、可以修改，适合保存一组会变化的数据。
- **元组 `tuple`**：有顺序、创建后不能直接修改，适合表示固定结构的数据。
- **字典 `dict`**：按键值对保存数据，适合表示一个对象、配置或接口响应。
- **集合 `set`**：元素不重复，适合去重和集合运算。

## 四种数据结构对比

| 类型 | 写法示例 | 是否有顺序 | 是否允许重复 | 是否可修改 | 主要访问方式 | 常见用途 |
| --- | --- | --- | --- | --- | --- | --- |
| 列表 `list` | `["api", "db"]` | 有 | 允许 | 可以 | 索引 | 一组会变化的数据 |
| 元组 `tuple` | `("prod", 8080)` | 有 | 允许 | 不可以 | 索引 | 固定的一组值 |
| 字典 `dict` | `{ "name": "api" }` | 按插入顺序保存 | 键不能重复 | 可以 | 键 | 对象、配置、接口数据 |
| 集合 `set` | `{ "api", "db" }` | 不依赖顺序 | 不允许 | 可以增删 | 成员关系 | 去重、交集、并集 |

> Python 日常开发中，很多人把“数组”作为泛称，但 Python 最常用的数组形式是 `list`（列表）。Python 还有 `array` 模块和 NumPy 数组，它们适合数值计算等特定场景；学习 FastAPI 时先掌握列表即可。

---

## 一、列表 list

### 1.1 列表是什么

列表可以保存多个元素，元素可以是字符串、数字、布尔值、字典，甚至还可以是另一个列表。列表有顺序，并且可以修改。

### 1.2 创建列表

```python
services = ["api", "worker", "database"]
ports = [8000, 8080, 5432]
mixed = ["api", 8000, True]
empty = []
```

方括号 `[]` 表示列表，元素之间使用逗号分隔。空列表可以先创建，再使用 `append()` 添加元素。

### 1.3 读取元素和索引

```python
services = ["api", "worker", "database"]

print(services[0])   # api
print(services[1])   # worker
print(services[-1])  # database
```

Python 的索引从 `0` 开始：

- `services[0]`：第一个元素。
- `services[1]`：第二个元素。
- `services[-1]`：最后一个元素。

访问不存在的索引会报错：

```python
services = ["api"]
print(services[1])  # IndexError
```

### 1.4 修改和添加元素

```python
services = ["api", "worker"]

services[1] = "scheduler"       # 修改第二个元素
services.append("database")     # 添加到末尾
services.insert(0, "gateway")   # 插入到第 0 个位置

print(services)
```

常用方法：

| 方法 | 作用 | 示例 |
| --- | --- | --- |
| `append(x)` | 添加一个元素到末尾 | `items.append("api")` |
| `extend(values)` | 添加多个元素 | `items.extend(["db", "cache"])` |
| `insert(index, x)` | 在指定位置插入 | `items.insert(0, "gateway")` |

### 1.5 删除元素

```python
services = ["api", "worker", "database"]

services.remove("worker")  # 按值删除
last = services.pop()       # 删除并返回最后一个元素
del services[0]             # 按索引删除
```

区别如下：

- `remove(value)` 删除第一个匹配的值。值不存在会报 `ValueError`。
- `pop(index)` 删除并返回指定位置的元素。不写索引时删除最后一个。
- `del items[index]` 直接删除指定索引，不返回被删元素。

### 1.6 遍历和切片

```python
services = ["api", "worker", "database"]

for service in services:
    print(service)

print(services[0:2])  # ["api", "worker"]
print(services[:2])   # 从开头取两个
print(services[1:])   # 从第二个取到结尾
```

切片格式是：

```python
items[开始位置:结束位置]
```

结束位置不包含在结果中，所以 `services[0:2]` 只包含索引 `0` 和 `1`。

### 1.7 列表常用操作

```python
numbers = [3, 1, 2, 1]

print(len(numbers))       # 元素数量
print(numbers.count(1))   # 1 出现了几次
print(numbers.index(2))   # 2 的位置
print(2 in numbers)      # 是否存在 2
```

排序需要区分 `sorted()` 和 `sort()`：

```python
numbers = [3, 1, 2]

new_numbers = sorted(numbers)  # 返回新列表，不修改原列表
print(new_numbers)
print(numbers)

numbers.sort()                 # 直接修改原列表
print(numbers)
```

- `sorted(items)` 返回一个新的排序结果。
- `items.sort()` 原地修改列表，返回值是 `None`。

### 1.8 列表推导式

先理解普通循环：

```python
squares = []
for number in range(5):
    squares.append(number * number)
```

列表推导式可以写成：

```python
squares = [number * number for number in range(5)]
even_numbers = [number for number in range(10) if number % 2 == 0]
```

初学时先掌握普通 `for` 循环，再使用列表推导式，代码更容易读懂。

### 1.9 列表容易出错的地方

- 访问不存在的索引会报 `IndexError`。
- `remove()` 按值删除，`pop()` 按位置删除。
- `items.sort()` 返回 `None`，不要写成 `new_items = items.sort()`。
- `new_items = items` 不是复制，而是让两个变量指向同一个列表。
- 列表可以混合类型，但实际项目中通常建议元素结构一致。

---

## 二、元组 tuple

### 2.1 元组是什么

元组和列表一样有顺序，但元组创建后不能直接修改。它适合表示一组固定关系，例如：

- 主机地址和端口。
- 经纬度坐标。
- RGB 颜色值。
- 函数返回的固定数量结果。

### 2.2 创建元组

```python
server = ("10.0.0.10", 8080)
coordinates = (31.23, 121.47)
empty = ()
```

单元素元组必须保留逗号：

```python
one_item = ("api",)  # 元组
not_tuple = ("api")  # 字符串
```

也可以省略括号，依靠逗号创建：

```python
server = "10.0.0.10", 8080
```

### 2.3 读取元组

```python
server = ("10.0.0.10", 8080)

print(server[0])
print(server[1])
print(server[-1])
print(len(server))
```

元组支持索引、切片、`for` 遍历和 `len()` 等读取操作，方式和列表很像。

### 2.4 元组不能修改

```python
server = ("10.0.0.10", 8080)

# server[1] = 9090  # TypeError
```

元组的不可变性可以表达“这组值应该保持固定”的意图，也能避免函数内部意外修改调用方传入的数据。

### 2.5 元组拆包

```python
server = ("10.0.0.10", 8080)
host, port = server

print(host)
print(port)
```

拆包会按照顺序把元组元素分别赋值给多个变量。变量数量通常要和元组元素数量一致。

扩展拆包：

```python
numbers = (1, 2, 3, 4, 5)
first, *middle, last = numbers

print(first)   # 1
print(middle)  # [2, 3, 4]
print(last)    # 5
```

交换变量也使用拆包：

```python
a = 1
b = 2
a, b = b, a
```

### 2.6 元组的注意事项

元组本身不能修改，但元组内部如果包含列表，列表内容仍然可以变化：

```python
data = ([1, 2], "Python")
data[0].append(3)

print(data)  # ([1, 2, 3], "Python")
```

这里没有替换元组的第一个元素，只是修改了元组内部那个列表的内容。

---

## 三、字典 dict

### 3.1 字典是什么

字典使用“键和值”保存数据：

```text
key -> value
```

键用来定位数据，值是实际内容。字典适合表示：

- 一台主机。
- 一个用户。
- 一组配置。
- 一个 API 请求或响应对象。

### 3.2 创建字典

```python
server = {
    "name": "api-01",
    "host": "10.0.0.10",
    "port": 8080,
    "enabled": True,
}

empty = {}
```

大括号 `{}` 可以创建字典。每个字段使用 `key: value` 表示，字段之间用逗号分隔。

### 3.3 读取值

```python
server = {"name": "api-01", "port": 8080}

print(server["name"])
print(server.get("port"))
print(server.get("region", "unknown"))
```

`server["key"]` 和 `server.get("key")` 的区别：

```python
server = {"name": "api-01"}

print(server["region"])              # KeyError
print(server.get("region"))          # None
print(server.get("region", "unknown"))  # unknown
```

读取不确定是否存在的配置时，优先考虑 `get()`。

### 3.4 新增和修改字段

```python
server = {"name": "api-01", "port": 8080}

server["port"] = 9090       # 修改已有字段
server["region"] = "cn"     # 新增字段
```

字典不需要提前声明字段：

- 给不存在的键赋值，就是新增。
- 给已有的键赋值，就是修改。

### 3.5 删除字段和遍历字典

```python
server = {"name": "api-01", "port": 8080}

del server["port"]

for key, value in server.items():
    print(key, value)

for key in server.keys():
    print(key)

for value in server.values():
    print(value)
```

- `items()` 同时遍历键和值。
- `keys()` 只遍历键。
- `values()` 只遍历值。

也可以使用 `pop()` 删除并取得值：

```python
server = {"name": "api-01", "port": 8080}
port = server.pop("port", None)
print(port)
```

### 3.6 判断键是否存在

```python
user = {
    "name": "Alice",
    "age": 18,
}

if "name" in user:
    print(user["name"])
```

字典中的 `in` 默认检查键，不检查值：

```python
"name" in user          # 检查键
"Alice" in user         # 不会检查值
"Alice" in user.values()  # 检查值
```

### 3.7 嵌套字典和列表

实际 API 返回经常是字典里面包含列表，列表里面又包含字典：

```python
response = {
    "status": "ok",
    "data": {
        "nodes": [
            {"name": "node-1", "ready": True},
            {"name": "node-2", "ready": False},
        ]
    }
}

print(response["data"]["nodes"][0]["name"])
```

读取时从外到内逐层取值：

1. 先取 `data`。
2. 再取 `nodes`。
3. 再取第一个元素 `[0]`。
4. 最后取 `name`。

### 3.8 字典容易出错的地方

- 直接访问不存在的键会报 `KeyError`。
- 字典键必须是可哈希类型，字符串、整数和元组通常可以作为键，列表不能作为键。
- 字典的键必须唯一，重复键会覆盖前面的值：

```python
data = {"a": 1, "a": 2}
print(data)  # {"a": 2}
```

- 不要在遍历字典时直接增删字段，否则可能报 `RuntimeError`。
- 不要把密码、Token、Cookie 等敏感信息写入示例代码或提交到仓库。

---

## 四、集合 set

### 4.1 集合是什么

集合保存不重复的元素，适合：

- 列表去重。
- 判断成员是否存在。
- 求交集、并集、差集。

集合没有稳定的索引，不适合依赖元素位置的场景。

### 4.2 创建集合和去重

```python
services = {"api", "worker", "api"}
print(services)  # 重复元素只保留一次

items = ["api", "api", "db"]
unique_items = set(items)
print(unique_items)
```

创建空集合必须使用 `set()`：

```python
empty_set = set()
empty_dict = {}
```

因为 `{}` 表示空字典。

### 4.3 添加、删除和查询

```python
tags = {"python", "linux"}

tags.add("docker")
tags.update(["kubernetes", "git"])

tags.remove("git")
tags.discard("unknown")

print("python" in tags)
```

- `add(x)` 添加一个元素。
- `update(values)` 添加多个元素。
- `remove(x)` 删除元素，不存在会报 `KeyError`。
- `discard(x)` 删除元素，不存在也不会报错。
- `pop()` 删除并返回一个元素，但不能预测会删除哪个，因为集合不依赖固定顺序。

### 4.4 集合运算

```python
a = {1, 2, 3}
b = {3, 4, 5}

print(a | b)  # 并集 {1, 2, 3, 4, 5}
print(a & b)  # 交集 {3}
print(a - b)  # 差集 {1, 2}
print(a ^ b)  # 对称差集 {1, 2, 4, 5}
```

也可以使用方法形式：

```python
a.union(b)
a.intersection(b)
a.difference(b)
a.symmetric_difference(b)
```

判断子集和超集：

```python
small = {1, 2}
large = {1, 2, 3}

print(small.issubset(large))   # True
print(large.issuperset(small)) # True
```

### 4.5 集合容易出错的地方

- 集合不能使用索引，例如 `items[0]` 会报错。
- 集合输出顺序不应该作为业务逻辑依据。
- 使用集合去重可能丢失原列表顺序。
- 集合元素必须是可哈希对象，不能直接放列表或字典。

如果需要去重并保留原顺序，可以使用：

```python
items = ["api", "api", "db", "api"]
unique_items = list(dict.fromkeys(items))
print(unique_items)  # ["api", "db"]
```

---

## 五、赋值、可变对象和复制

这是列表和字典中最容易混淆的部分。

### 5.1 赋值不是复制

```python
a = [1, 2]
b = a

b.append(3)
print(a)  # [1, 2, 3]
```

`a` 和 `b` 指向同一个列表。修改 `b`，`a` 也会看到变化。

### 5.2 浅复制

```python
a = [1, 2]
b = a.copy()

b.append(3)
print(a)  # [1, 2]
print(b)  # [1, 2, 3]
```

常见浅复制写法：

```python
b = a.copy()
b = a[:]
b = list(a)
```

如果列表中还有嵌套列表，浅复制只复制外层：

```python
a = [[1, 2], [3, 4]]
b = a.copy()

b[0][0] = 99
print(a)  # [[99, 2], [3, 4]]
```

### 5.3 深复制

需要完整复制嵌套结构时，可以使用 `deepcopy()`：

```python
import copy

a = [[1, 2], [3, 4]]
b = copy.deepcopy(a)

b[0][0] = 99
print(a)  # [[1, 2], [3, 4]]
print(b)  # [[99, 2], [3, 4]]
```

### 5.4 函数参数中的可变对象

```python
def add_item(items):
    items.append("new")


data = []
add_item(data)
print(data)  # ["new"]
```

函数可以直接修改传入的列表或字典。设计函数时，要明确这种修改是否是预期行为。

---

## 六、如何选择数据结构

可以使用下面的简单规则：

- 需要按位置保存一组可变数据：用列表。
- 需要表示固定、不应改变的一组数据：用元组。
- 需要通过名称或字段查找数据：用字典。
- 需要去重或做交集、并集、差集：用集合。
- 需要保留顺序且去重：使用 `dict.fromkeys()` 或手动维护集合。
- 需要让对象成为字典键或集合元素：确认对象是可哈希的。

| 问题 | 推荐类型 | 理由 |
| --- | --- | --- |
| 数据会变化并且需要保持顺序吗 | 列表 `list` | 支持增删改和索引 |
| 这组数据创建后应该固定吗 | 元组 `tuple` | 不能被直接修改 |
| 需要通过名称查找值吗 | 字典 `dict` | 通过键快速定位 |
| 只关心唯一值或集合运算吗 | 集合 `set` | 自动去重并支持集合运算 |

---

## 七、和 FastAPI 的关系

FastAPI 接口经常接收和返回 JSON。常见对应关系如下：

| JSON | Python | FastAPI 中的常见场景 |
| --- | --- | --- |
| `{ "name": "api" }` | `dict` | 请求体或响应对象 |
| `["api", "db"]` | `list` | 服务列表、节点列表 |
| `true` / `false` | `bool` | 健康状态、开关字段 |
| `null` | `None` | 缺失或未知的值 |

示例接口：

```python
from fastapi import FastAPI

app = FastAPI()


@app.get("/services")
def list_services():
    return {
        "services": [
            {"name": "api", "status": "healthy"},
            {"name": "worker", "status": "degraded"},
        ]
    }
```

这里最外层是字典，`services` 的值是列表，列表中的每个元素又是字典。这种结构是运维状态接口中常见的返回格式。

---

## 八、综合示例

下面的示例同时使用了列表、元组、字典和集合：

```python
students = [
    {
        "name": "Alice",
        "subjects": ("math", "english"),
        "scores": {"math": 95, "english": 88},
        "tags": {"python", "beginner"},
    },
    {
        "name": "Bob",
        "subjects": ("math", "english"),
        "scores": {"math": 78, "english": 91},
        "tags": {"linux", "beginner"},
    },
]
```

结构说明：

- 最外层是列表，表示多个学生。
- 每个学生是一个字典。
- `subjects` 是元组，因为科目结构固定。
- `scores` 是字典，通过科目名称查成绩。
- `tags` 是集合，用于保存不重复的标签。

可以设计以下练习：

- 找出所有学生姓名。
- 计算 Alice 的平均分。
- 找出所有出现过的标签。
- 求两个学生标签的交集。
- 给某个学生增加一个标签。
- 按数学成绩排序。

---

## 九、练习题

建议先自己写，再对照答案。练习的目标不是记住每个方法，而是根据数据特点选出合适的结构。

1. 创建一个列表，保存三个服务名，追加一个服务后打印全部服务。
2. 创建一个元组，保存主机地址和端口，并使用拆包分别得到 `host` 和 `port`。
3. 创建一个字典，保存节点名称、Ready 状态和 IP 地址。使用 `get()` 读取不存在的 `region`。
4. 把包含重复服务名的列表转换成集合，得到不重复的服务名。
5. 用列表保存五个数字，计算最大值、最小值和平均值。
6. 使用两个集合计算两组服务标签的交集。
7. 解释 `a = b`、`a.copy()` 和 `copy.deepcopy(a)` 的区别。

### 练习参考答案

```python
services = ["api", "worker", "db"]
services.append("cache")
print(services)

server = ("10.0.0.10", 8080)
host, port = server
print(host, port)

node = {
    "name": "node-1",
    "ready": True,
    "ip": "10.0.0.20",
}
print(node.get("region", "unknown"))

names = ["api", "api", "db"]
print(set(names))
```

---

## 十、常见错误速查

| 现象 | 原因 | 处理方式 |
| --- | --- | --- |
| `IndexError` | 列表索引不存在 | 先检查 `len(items)` 和索引范围 |
| `KeyError` | 字典中没有这个键 | 使用 `get()` 或先判断 `key in dict` |
| `TypeError: tuple does not support item assignment` | 尝试修改元组 | 创建新元组或改用列表 |
| `{}` 得到的是字典 | 空集合写法错误 | 使用 `set()` 创建空集合 |
| `IndexError` 或 `KeyError` | 把索引和值混淆 | 区分列表索引和字典键 |
| `list.sort()` 结果为 `None` | `sort()` 原地排序 | 直接调用，或使用 `sorted()` |
| `remove()` 报错 | 要删除的值不存在 | 先判断，或根据场景使用 `pop()` |
| 集合不能用索引 | 集合没有位置索引 | 使用 `in` 判断成员 |
| 修改副本却影响原数据 | 两个变量共享对象或浅复制 | 使用 `copy()` 或 `deepcopy()` |
| 遍历字典时删除元素报错 | 修改了字典大小 | 遍历 `list(data)` 的副本 |

---

## 十一、下一步学习顺序

1. 字符串、数字、布尔值和 `None`。
2. `if`、`for`、`while`、函数和异常处理。
3. Pydantic 请求模型和响应模型。
4. FastAPI 的 Path、Query、Body 参数。
5. Prometheus 和 Kubernetes 状态接口中的字典、列表嵌套结构。
6. Python 模块、包和 FastAPI `routers` 目录拆分。

完成本文练习后，可以继续把 FastAPI 示例扩展为 `/healthz`、`/items` 和 `/services` 三个接口，分别练习字典、列表、路径参数和请求体。
