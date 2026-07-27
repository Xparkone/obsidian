# Git 命令详解

> 一份面向日常开发的 Git 命令速查与详解，涵盖从基础到高级的常用场景。

---

## 目录

1. [基础工作流](#一基础工作流)
2. [分支管理](#二分支管理)
3. [撤销与回退](#三撤销与回退)
4. [暂存与贮藏](#四暂存与贮藏)
5. [日志与历史追溯](#五日志与历史追溯)
6. [远程仓库操作](#六远程仓库操作)
7. [标签管理](#七标签管理)
8. [高级操作](#八高级操作)
9. [配置与别名](#九配置与别名)
10. [常见场景实战](#十常见场景实战)

---

## 一、基础工作流

### `git init` — 初始化仓库

```bash
git init                  # 在当前目录创建 .git
git init my-project       # 创建目录并初始化
git init --bare           # 裸仓库（用于远程仓库）
```

### `git clone` — 克隆仓库

```bash
git clone https://github.com/user/repo.git            # 克隆全部历史
git clone https://github.com/user/repo.git my-dir     # 指定目录名
git clone --depth 1 https://github.com/user/repo.git  # 浅克隆（仅最新提交）
git clone -b develop https://github.com/user/repo.git # 克隆指定分支
```

| 选项 | 说明 |
|------|------|
| `--depth N` | 只克隆最近 N 次提交，节省空间和时间 |
| `--branch / -b` | 克隆后切换到指定分支 |
| `--single-branch` | 只克隆指定分支的历史 |
| `--recurse-submodules` | 同时克隆子模块 |

### `git status` — 查看工作区状态

```bash
git status                  # 详细状态
git status -s               # 简短格式
git status -sb              # 简短 + 当前分支信息
```

输出解读：
- `??` — 未跟踪的新文件
- `M` (红色) — 已修改未暂存
- `M` (绿色) — 已暂存待提交
- `A` — 新文件已暂存
- `D` — 已删除

### `git add` — 暂存更改

```bash
git add file.txt            # 暂存单个文件
git add src/                # 暂存整个目录
git add -A                  # 暂存所有更改（新增+修改+删除）
git add -u                  # 暂存已跟踪文件的修改和删除（不含新文件）
git add -p                  # 交互式选择暂存（逐块确认）
git add -i                  # 交互式菜单
```

### `git commit` — 提交更改

```bash
git commit -m "feat: add login feature"           # 提交并写消息
git commit -a -m "fix: typo"                      # 跳过 git add，直接提交已跟踪文件
git commit --amend -m "new message"               # 修改上一次提交的消息
git commit --amend --no-edit                       # 追加到上一次提交（不改消息）
git commit --amend --date="$(date)"                # 修改提交时间
```

**提交信息规范** (Conventional Commits):

```
<type>(<scope>): <description>

feat: 新功能
fix: 修复 bug
docs: 文档变更
refactor: 重构
perf: 性能优化
test: 测试
chore: 构建/工具
ci: CI/CD 变更
```

### `git diff` — 查看差异

```bash
git diff                    # 工作区 vs 暂存区（未暂存的更改）
git diff --staged           # 暂存区 vs 最新提交
git diff HEAD               # 工作区 vs 最新提交（所有未提交的更改）
git diff HEAD~1             # 工作区 vs 上一次提交
git diff main..feature      # 两个分支的差异
git diff --stat             # 只显示统计信息
git diff --name-only        # 只显示文件名
git diff --word-diff        # 逐词对比（而非逐行）
```

### `git rm` / `git mv` — 删除与移动

```bash
git rm file.txt             # 删除文件并暂存
git rm --cached file.txt    # 从 Git 跟踪中移除但保留本地文件
git mv old.txt new.txt      # 重命名并暂存（等价于 mv + git add）
```

---

## 二、分支管理

### `git branch` — 查看/创建/删除分支

```bash
git branch                  # 列出本地分支
git branch -r               # 列出远程分支
git branch -a               # 列出所有分支
git branch -v               # 列出分支 + 最新提交
git branch -vv              # 列出分支 + 远程跟踪关系
git branch feature/login    # 创建分支（不切换）
git branch -d old-branch    # 删除已合并的分支
git branch -D old-branch    # 强制删除（即使未合并）
git branch -m new-name      # 重命名当前分支
```

### `git switch` / `git checkout` — 切换分支

```bash
# 新版推荐 (Git 2.23+)
git switch main             # 切换到已有分支
git switch -c feature/new   # 创建并切换到新分支
git switch -                # 切换到上一个分支

# 旧版
git checkout main
git checkout -b feature/new
git checkout -              # 回到上一个分支
```

### `git merge` — 合并分支

```bash
git checkout main
git merge feature/login           # 将 feature/login 合并到当前分支

# 合并策略
git merge --no-ff feature/login    # 强制生成合并提交（保留分支历史）
git merge --ff-only feature/login  # 仅快进合并（不能快进就失败）
git merge --squash feature/login   # 压缩为一个提交（不自动 commit）
```

**三种合并方式对比**：

```
# 快进合并 (Fast-Forward)
main:  A---B
           \
feat:       C---D
# 合并后: A---B---C---D  (线性历史，无合并提交)

# 非快进合并 (--no-ff)
main:  A---B
           \
feat:       C---D
# 合并后: A---B-------M  (有合并提交，保留分支轨迹)
                \     /
                 C---D

# Squash 合并
main:  A---B
           \
feat:       C---D
# 合并后: A---B---S  (C+D 压缩成一个提交 S)
```

### `git rebase` — 变基

```bash
git checkout feature/login
git rebase main                     # 将 feature 分支的提交"搬到"main 最新提交之上
git rebase -i HEAD~3                # 交互式变基最近 3 次提交
git rebase --continue               # 解决冲突后继续
git rebase --abort                  # 放弃变基
git rebase --onto main feature/A feature/B  # 将 B 中独有提交移到 main 上
```

**rebase vs merge**：

| 维度 | merge | rebase |
|------|-------|--------|
| 历史 | 保留真实分支拓扑 | 线性历史，更干净 |
| 冲突解决 | 一次解决 | 可能需要多次解决 |
| 安全性 | 安全 | 不要 rebase 已推送的提交 |
| 适用场景 | 公共分支合并 | 整理本地提交 |

**交互式 rebase (`-i`) 操作**：

```
pick abc1234 feat: add login
pick def5678 fix: typo
pick ghi9012 wip: temp

# 可用命令:
# pick   = 保留该提交
# reword = 保留但修改提交信息
# edit   = 保留但暂停以便修改
# squash = 合并到上一个提交（保留信息）
# fixup  = 合并到上一个提交（丢弃信息）
# drop   = 删除该提交
```

### `git cherry-pick` — 挑选提交

```bash
git cherry-pick abc1234            # 将指定提交应用到当前分支
git cherry-pick abc1234 def5678    # 挑选多个提交
git cherry-pick abc1234..def5678   # 挑选一个范围（不含 abc1234）
git cherry-pick --no-commit abc1234  # 不自动提交，保留在暂存区
git cherry-pick --continue         # 解决冲突后继续
git cherry-pick --abort            # 放弃
```

---

## 三、撤销与回退

### `git reset` — 重置提交（改变历史）

```bash
# --soft: 只移动 HEAD，保留暂存区和工作区
git reset --soft HEAD~1            # 撤销上一次提交，更改回到暂存区

# --mixed (默认): 移动 HEAD + 清空暂存区，保留工作区
git reset HEAD~1                   # 撤销提交+暂存，更改保留在工作区
git reset HEAD file.txt            # 取消暂存单个文件

# --hard: 移动 HEAD + 清空暂存区 + 丢弃工作区更改 ⚠️ 危险
git reset --hard HEAD~1            # 彻底回到上一次提交
git reset --hard origin/main       # 强制同步到远程
```

**三种 reset 对比**：

| 模式 | HEAD | 暂存区 | 工作区 |
|------|------|--------|--------|
| `--soft` | 移动 | 保留 | 保留 |
| `--mixed` | 移动 | 清空 | 保留 |
| `--hard` | 移动 | 清空 | 清空 |

### `git revert` — 反向提交（不改变历史）

```bash
git revert abc1234                 # 创建一个新提交来撤销 abc1234 的更改
git revert abc1234..def5678        # 撤销一个范围
git revert -m 1 abc1234            # 撤销合并提交（1 表示保留主分支的父提交）
git revert --no-commit abc1234     # 不自动提交
```

### `git checkout -- <file>` — 恢复文件

```bash
git checkout -- file.txt           # 丢弃工作区更改，恢复到暂存区状态
git checkout HEAD -- file.txt      # 丢弃工作区更改，恢复到最新提交状态
git checkout abc1234 -- file.txt   # 恢复文件到指定提交的版本
```

### `git restore` — 新版恢复命令 (Git 2.23+)

```bash
git restore file.txt               # 丢弃工作区更改 (= checkout -- file)
git restore --staged file.txt      # 取消暂存 (= reset HEAD file)
git restore -SW file.txt           # 同时丢弃工作区和暂存区
git restore -s abc1234 file.txt    # 从指定提交恢复
```

---

## 四、暂存与贮藏

### `git stash` — 暂存当前工作

```bash
git stash                           # 暂存所有更改
git stash push -m "WIP: login"      # 暂存并命名
git stash push -u                   # 暂存所有文件（包括未跟踪的）
git stash push -p                   # 交互式选择暂存内容

git stash list                      # 查看暂存列表
git stash show                      # 查看最新暂存内容
git stash show -p                   # 查看详细 diff
git stash show stash@{1}            # 查看指定暂存

git stash pop                       # 恢复最新暂存并删除记录
git stash pop stash@{1}             # 恢复指定暂存
git stash apply                     # 恢复最新暂存但保留记录
git stash apply stash@{1}           # 恢复指定暂存

git stash drop                      # 删除最新暂存
git stash drop stash@{1}            # 删除指定暂存
git stash clear                     # 清空所有暂存

git stash branch feature/recover    # 从暂存创建新分支
```

**典型场景**：

```bash
# 场景1: 正在开发 feature，突然需要修 bug
git stash push -m "WIP: feature-x"
git checkout main
git checkout -b hotfix/bug
# ... 修复 bug 并提交 ...
git checkout feature
git stash pop

# 场景2: 拉取远程更新前暂存本地更改
git stash
git pull --rebase
git stash pop
```

---

## 五、日志与历史追溯

### `git log` — 查看提交历史

```bash
git log                                    # 基本日志
git log --oneline                          # 一行一个提交
git log --oneline --graph                  # 图形化分支历史
git log --oneline --graph --all            # 所有分支的图形历史
git log --oneline -10                      # 最近 10 条
git log --stat                             # 显示文件变更统计
git log -p                                 # 显示完整 diff
git log -p -2                              # 最近 2 条的完整 diff
git log -- file.txt                        # 只看某个文件的提交历史
git log --grep="fix"                       # 搜索提交信息
git log -S "function_name"                 # 搜索代码变更（查找某段代码何时被引入/删除）
git log --author="John"                    # 按作者过滤
git log --since="2024-01-01" --until="2024-12-31"  # 按时间过滤
git log main..feature                      # feature 有但 main 没有的提交
git log --merges                           # 只看合并提交
git log --no-merges                        # 排除合并提交
```

**自定义格式化**：

```bash
# 简洁格式
git log --pretty=format:"%h %s" --graph

# 自定义格式
git log --pretty=format:"%h %ad | %s [%an]" --date=short

# 常用占位符:
# %H 完整 hash     %h 短 hash
# %an 作者名       %ae 作者邮箱
# %ad 作者日期     %ar 相对日期
# %s 提交信息      %d 引用名 (分支/标签)
```

**推荐别名**：

```bash
git config --global alias.lg "log --oneline --graph --all -20"
git config --global alias.ls "log --oneline --graph -20"
```

### `git show` — 查看提交详情

```bash
git show abc1234              # 查看提交的完整信息（diff + 元数据）
git show abc1234 --stat       # 只显示统计
git show abc1234:file.txt     # 查看某提交中文件的内容
git show HEAD                 # 查看最新提交
git show --name-only abc1234  # 只显示变更的文件名
```

### `git blame` — 追溯代码作者

```bash
git blame file.txt            # 查看每行代码的作者和提交
git blame -L 10,20 file.txt   # 只看第 10-20 行
git blame -L '/func main/,/^}/' file.txt  # 函数范围
git blame -w file.txt         # 忽略空白变更
git blame -C file.txt         # 检测代码移动/复制
```

### `git reflog` — 引用日志（救命稻草）

```bash
git reflog                    # 查看 HEAD 的移动历史（包括被 reset 掉的提交）
git reflog show feature/login # 查看分支的引用历史
git reflog --date=iso         # 显示时间戳
```

**reflog 救回误删**：

```bash
# 不小心 git reset --hard 了
git reflog
# 找到 reset 之前的 HEAD@{n}
git reset --hard HEAD@{3}
```

### `git bisect` — 二分查找 bug

```bash
git bisect start              # 开始二分查找
git bisect bad HEAD           # 标记当前版本有问题
git bisect good v1.0          # 标记 v1.0 是好的
# Git 自动 checkout 到中间版本...
# 测试后标记：
git bisect good               # 或 git bisect bad
# 重复直到定位到引入 bug 的提交
git bisect reset              # 结束二分查找，回到原分支
```

---

## 六、远程仓库操作

### `git remote` — 管理远程仓库

```bash
git remote -v                        # 查看远程仓库地址
git remote add upstream https://...  # 添加远程仓库
git remote rename origin upstream    # 重命名
git remote remove upstream           # 删除
git remote set-url origin git@...    # 修改 URL
git remote show origin               # 查看远程仓库详情
git remote prune origin              # 清理本地已删除的远程分支引用
```

### `git fetch` — 拉取远程更新（不合并）

```bash
git fetch origin                    # 拉取所有远程分支更新
git fetch origin main               # 只拉取 main 分支
git fetch --all                     # 拉取所有远程仓库
git fetch -p                        # 拉取并清理已删除的远程分支
git fetch origin main:local-main    # 拉取到本地指定分支
```

### `git pull` — 拉取并合并 (= fetch + merge)

```bash
git pull origin main                # 拉取并合并
git pull --rebase origin main       # 拉取并变基（推荐，保持线性历史）
git pull --ff-only                  # 只做快进合并
```

**配置默认 pull 策略**：

```bash
git config --global pull.rebase true      # 默认使用 rebase
git config --global pull.ff only          # 默认只快进
```

### `git push` — 推送提交

```bash
git push origin main                # 推送到远程
git push origin feature/login       # 推送指定分支
git push -u origin feature/login    # 推送并设置上游跟踪
git push --force                    # 强制推送 ⚠️
git push --force-with-lease         # 安全强制推送（检查远程是否被他人修改）
git push --all origin               # 推送所有分支
git push origin --delete old-branch # 删除远程分支
```

**`--force` vs `--force-with-lease`**：

```bash
# --force: 无条件覆盖远程，如果别人在此期间推送了，会丢失
git push --force

# --force-with-lease: 先检查远程分支是否和你上次 fetch 的一样
# 如果有人在你之后推送了，命令会失败，保护他人的工作
git push --force-with-lease
```

---

## 七、标签管理

### `git tag` — 创建/查看标签

```bash
git tag                             # 列出所有标签
git tag -l "v2.*"                   # 模糊匹配标签
git tag v1.0.0                      # 创建轻量标签
git tag -a v1.0.0 -m "release v1"   # 创建附注标签（含元数据）
git tag -a v1.0.0 abc1234           # 为指定提交打标签
git tag -d v1.0.0                   # 删除本地标签
git push origin v1.0.0              # 推送单个标签
git push origin --tags              # 推送所有标签
git push origin --delete v1.0.0     # 删除远程标签
git show v1.0.0                     # 查看标签详情
git checkout v1.0.0                 # 切换到标签（游离 HEAD）
git checkout -b release/v1 v1.0.0   # 从标签创建分支
```

---

## 八、高级操作

### `git submodule` — 子模块

```bash
git submodule add https://github.com/lib/utils.git libs/utils
git submodule update --init --recursive      # 克隆后初始化子模块
git submodule update --remote                # 更新子模块到最新
git submodule foreach git pull origin main   # 批量操作所有子模块
git submodule deinit libs/utils              # 移除子模块
```

### `git worktree` — 工作树（同时检出多个分支）

```bash
git worktree add ../hotfix hotfix/bug-123    # 创建新工作树
git worktree list                            # 列出所有工作树
git worktree remove ../hotfix                # 删除工作树
git worktree prune                           # 清理失效的工作树引用
```

**适用场景**：在一个工作树中编译，在另一个中开发，避免 `git stash` 的来回切换。

### `git clean` — 清理未跟踪文件

```bash
git clean -n              # 预览要删除的文件（dry-run）
git clean -f              # 删除未跟踪文件
git clean -fd             # 删除未跟踪文件和目录
git clean -fdx            # 删除所有未跟踪文件（包括 .gitignore 中的）
```

### `git gc` — 垃圾回收

```bash
git gc                    # 压缩和清理仓库
git gc --aggressive       # 更激进的优化
git gc --auto             # 自动判断是否需要
```

### `git archive` — 打包导出

```bash
git archive --format=tar.gz --output=release.tar.gz HEAD
git archive --format=zip --output=v1.0.zip v1.0.0
```

---

## 九、配置与别名

### `git config` — 全局配置

```bash
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
git config --global core.editor "vim"
git config --global diff.tool "vimdiff"
git config --global merge.tool "vimdiff"
git config --global init.defaultBranch main
git config --global core.autocrlf input    # macOS/Linux
git config --global core.autocrlf true     # Windows
git config --global http.proxy http://proxy:8080
git config --global --unset http.proxy     # 取消代理
git config --list                          # 查看所有配置
git config --global --list                 # 查看全局配置
```

### 推荐别名

```bash
git config --global alias.co checkout
git config --global alias.br branch
git config --global alias.ci commit
git config --global alias.st status
git config --global alias.unstage "reset HEAD --"
git config --global alias.last "log -1 HEAD"
git config --global alias.lg "log --oneline --graph --all -20"
git config --global alias.ls "log --oneline --graph -20"
git config --global alias.undo "reset --soft HEAD~1"
git config --global alias.amend "commit --amend --no-edit"
git config --global alias.discard "checkout --"
git config --global alias.cleanup "!git branch --merged | grep -v '\\*\\|main\\|master' | xargs -n 1 git branch -d"
```

---

## 十、常见场景实战

### 场景 1：提交了不该提交的文件

```bash
# 情况 A: 刚提交，还没推送
git reset --soft HEAD~1          # 撤销提交，保留更改
git reset HEAD unwanted-file.txt # 取消暂存
git commit -c ORIG_HEAD          # 重新提交

# 情况 B: 已经推送了
git revert HEAD                  # 创建一个反向提交
git push origin main

# 情况 C: 敏感信息（密码/密钥）泄露
# 1. 立即修改泄露的密码
# 2. 使用 git filter-branch 或 BFG Repo-Cleaner 清理历史
git filter-branch --force --index-filter \
  "git rm --cached --ignore-unmatch secret.txt" \
  --prune-empty --tag-name-filter cat -- --all
git push --force --all
```

### 场景 2：合并冲突解决

```bash
# 冲突发生
git merge feature/login
# CONFLICT in file.txt

# 1. 查看冲突文件
git status

# 2. 手动编辑文件，解决冲突标记
# <<<<<<< HEAD
# 你的更改
# =======
# 对方的更改
# >>>>>>> feature/login

# 3. 标记为已解决
git add file.txt

# 4. 完成合并
git commit -m "merge: resolve conflicts"

# 或者放弃合并
git merge --abort
```

**冲突解决工具**：

```bash
git mergetool                      # 启动可视化合并工具
git checkout --ours file.txt       # 使用当前分支的版本
git checkout --theirs file.txt     # 使用合并分支的版本
```

### 场景 3：把一个分支的某个提交应用到另一个分支

```bash
git checkout main
git cherry-pick abc1234            # 直接应用

# 如果冲突
git cherry-pick abc1234
# ... 解决冲突 ...
git add .
git cherry-pick --continue
```

### 场景 4：拆分一个大提交

```bash
git rebase -i HEAD~3               # 标记要拆分的提交为 'edit'
# Git 停在那个提交
git reset HEAD~1                   # 回退该提交，保留更改
git add file1.py && git commit -m "part 1"
git add file2.py && git commit -m "part 2"
git rebase --continue
```

### 场景 5：修改很久以前的提交信息

```bash
git rebase -i HEAD~5
# 将目标提交前的 'pick' 改为 'reword'
# 保存后 Git 会打开编辑器让你修改信息
```

### 场景 6：找回误删的分支

```bash
git reflog
# 找到分支删除前的提交 hash
git checkout -b recovered-branch abc1234
```

### 场景 7：对比两个分支的差异文件

```bash
git diff --name-only main..feature           # 列出差异文件
git diff --stat main..feature                # 统计差异
git diff main..feature -- path/to/dir/       # 只对比某个目录
```

### 场景 8：临时保存工作，切换分支

```bash
git stash push -m "WIP: feature-x"
git checkout main
# ... 做其他事 ...
git checkout feature
git stash pop
```

### 场景 9：同步 fork 仓库

```bash
git remote add upstream https://github.com/original/repo.git
git fetch upstream
git checkout main
git merge upstream/main
git push origin main
```

### 场景 10：Git 仓库瘦身

```bash
# 1. 查找大文件
git rev-list --objects --all | \
  git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' | \
  awk '/^blob/ {print $4, $3}' | sort -rn -k2 | head -20

# 2. 清理（推荐用 BFG Repo-Cleaner）
# 3. 垃圾回收
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

---

## 附录：速查表

| 操作 | 命令 |
|------|------|
| 创建分支 | `git switch -c feature/xxx` |
| 切换分支 | `git switch main` |
| 删除分支 | `git branch -d feature/xxx` |
| 暂存所有 | `git add -A` |
| 提交 | `git commit -m "msg"` |
| 修改上次提交 | `git commit --amend` |
| 撤销暂存 | `git restore --staged file` |
| 丢弃更改 | `git restore file` |
| 撤销提交 (保留更改) | `git reset --soft HEAD~1` |
| 撤销提交 (丢弃更改) | `git reset --hard HEAD~1` |
| 反向提交 | `git revert HEAD` |
| 暂存工作 | `git stash push -m "wip"` |
| 恢复暂存 | `git stash pop` |
| 查看历史 | `git log --oneline --graph` |
| 查看引用日志 | `git reflog` |
| 拉取不合并 | `git fetch origin` |
| 拉取并变基 | `git pull --rebase` |
| 推送 | `git push origin main` |
| 安全强推 | `git push --force-with-lease` |
| 挑选提交 | `git cherry-pick abc1234` |
| 交互式变基 | `git rebase -i HEAD~3` |
| 清理未跟踪文件 | `git clean -fd` |