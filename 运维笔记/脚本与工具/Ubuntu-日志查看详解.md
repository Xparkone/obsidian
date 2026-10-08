# Ubuntu 日志查看详解

## 1. 先记住怎么用这篇文档

Ubuntu 上的排障日志主要来自两套系统：`systemd-journald` 管理的二进制日志（用 `journalctl` 查看），以及 `rsyslog` 落盘在 `/var/log` 下的文本日志。内核消息两套系统都会收集，此外还可以用 `dmesg` 直接看内核环形缓冲区。

这篇文档适合回答三类问题：

1. **日志在哪里、是谁写的**：先看第 2 章的体系总览和 `/var/log` 目录表。
2. **某个时间段、某个服务、某种级别的日志怎么看**：看第 3 章 `journalctl` 和第 4 章文本日志的过滤方法。
3. **遇到具体故障从哪条命令开始**：直接翻第 7 章排障场景速查，照着命令组合执行，再按「解读要点」判断。

一个比较稳妥的定位顺序是：

```text
明确故障时间点 → 用 journalctl -b / --since 圈定范围 → 按服务或优先级收窄
→ 必要时回 /var/log 文本日志和已轮转的 .gz 文件交叉验证
```

本文所有命令以 Ubuntu 20.04 / 22.04 / 24.04 默认安装为准（systemd 245+）。极少用到的或各版本行为不一致的参数会单独标注，未标注的均可直接使用。示例中的时间、主机名、PID、IP 都是示意值，执行前请替换为本机实际值。

另外提醒：日志里天然带有主机名、用户名、来源 IP、命令行参数甚至脱敏不彻底的令牌。把日志片段粘到工单、群聊或外部服务之前，先扫一遍敏感信息。

## 2. Ubuntu 日志体系总览

### 2.1 journald 与 rsyslog 的分工

Ubuntu 默认同时运行两套日志系统，理解它们的先后关系，排障时就不会纠结「为什么 `journalctl` 里有而 `syslog` 里找不到」：

```text
内核 printk ──┐
服务 stdout/stderr（systemd 接管） ──┼─► systemd-journald ─► rsyslogd ─► /var/log 文本日志
syslog() 接口 ──┘
```

- **systemd-journald 先收集**：内核消息、systemd 管理的服务输出、syslog 调用都会先进 journald。每条记录带结构化字段（时间、优先级、unit、PID、UID 等），存放在 `/var/log/journal/`（持久化）或 `/run/log/journal/`（易失）。
- **rsyslog 再落盘**：rsyslog 从 journald 读取消息，按 `/etc/rsyslog.d/50-default.conf` 的规则过滤，写成便于人读的文本文件。`auth.log`、`kern.log` 这些按主题拆分的文件就是 rsyslog 规则的产物。

由此得到两个实用结论：

1. journald 的记录更全（包含被 rsyslog 规则丢弃的低优先级消息），文本日志更方便 `grep`。两边查到的时间戳应能对上，对不上时以 journald 为准。
2. 重启 rsyslog 只会中断文本落盘，不会丢 journald 里的记录；反过来停掉 journald，rsyslog 也就没了来源，两边都会受影响。

### 2.2 /var/log 目录全貌

Ubuntu 默认安装（含云镜像）下，`/var/log` 常见文件与子目录如下。其中 nginx、apache2、mysql、postgresql、fail2ban 等条目要对应软件包安装后才会有；`ufw.log` 需要 UFW 开启日志记录；cloud-init 相关日志只在云镜像或装过 cloud-init 的系统上可见：

| 文件 / 目录 | 记录内容 | 典型查看方式 |
|---|---|---|
| `syslog` | 系统综合日志，几乎所有服务的消息都汇一份 | `less`、`grep`、`tail -f` |
| `auth.log` | 认证相关：SSH 登录、sudo、PAM、su、用户增删 | 排查登录异常的主战场 |
| `kern.log` | 内核消息，与 `dmesg` 同源但持续追加 | 硬件、驱动、OOM、防火墙丢包 |
| `daemon.log` | 后台守护进程消息（按 facility 拆分自 syslog） | 服务排障补充 |
| `debug` | debug 级别的消息，量可能很大 | 一般只在开调试时看 |
| `dpkg.log` | deb 包的安装、升级、移除记录（按次逐条） | 追溯软件变更时间线 |
| `apt/history.log` | APT 事务历史，含完整命令行与操作人 | `grep Commandline` |
| `apt/term.log` | APT 事务的终端输出细节 | 安装失败时回看报错 |
| `unattended-upgrades/` | 自动安全更新的执行日志 | 确认是否被自动升级影响 |
| `cloud-init.log`、`cloud-init-output.log` | 云主机首次启动初始化过程与输出 | 云实例初始化失败排查 |
| `nginx/` | Nginx 的 `access.log` / `error.log` 等 | Web 访问与错误分析 |
| `apache2/` | Apache 的访问与错误日志 | 同上 |
| `journal/` | journald 持久化二进制日志 | 只用 `journalctl` 读，别直接动文件 |
| `ufw.log` | UFW 防火墙放行/拦截记录 | 网络连通性排查 |
| `fail2ban.log` | fail2ban 封禁/解封动作 | 确认 IP 是否被误封 |
| `mysql/`、`postgresql/` | 数据库错误日志 | 数据库排障 |
| `btmp` | 失败登录记录（二进制） | `sudo lastb` |
| `wtmp` | 登录/登出/重启记录（二进制） | `last`、`last -x` |
| `lastlog` | 每个用户最近一次登录（二进制） | `lastlog` |
| `alternatives.log` | `update-alternatives` 切换记录 | 排查默认程序被改 |
| `dist-upgrade/` | 发行版大版本升级日志 | do-release-upgrade 失败回看 |
| `installer/`、`bootstrap.log` | 系统安装阶段日志 | 装机遗留问题 |

`btmp`、`wtmp`、`lastlog` 是二进制格式，不要用 `cat` 看。云镜像默认装 cloud-init，物理机或手工安装的系统可能没有 `cloud-init*.log`，属于正常差异。

### 2.3 二进制日志与文本日志的取舍

| 需求 | 更适合的工具 |
|---|---|
| 按服务、按启动次数、按结构化字段精确过滤 | `journalctl` |
| 快速 `grep`、和其他文本工具（awk/sed）拼接 | `/var/log` 文本日志 |
| 看内核环形缓冲区最新内容 | `dmesg` / `journalctl -k` |
| 查几个月前的旧记录（取决于轮转和保留策略） | 已轮转的 `.gz` 文本日志 |
| 导出结构化数据给程序处理 | `journalctl -o json` |

注意容器和 WSL1 环境里通常没有运行 systemd，`journalctl` 不可用，只能看应用自己写的日志文件；WSL2 和常规虚拟机/物理机不受影响。

## 3. journalctl 详解

不带参数执行 `journalctl` 会按时间正序输出本次收集到的全部日志（默认经 pager 分页）。实际排障几乎都是「先过滤再翻页」，下面按过滤维度展开。

### 3.1 按服务过滤：`-u`

| 命令 | 作用 |
|---|---|
| `journalctl -u ssh` | 只看 ssh 服务的日志（unit 名，可省略 `.service`） |
| `journalctl -u ssh.service` | 同上，写法更严谨 |
| `journalctl -u nginx -u mysql` | 多个 `-u` 是「或」的关系 |
| `journalctl -u cron --since today` | `-u` 可与时间等条件叠加 |

```bash
journalctl -u ssh -n 50 --no-pager
journalctl -u nginx.service -f
```

`-u` 只匹配 systemd 接管的输出。服务自己写的日志文件（如 Nginx 的 access.log）不在其中，需要去第 4 章的文本文件里找。用 `systemctl list-units --type=service` 确认本机 unit 的准确名字，猜错名字只会得到空输出，不会报错。

### 3.2 按时间过滤：`--since` / `--until`

支持绝对时间、相对时间和口语化写法，可单独用也可成对用（闭区间）：

| 命令 | 作用 |
|---|---|
| `journalctl --since "1 hour ago"` | 最近 1 小时 |
| `journalctl --since "30 min ago"` | 最近 30 分钟 |
| `journalctl --since today` | 今天 0 点至今 |
| `journalctl --since yesterday --until today` | 昨天一整天 |
| `journalctl --since "2026-09-29 10:00:00" --until "2026-09-29 10:30:00"` | 指定半小时窗口 |
| `journalctl -u nginx --since "2026-09-29" --until "2026-09-30"` | 与服务过滤叠加 |

```bash
journalctl -u mysql --since "2026-09-29 03:00:00" --until "2026-09-29 04:00:00" --no-pager
journalctl --since "10 min ago" -p err --no-pager
```

只写日期表示当天 00:00:00；写相对时间时注意用的是当前系统时区。跨时区协作或服务器时区混乱时，先用 `timedatectl` 确认本机时区，再圈时间窗，避免「查了错的半小时」。

### 3.3 按优先级过滤：`-p`

沿用 syslog 的 0～7 级优先级，数字越小越严重：

| 级别 | 数字 | 名称 | 含义 |
|---|---|---|---|
| emerg | 0 | 紧急 | 系统不可用 |
| alert | 1 | 警报 | 必须立即处理 |
| crit | 2 | 危险 | 严重错误状态 |
| err | 3 | 错误 | 出错（排障最常用的过滤起点） |
| warning | 4 | 警告 | 潜在问题 |
| notice | 5 | 提示 | 正常但值得注意 |
| info | 6 | 信息 | 常规运行消息 |
| debug | 7 | 调试 | 仅调试期有用 |

`-p err` 表示「err 及更严重的全部（0～3）」；还支持范围写法，如 `-p info..debug` 只含 info 与 debug 两级，`-p 3..5` 则等价于 err 到 warning。

```bash
journalctl -u ssh -p err --since today --no-pager
journalctl -p warning --since "1 hour ago" --no-pager    # warning 及以上
```

两个提醒：其一，优先级由服务自己上报，很多应用把真错误打成 info 甚至 stdout，`-p err` 为空不代表没问题；其二，看排查对象的完整上下文时应去掉 `-p`，错误前后的 info 行往往才说明因果。

### 3.4 按开机次数过滤：`-b`

| 命令 | 作用 |
|---|---|
| `journalctl -b` | 只看本次开机以来的日志 |
| `journalctl -b -1` | 上一次开机的日志 |
| `journalctl -b -3` | 倒数第三次开机的日志 |
| `journalctl --list-boots` | 列出 journal 里保存的所有开机记录及时间范围 |

```bash
journalctl --list-boots
journalctl -b -1 -n 200 --no-pager     # 上次开机时发生了什么
journalctl -b -1 -u nginx --no-pager   # 上次开机期间 nginx 的日志
```

`-b -1` 查历史开机依赖 journald 持久化。Ubuntu 默认创建 `/var/log/journal`，历史开机日志通常都在；若该目录不存在，只能看本次开机，可按第 8.1 节开启持久化。

### 3.5 实时跟踪与只看内核：`-f`、`-k`

| 命令 | 作用 |
|---|---|
| `journalctl -f` | 类似 `tail -f`，实时滚动全部日志 |
| `journalctl -fu nginx` | 实时滚动指定服务 |
| `journalctl -k` | 只看内核消息，等价于读 dmesg 的内容进 journal |
| `journalctl -kf` | 实时滚动内核消息 |

```bash
journalctl -u ssh -f --since "5 min ago"
journalctl -k -b --no-pager | grep -i error
```

`-f` 与高负载机器上日志洪峰叠加时，终端可能刷屏，建议始终带上 `-u` 或 `--since` 收窄范围。配合 `grep` 过滤时使用 `--no-pager`，不要把 pager 挂在管道中间。

### 3.6 按字段过滤：`_PID=`、`_UID=`、可执行文件路径

journal 每条记录都带结构化字段，直接按字段匹配（多个条件是「与」关系）：

| 命令 | 作用 |
|---|---|
| `journalctl _PID=1234` | 只看 PID 1234 的日志 |
| `journalctl _UID=1000` | 只看 UID 1000 用户的进程日志 |
| `journalctl _COMM=sshd` | 按进程名过滤 |
| `journalctl /usr/sbin/sshd` | 按可执行文件路径过滤（直接跟路径即可） |
| `journalctl _SYSTEMD_UNIT=nginx.service` | 与 `-u` 等价的字段写法 |
| `journalctl -N --no-pager` | 列出当前 journal 里出现过的全部字段名 |

```bash
journalctl _PID=1 --since "1 hour ago" --no-pager
journalctl /usr/sbin/cron --since today --no-pager
journalctl _UID=0 -p err --no-pager
```

`journalctl -o verbose` 可以查看单条记录带有的全部字段，写过滤条件前先用它确认字段确实存在、值是什么形态。PID 会复用，按 `_PID` 过滤时务必同时限定时间窗口；进程重启后旧 PID 的历史会和新记录混在一起。

### 3.7 输出格式、分页与翻页

| 命令 | 作用 |
|---|---|
| `journalctl -o short-precise` | 默认格式，时间戳精确到微秒 |
| `journalctl -o short-iso` | ISO 格式时间（`2026-09-29T10:00:00+08:00`），对齐多时区 |
| `journalctl -o json-pretty` | 每条记录完整字段的多行 JSON |
| `journalctl -o cat` | 只输出消息正文本，最干净，适合管道 |
| `journalctl -o verbose` | 显示记录的全部字段 |
| `journalctl -n 100` | 只显示最近 100 行；`-n` 不带数字默认 10 行 |
| `journalctl -e` | 直接跳到末尾 |
| `journalctl -r` | 反序（最新在前） |
| `journalctl --no-pager` | 不分页直接输出，脚本与管道必备 |

```bash
journalctl -u ssh --since today -o cat --no-pager | grep -c "Accepted"
journalctl -p err --since "1 hour ago" -o json-pretty --no-pager | head -40
journalctl -u nginx -r -n 100 --no-pager
journalctl -b --no-pager > /tmp/boot-$(date +%Y%m%d).log
```

不带过滤条件时输出会进 `less` 分页，适合交互翻看；写进脚本、管道或重定向时必须带 `--no-pager`，否则会卡在分页或混入控制字符。导出到 `/tmp` 的日志文件同样含主机名、用户名、IP，发送出去前先脱敏。

### 3.8 磁盘占用查看与清理：vacuum

| 命令 | 作用 |
|---|---|
| `journalctl --disk-usage` | 查看 journal 占用的磁盘总量 |
| `sudo journalctl --vacuum-time=7d` | 只保留最近 7 天的日志 |
| `sudo journalctl --vacuum-size=500M` | 收缩到不超过 500 MB |
| `sudo journalctl --vacuum-files=10` | 最多保留 10 个归档文件 |

```bash
journalctl --disk-usage
sudo journalctl --vacuum-time=7d
journalctl --disk-usage        # 再次确认收缩结果
```

vacuum 是物理删除历史记录，执行后不可恢复。有合规保留要求或故障待复盘的主机，先备份 `/var/log/journal` 再清理。不要直接 `rm /var/log/journal/*`：正在写入的 journal 文件被删除可能损坏索引，正确做法就是 vacuum 或调整第 8.2 节的容量上限让 journald 自己滚。

## 4. 传统文本日志查看

rsyslog 落盘的文本日志胜在「什么都能 grep」，也是审计脚本、第三方工具最常对接的形态。

### 4.1 各文件的打开方式

```bash
less /var/log/syslog
grep ssh /var/log/auth.log | tail -20
tail -n 100 /var/log/kern.log
less /var/log/cloud-init-output.log        # 云主机初始化输出
tail -f /var/log/nginx/access.log          # Nginx 访问日志
tail -f /var/log/nginx/error.log           # Nginx 错误日志
```

`/var/log/auth.log`、`/var/log/syslog` 属 `syslog:adm` 组，普通用户读不了时加 `sudo`，或把自己加入 `adm` 组。不要用 `cat` 整体输出大日志文件刷屏，用 `less` 翻页或先 `tail`/`grep` 截取。

### 4.2 实时跟踪：`tail -f`、`tail -F`、`less +F`

| 命令 | 作用 |
|---|---|
| `tail -f /var/log/syslog` | 跟踪文件，轮转后仍跟在旧文件句柄上（看不到新内容） |
| `tail -F /var/log/syslog` | 按文件名跟踪，日志轮转后自动重开新文件，生产排障应优先用它 |
| `less +F /var/log/syslog` | 在 less 内滚动查看，按 `Ctrl-C` 暂停跟踪翻历史，按 `F` 恢复跟踪 |

`tail -f` 与 `tail -F` 的区别在日志发生轮转的那一刻才显现：rsyslog 类日志通常每天/每周被 logrotate 换名压缩，`-f` 还在读已被重命名的旧 inode，屏幕会「突然安静」让人误以为没有新日志。长时间挂着观察的窗口，一律用 `tail -F`。

### 4.3 检索与按时间截取

syslog 风格的时间戳是 `Sep 29 10:20:01`，没有年份，按时间截取靠正则：

```bash
grep "Failed password" /var/log/auth.log | tail -20      # 关键字检索
grep -i "error" /var/log/syslog | tail -50               # -i 忽略大小写
awk '/^Sep 29 1[0-2]:/' /var/log/syslog                  # 取 29 日 10～12 点
awk '/^Sep 29 10:2[0-9]:/' /var/log/syslog               # 精确到 10:20～10:29
grep -v "CRON" /var/log/syslog | tail -100               # 排除噪音行
```

跨年边界翻旧日志时要特别小心：`Sep` 打头的行可能是去年 9 月的。需要精确时间线时回 `journalctl --since` 用 ISO 时间过滤，两边对照。

### 4.4 检索已轮转的压缩日志：zgrep / zcat

轮转后的历史日志被 gzip 压缩，`grep` 读不了，用 `zgrep` / `zcat`：

```bash
zgrep "Failed password" /var/log/auth.log.2.gz
zgrep -i "error" /var/log/syslog.*.gz                    # 全部压缩归档一起搜
zcat /var/log/syslog.2.gz | head -20
```

覆盖「当前 + 全部归档」的完整检索可以拼起来：

```bash
grep "Out of memory" /var/log/syslog              # 当前文件
zgrep -h "Out of memory" /var/log/syslog.*.gz     # 全部压缩归档
```

`syslog.*.gz` 的通配同时覆盖按序号滚动的归档；查多个月前的记录前先确认保留策略（第 6 章），别对已被清理的历史下结论。

## 5. 内核日志 dmesg

`dmesg` 直接读内核环形缓冲区，适合看硬件识别、驱动报错、OOM、防火墙丢包这类内核视角的事件。Ubuntu 默认启用 `kernel.dmesg_restrict=1`，普通用户需要 `sudo`。

### 5.1 常用参数

| 命令 | 作用 |
|---|---|
| `sudo dmesg` | 输出全部内核环形缓冲（直接刷到终端，请配合后面的参数） |
| `sudo dmesg -T` | 把时间戳转成人类可读的日期时间 |
| `sudo dmesg -l err,warn` | 只显示 err 和 warn 级别（可多级别逗号分隔） |
| `sudo dmesg -w` | 实时跟踪新内核消息，等价于 `journalctl -kf` |
| `sudo dmesg --since "1 hour ago"` | 按相对时间过滤（见下方版本说明） |
| `sudo dmesg -H` | 人类友好分页模式（等价 `-T` + pager） |

```bash
sudo dmesg -T | grep -iE "error|fail|killed"
sudo dmesg -T -l err,crit,alert,emerg
sudo dmesg -Tw                 # 实时滚动、人类可读时间
sudo dmesg -T | less
```

`--since`（与 `--until`）是 util-linux 2.35 起加入的参数：Ubuntu 22.04 / 24.04 可用，20.04（util-linux 2.34）不支持，在 20.04 上请改用 `-T` 加 `grep` 时间范围。拿不准本机是否支持时，`dmesg --help` 先看一眼。

### 5.2 与 journalctl -k 的关系

journald 会持续把内核消息收进 journal，因此：

```bash
sudo dmesg -T | tail -5
journalctl -k -n 5 --no-pager
```

两者内容同源，差异在于：

- `dmesg` 只看当前环形缓冲区，缓冲区被刷满后旧消息被覆盖；
- `journalctl -k` 可查 journal 保存的历史开机内核消息（`journalctl -k -b -1`），时间上能倒得更远。

排障时优先 `journalctl -k` 圈历史，`dmesg -Tw` 盯实时，两者互补。

### 5.3 时间戳的坑

`dmesg` 原始行首的 `[12345.678]` 是**本次开机以来的秒数**，不是墙上时间。`-T` 是工具拿「开机时刻 + 秒数」换算出来的近似日期：系统经历过休眠/挂起时，挂起期间环缓冲计时仍在走而墙上时间也走，`-T` 的换算会整体漂移，极端情况可差几个小时。

因此「按日期精确对齐内外部事件」时不要信 `dmesg -T` 的绝对时刻，用 `journalctl -k --since` 或 `/var/log/kern.log` 的时间戳（由 journald/rsyslog 按收到时刻打）更可靠。

`/var/log/dmesg` 是开机阶段内核缓冲的落盘副本，挂了内核或启动阶段排障时可以回看，日常排障仍以 `dmesg`/`journalctl -k` 为主。

## 6. 日志轮转 logrotate

### 6.1 轮转后的文件命名规律

rsyslog 管理的文本日志默认按天（syslog）或按周（其余）轮转，命名规律：

```text
syslog            ← 正在写入的当前文件
syslog.1          ← 上一周期（delaycompress 使最近一次不压缩）
syslog.2.gz       ← 更早的周期，gzip 压缩
syslog.3.gz …     ← 依保留份数依次类推，超出份数的被删除
```

auth.log、kern.log、dpkg.log、apt/history.log 等同理。目录里 `名称.N` 与 `名称.N.gz` 混排属于正常：`.1` 未压缩是延后压缩策略的结果，不是轮转出错。

### 6.2 rsyslog 的轮转配置

配置在 `/etc/logrotate.d/rsyslog`，Ubuntu 默认把它写成两段：`syslog` 单独一段按天轮转，其余主题日志合为一段按周轮转（20.04/22.04 默认近似如下，各版本条目可能略有增减，以 `cat` 本机文件为准）：

```conf
/var/log/syslog
{
        rotate 4
        daily
        missingok
        notifempty
        compress
        delaycompress
        postrotate
                /usr/lib/rsyslog/rsyslog-rotate || true
        endscript
}

/var/log/mail.info
/var/log/mail.warn
/var/log/mail.err
/var/log/mail.log
/var/log/daemon.log
/var/log/kern.log
/var/log/auth.log
/var/log/user.log
/var/log/cron.log
/var/log/debug
/var/log/messages
{
        rotate 4
        weekly
        missingok
        notifempty
        compress
        delaycompress
        sharedscripts
        postrotate
                /usr/lib/rsyslog/rsyslog-rotate || true
        endscript
}
```

逐条含义：

| 配置项 | 作用 |
|---|---|
| `rotate 4` | 最多保留 4 份历史，超出的删除 |
| `daily` | 每天轮转一次（syslog 用的就是它） |
| `weekly` | 每周轮转一次（其余主题日志用它） |
| `missingok` | 文件不存在时不报错 |
| `notifempty` | 空文件不轮转 |
| `compress` | 旧日志 gzip 压缩 |
| `delaycompress` | 最近一次轮转的文件推迟到下一轮再压缩（即 `.1` 不压） |
| `sharedscripts` | 一组文件只执行一次 postrotate |
| `postrotate …` | 轮转后让 rsyslog 重开日志句柄，避免继续写旧 inode |

注意一个容易踩的坑：`syslog` 每天轮转且只留 4 份，也就是说 `/var/log` 里的 syslog 文本实际只覆盖最近 4 天左右；更早的历史要么靠 journald（默认保留量大得多），要么靠集中式日志平台。排查跨度超过几天的问题时，别先假设 syslog 归档还在。

### 6.3 全局默认配置 /etc/logrotate.conf

```bash
cat /etc/logrotate.conf
```

关键默认项：`weekly`（默认每周）、`rotate 4`（默认留 4 份）、`create`（轮转后新建空文件）、`include /etc/logrotate.d`（加载各软件配置），末尾还有 `wtmp`、`btmp` 的按月轮转节。一句话原则：**全局文件管默认值，`/etc/logrotate.d/` 下各文件管具体日志**，调整保留策略改后者，不要动前者。

### 6.4 确认轮转与保留是否生效

```bash
cat /etc/logrotate.d/rsyslog                 # 看策略
ls -lh /var/log/syslog*                      # 看实际产出与保留份数
zcat /var/log/syslog.2.gz | head -5          # 抽查归档内容
sudo logrotate -d /etc/logrotate.conf        # 干跑演练，只打印不执行
```

`logrotate -d` 是安全的演练模式，输出「would rotate / would compress」等计划动作，不会真的动文件，上线新策略前先跑一遍。反过来 `logrotate -f` 会强制执行轮转，会立即改名压缩当前日志，生产主机上慎用；手工触发后若正在用 `tail -f` 观察，记得切到 `tail -F`。

## 7. 典型排障场景速查

### 7.1 SSH 登录失败 / 暴力破解排查

```bash
# 文本日志：失败登录明细与来源 IP 统计
sudo grep "Failed password" /var/log/auth.log | tail -20
sudo grep "Failed password" /var/log/auth.log | awk '{print $(NF-3)}' | sort | uniq -c | sort -nr | head
sudo zgrep -h "Failed password" /var/log/auth.log.*.gz | awk '{print $(NF-3)}' | sort | uniq -c | sort -nr | head

# journal 视角：今天 ssh 服务的全部记录与错误
journalctl -u ssh --since today --no-pager
journalctl -u ssh --since today -p err --no-pager

# 登录会计记录
sudo lastb | head -20        # 失败登录（读 btmp）
last | head -20              # 成功登录与会话（读 wtmp）
last -i | head -20           # 以 IP 形式显示来源
```

解读要点：

- 单行形如 `Failed password for invalid user admin from 203.0.113.5 port 51234 ssh2`。`invalid user` 表示对方在穷举用户名；合法用户名被打更值得警惕。`$(NF-3)` 正好取到来源 IP 字段。
- 同一 IP 高频失败且端口跳变，是典型的暴力破解；对照 `lastb` 与 `last` 确认**是否有失败之后紧接着成功**的记录——有的话按成功入侵处理：重置凭据、查 `~/.ssh/authorized_keys`、审计 history。
- 如果装了 fail2ban，再查 `sudo grep Ban /var/log/fail2ban.log` 看封禁动作，确认现有拦截是否生效；未装则可考虑启用，参考本仓库 `安全/` 目录的 UFW/iptables 文档配套加固。
- 这类日志包含外部 IP 与用户名，写入报告属正常；对外分享样例时做最小化脱敏即可。

### 7.2 systemd 服务启动失败

以 `myapp` 服务为例：

```bash
systemctl status myapp --no-pager -l                    # 先看状态与最近几行
journalctl -u myapp -b -p err --no-pager                # 本次开机以来的错误
journalctl -u myapp -b --no-pager | tail -80            # 再放开优先级看完整上下文
journalctl -u myapp --since "10 min ago" -f             # 边改配置边实时观察
```

解读要点：

- 重点看 `Failed at` 前一行：`code=exited, status=1/FAILURE` 是进程自己报错退出；`status=203/EXEC` 多半是 `ExecStart` 路径或权限问题；`status=217/USER` 是服务里 `User=` 指定的账号不存在。
- `-p err` 只看错误快，但缺少因果链：真正的原因常在错误行之前几行的 info 里（依赖没起、端口被占、配置加载失败），所以一定要有第二步放开优先级的完整回看。
- `systemctl status` 显示的是「最近一次」结果；服务被反复拉起时，用 `journalctl -u myapp -b` 看每次重启循环的间隔，必要时 `systemctl show myapp -p NRestarts,Restart` 确认重启策略。

### 7.3 OOM Kill 排查

```bash
sudo dmesg -T | grep -i "killed process"
journalctl -k | grep -i oom
journalctl -k --since today | grep -iE "out of memory|oom"
sudo grep -i oom /var/log/kern.log
```

解读要点：

- 典型行：`Out of memory: Killed process 1234 (java) total-vm:... anon-rss:...`。记录 PID、进程名和 anon-rss，对照业务判断被杀的是不是关键服务。
- 行首的触发上下文（`oom-kill:constraint=CONSTRAINT_NONE` 还是 `CONSTRAINT_MEMCG`）区分是**整机内存耗尽**还是**cgroup/容器限额**触发。MEMCG 情况下整机可能内存充足，应去查容器 limit 而不是加内存。
- 被杀的直接证据只在内核日志里；应用侧往往只看到「连接中断/进程消失」。找到 OOM 后再回该时间点 `journalctl -u <服务>` 看被杀前应用的行为，结合本仓库 `top` 排障文档第 6.3 节的内存排查流程定位增长源头。

### 7.4 磁盘被日志打满

```bash
df -h /var/log /                                    # 先确认满的是哪个挂载点
journalctl --disk-usage                             # journal 占了多少
du -h /var/log 2>/dev/null | sort -h | tail -20     # /var/log 下谁最大
ls -lhS /var/log | head                             # 最大的单文件
sudo journalctl --vacuum-time=7d                    # 收缩 journal
sudo journalctl --vacuum-size=500M
```

解读要点：

- `/var/log` 通常和根分区在同一盘上，日志打满会导致新日志写不进、甚至影响依赖 `/var` 的服务。先 `df -h` 确认挂载点，再决定清理对象。
- 定位到超大且还在增长的文本日志后，**不要直接 `rm`**：进程仍持有旧句柄，空间不会释放，还丢了现场。正确做法是截断（`sudo truncate -s 0 /var/log/某文件`，先确认内容可弃）或触发轮转，然后排查是什么在狂写（多半是某个服务在报错刷屏）。
- journal 只接受 vacuum 或上限配置，不接受手工删文件。清理完成后再 `journalctl --disk-usage` 和 `df -h` 复核结果。

### 7.5 apt 安装 / 卸载历史追溯

```bash
# APT 事务视角：谁在什么时候跑了什么命令
grep "Commandline\|Requested-By" /var/log/apt/history.log | tail -20
less /var/log/apt/history.log           # 完整事务段：Start-Date / Commandline / Install / Remove / End-Date

# dpkg 明细视角：逐个包的变更
grep " install " /var/log/dpkg.log | tail
grep " remove \| purge " /var/log/dpkg.log
zgrep " install " /var/log/dpkg.log.*.gz | tail -20    # 查更久远的归档
```

解读要点：

- `history.log` 每个事务是一段：`Start-Date` → `Commandline: apt install nginx` → `Requested-By: username` → 变更包列表 → `End-Date`。判定「是不是有人手滑 / 是不是自动更新干的」首选它，`Commandline` 显示 `apt`/`apt-get` 还是未知，能区分人工与脚本触发。
- `dpkg.log` 记录到具体包版本（如 `install nginx:amd64 <none> 1.24.0-…`），适合做「某包何时变更到当前版本」的精确对账；行格式中动作词两侧带空格，用 `grep " install "` 精确匹配。
- `unattended-upgrades` 会自动改包：发布时间线对不上人工操作时，先看 `/var/log/unattended-upgrades/` 再怀疑别人。

### 7.6 上次异常关机 / 重启原因

```bash
journalctl --list-boots                              # 有哪些开机记录
journalctl -b -1 -e --no-pager                       # 跳到上次开机日志的末尾
journalctl -b -1 -n 100 --no-pager                   # 上次开机最后 100 行
last -x shutdown reboot | head -10                   # 正常的关机/重启会计记录
```

解读要点：

- 对比两种结局：上次日志结尾是 `Reached target Power-Off`、`systemd-logind: System is powering down` 这类收尾行 → 正常关机；**结尾戛然而止、没有任何关机收尾** → 断电、内核 panic、watchdog 或宿主机强制下电，需继续查硬件/IPMI/云平台事件。
- `last -x` 里只有 `reboot` 没有对应 `shutdown`，同样指向非正常下电。
- 若在上次日志末尾看到 `kernel: panic`、`watchdog: BUG`、硬件 MCE 报错，按对应方向深入；什么都看不到但确认了异常下电，问题多半在系统日志之外的供电/虚拟化层。

## 8. 附录

### 8.1 journald 日志持久化

journald 的存储由 `/var/log/journal` 目录是否存在决定：存在则持久化保存（重启后仍在），不存在则只写到内存型的 `/run/log/journal`，重启即丢失。Ubuntu 默认创建该目录，因此 `-b -1` 通常直接可用。手工精简化过的系统如果没有：

```bash
ls -d /var/log/journal 2>/dev/null || {
  sudo mkdir -p /var/log/journal
  sudo systemd-tmpfiles --create --prefix /var/log/journal
  sudo systemctl restart systemd-journald
}
```

重启 journald 只会短暂影响日志收集（秒级），不影响业务服务；但从变更管理的角度，生产环境仍建议挑低峰期操作。

### 8.2 /etc/systemd/journald.conf 常用配置

改完任何一项都要 `sudo systemctl restart systemd-journald` 生效：

| 配置项 | 作用 | 常用值 |
|---|---|---|
| `Storage` | 存储方式 | `auto`（有 `/var/log/journal` 则持久化）、`persistent`、`volatile`、`none` |
| `SystemMaxUse` | journal 占用的磁盘上限 | 如 `500M`、`2G` |
| `SystemMaxFileSize` | 单个归档文件大小上限 | 如 `100M` |
| `SystemKeepFree` | 给磁盘预留的剩余空间 | 防止日志把盘写满 |
| `MaxRetentionSec` | 最长保留时长 | 如 `7day`、`1month` |
| `ForwardToSyslog` | 是否转发给 rsyslog | Ubuntu 默认经 socket 集成，一般保持默认即可 |
| `Compress` | 归档文件是否压缩 | 默认开 |

生产环境常见的调整就是把 `SystemMaxUse` 显式设小（防止极端情况下撑爆磁盘）、把 `MaxRetentionSec` 对齐合规要求。改完后再用 `journalctl --disk-usage` 复核实际占用。

### 8.3 单机之外的集中式日志

`journalctl` 和 `grep /var/log` 解决的是**单机视角**。当机器数量上来、或需要跨主机关联事件时，应把日志采集到集中式平台（如 Loki + Promtail + Grafana，或 VictoriaLogs）再做查询与告警。这部分本仓库在 `监控/` 目录另有专文——[日志平台方案设计：Loki-Promtail-Grafana与VictoriaLogs](../监控/日志平台方案设计：Loki-Promtail-Grafana与VictoriaLogs.md)，此处不展开。即便上了集中式平台，本章的单机技能仍是平台上「下钻到某台机器」时的基本功，两边不矛盾。

