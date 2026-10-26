# 形象层集成方案：给陪伴机器人一个"身体"

> 调研日期：2026-10-26
> 参考项目：[QCYTSN/dsh-dafeiyu](https://github.com/QCYTSN/dsh-dafeiyu)（大肥鱼）→ 上游 [PC2005-cloud/dsh-pet](https://github.com/PC2005-cloud/dsh-pet)
> **决策（2026-10-26）：路径 A 先行，路径 B 后续。授权前提：目前纯自用。**
> 适配层实现：[src/companion/avatar.py](../src/companion/avatar.py)

---

## 1. 先厘清：参考项目不是"人物模型"

| | 大肥鱼 / dsh-pet | 本项目 |
|---|---|---|
| 本质 | **动画播放器**（透明窗 + 帧序列） | LLM 陪伴机器人 |
| 有 LLM 吗 | ❌ 零 LLM | ✅ Qwen3.5 + 人格系统 |
| "性格"来源 | 宿主推事件 → 切动画档位 | system prompt + 情绪状态机 |
| 素材 | AI 生成绿幕视频 → 抠像 → VP9-alpha webm | — |

**结论**：我们缺的不是"模型"，是**具身层**。大肥鱼提供的是"形象怎么呈现、怎么跟随状态动起来"这一层，正好补我们项目的空缺。

它还顺带解决了一个我们一直纠结的问题：**人格的视觉表达**。见 §6。

---

## 2. 决策

| 项 | 决定 |
|---|---|
| 路径 | **A 先行**（复用 dsh-pet 验证），**B 后续**（做原创形象） |
| 授权 | **目前纯自用** → 大肥鱼素材可自用（非商用），但二创须在公开渠道署名原作者 GitHub |
| 触发条件 | 若将来要商用 → 必须切到路径 B（大肥鱼素材 + 形象均不允许商用） |

### 路径 A：直接复用 dsh-pet

| | |
|---|---|
| 做法 | 目标机 `npm i -g dsh-pet` → `dsh-pet-standalone`；AstrBot 侧用 `avatar.py` 走 HTTP 驱动 |
| 优点 | **零动画代码、零窗口代码**；动画链 / 物理 / 多开 / 抛掷 / 右键菜单全部现成；代码 MIT |
| 缺点 | 引入 Node + Electron 运行时（~100 MB 首次解压，Windows 冷启动被杀毒扫描可能明显变慢）；大肥鱼形象 CC BY-NC-SA 4.0 非商用 + 署名；standalone 下余额/碎碎念/对话/系统通知不可用 |
| 成本 | 适配层已写好（`src/companion/avatar.py`），剩下是装 dsh-pet + 校准动画名 |

### 路径 B：做我们自己的原创形象（后续）

| | |
|---|---|
| 做法 | 用 `prompts/桌面宠物 10 秒动作提示词.md` 的配方 → 生成我们角色的绿幕视频 → 按 MAKE-YOUR-OWN-PET 抠像成 VP9-alpha webm → 放进 `main-animation/webm/`（**优先级高于包内素材**）或做成 pet pack |
| 优点 | **避开非商用限制**与二创署名义务；形象按世界观定制；档位表由我们定义 |
| 缺点 | 视频生成 + 抠像有人工环节；成片周期以周计 |

> **路径 B 的额外动因见 §4** —— 路径 A 能覆盖的档位有限，情绪向的动画基本得自己做。

---

## 3. 接口契约

### 3.1 基址与端点

`dsh-pet-standalone` 默认监听 `http://127.0.0.1:3080`，路由前缀 `/dsh-pet-7340`。

| 用途 | 方法与路径 | 说明 |
|------|-----------|------|
| **占用锁** | `POST /lock?pet=` | 不传 `lock` = 新建，传了 = 续期；回 `{lockId, expiresAt}` |
| 释放锁 | `POST /lock/release?pet=&lock=` | `lockId` = 持锁者收工；`force` 是渲染端上报用的，第三方不调 |
| **投喂气泡** | `POST /broadcast?pet=&lock=` | **不生成、只搬运**外部给定文本；可带 `image` / `duration` / 动画联动 |
| **点播动画** | `POST /anim?pet=&lock=` | 播池内动画名或自带 url；`facing` 可指定朝向（left/right）；回 `playbackId` |
| 播放回执 | `GET /playback/{id}` | 带 `?wait=&timeout=` 可挂起等待 |
| 清空气泡 | `POST /bubble/clear?pet=&lock=` | 提前收起（不等它自己 10 秒消失） |
| **写工作状态** | `POST /work-status` | `{state, task?}`，**固定外部槽，最后写入者生效**；不需要锁 |
| 注册右键菜单 | `POST /menu/item` | `{owner, labels, target?}`；同 owner 整体覆盖；显示在右键菜单「更多」下 |
| 读菜单点击 | `GET /menu/events?owner=&wait=` | 长轮询，**读取即清空** |
| 读全部状态 | `GET /state?since=&timeout=` | 长轮询；`counter` 变化即表示该叶子更新了 |
| 位置 / 抛掷 | `POST /position` / `POST /throw` | 需锁 |
| 素材 | `GET /thumb/{petId}/{file}` | 动画素材 URL 格式 |

**独立模式**（不打开 DSH）额外多三个端点，挂在服务根上（**不在** `/dsh-pet-7340` 前缀下）：

| 端点 | 说明 |
|------|------|
| `GET /`、`GET /health` | 服务与插件信息、监听端口、已运行秒数 |
| `POST /shutdown` | 优雅停机（释放 effect、停桌面助手、清周期定时器），退出码 0 |

独立模式下三个依赖 DSH 的接口**明确降级**（结构化失败，不假装成功）：
`POST /whisper`、`POST /chat` 回 `reason: 'provider-missing'`；`POST /balance` 回 `reason: 'unsupported'`。

> **我们的场景恰好只需要前者** —— 回复由我们的 LLM 生成，我们只搬运和播放。

### 3.2 锁的规则（第三方驱动的硬约束）

- 标了 **（需锁）** 的接口（`/broadcast`、`/anim`、`/bubble/clear`、`/position`、`/throw`）必须带 `?lock=<lockId>`
- 不带锁 → `lock-required`；锁号不对 → `lock-lost`（`cause` 说明是过期 / 已释放 / 被用户抢走）
- **锁占用期间桌宠完全静止** —— 它自己不动、也不弹气泡，余额/碎碎念/工作状态全部让路
  → **演出结束必须立刻释放**，否则桌宠被锁住、连待机动画都不动
- **用户优先**：用户一拖宠物、或把它隐藏/关闭，锁会立刻被撤销（此时收到 `lock-lost` 属正常）

> 我们的实现（`avatar.py`）按「取锁 → 演一次 → 放锁」的模式做，每次动作一个锁周期。

### 3.3 `/state` 的结构

```json
{
  "counter": 1755000000007,
  "sections": { "balance": {...}, "workStatus": {...}, "notify": {...}, "config": {...} },
  "pets": {
    "main": { "say": {...}, "anim": {...}, "position": {...}, "throw": {...}, "lock": {...} }
  }
}
```

每个叶子是 `{counter, data}`；`counter` 变了就表示它更新了（唯一判据）。
长轮询 `?since=<顶层 counter>&timeout=<ms>`（成对必填，上限 10 s）。

---

## 4. ⚠️ 关键约束：动画名必须真实存在

`events.<name>` 数组的元素是**动画池里的动画名**，不是随便写的字符串 —— 桌宠找不到同名动画就是 404。

dsh-pet 自带的动画池是**给鲸鱼角色做的日常行为**（16 组动作 / 3,444 帧），已知的名字大致是：

| 分类 | 已知动画名 |
|------|-----------|
| 待机 / 转向 | 待机、转身 |
| 移动 | 行走、屏幕漫游 |
| 小动作 | 打瞌睡、玩魔方、吃火锅、时节类 |
| 玩耍 / 文字 / 点击 | 打滚、气泡文字、点击回应 |
| 拖拽 | 悬空、落地回弹 |
| 事件 | 余额六档、碎碎念说话、**工作状态六档**（思考/工作/整理/等待/成功/出错） |

**结论（这决定了 A/B 的分工）**：

| 我们的状态 | 路径 A 能覆盖吗 |
|---|---|
| 待机、打瞌睡、玩耍、点击回应、拖拽 | ✅ 自带直接用 |
| **思考 / 工作 / 等待 / 成功 / 出错** | ✅ 用 `/work-status` 的内置六档 |
| **倾听 / 关心 / 俏皮 / 认真 / 说话 / 主动搭话** | ❌ **自带池里没有** → 要自己出 webm = 路径 B |

也就是说：**路径 A 能立刻拿到"有身体、能待机、会打哈欠、状态有反馈"，但拿不到情绪的视觉表达** —— 而情绪表达恰恰是陪伴场景最值钱的部分。

> 折中做法（路径 A 阶段）：情绪档位**先复用** `events.companion` 里的占位（全部指向"待机"），
> 等路径 B 的原创素材到位再逐个替换。`avatar.py` 的 `tier_animations` 配置项就是干这个的。

---

## 5. 我们的状态 → 桌宠信号

### 5.1 对接点

| 我们的来源 | 状态 | 桌宠信号 |
|---|---|---|
| `emotion.py` | `neutral` / `listening` / `caring` / `playful` / `serious` / `tired` | 档位动画（`/anim`） |
| `streaming.py` | 等 LLM 首字 | `/work-status` state=`思考` |
| `streaming.py` | TTS 播放中 | 档位 `说话`（路径 B 后才有料） |
| `handler.py` | 回复生成完 | `/broadcast` 投喂文本 + 说话动画 |
| `proactive.py` | 主动关怀触发 | `/broadcast` + `主动搭话` 档位 |
| `handler.py` | 异常 | `/work-status` state=`出错` |
| `persona.py` | 人格切换 | 切换显示哪只宠物（见 §6） |

### 5.2 档位表

档位索引在 `events.companion` 数组里，**索引即档位，只可追加末尾，不可中间插入**（dsh-pet 的硬规矩，我们自己也守）：

| 索引 | 档位 | 来源 | 路径 A 是否有素材 |
|---|---|---|---|
| 0 | 待机 | `emotion.neutral` | ✅ |
| 1 | 倾听 | `emotion.listening` | ❌ 路径 B |
| 2 | 关心 | `emotion.caring` | ❌ 路径 B |
| 3 | 俏皮 | `emotion.playful` | ❌ 路径 B |
| 4 | 认真 | `emotion.serious` | ❌ 路径 B |
| 5 | 犯困 | `emotion.tired` | ✅ 打瞌睡 |
| 6 | 思考 | `streaming` 等首字 | ✅ `/work-status` 思考 |
| 7 | 说话 | TTS 播放中 | ❌ 路径 B |
| 8 | 主动搭话 | `proactive` | ❌ 路径 B |
| 9 | 出错 | 异常 | ✅ `/work-status` 出错 |

### 5.3 适配层用法

`src/companion/avatar.py` —— 只依赖标准库，所有失败吞掉并记录，**绝不影响对话主链路**；连续失败 5 次自动关闭，避免对着没人监听的端口刷日志。

```python
from .avatar import AvatarClient, TIER_CARING, TIER_THINKING

avatar = AvatarClient(config.get("avatar", {}))

await avatar.set_work_status("思考")              # 不需要锁
await avatar.say("今天过得怎么样？", tier=TIER_CARING)  # 投喂 + 说话动画（需锁）
await avatar.set_emotion("tired")                 # 情绪 → 档位 → 动画
```

配置项（`astrbot.yaml` 的 `avatar:` 段）：

```yaml
avatar:
  enabled: true
  base_url: "http://127.0.0.1:3080/dsh-pet-7340"
  pet_id: "main"
  timeout: 3.0
  max_consecutive_failures: 5
  menu_owner: "companion-bot"
  # 档位 → 桌宠动画名（按它实际带的动画池校准）
  tier_animations:
    0: "待机"
    5: "打瞌睡"
```

### 5.4 还可以做的两件事

- **点击桌宠主动跟它说话** —— `POST /menu/item` 注册一个菜单项（如"跟小忆说话"），
  再用 `GET /menu/events` 长轮询读点击；点击后走**我们的** LLM 生成回复，再 `/broadcast` 回去。
  （桌宠自己的 `/chat` 在独立模式下不可用，而且它调的是它自己的模型。）
- **订阅状态** —— `GET /state?since=&timeout=` 长轮询，我们能读到桌宠当前说的话、动画、锁状态。

---

## 6. 人格 ↔ 宠物的对应关系

`pet pack` 机制天然支持"多人格"：

```
$DSH_HOME/dsh-pet/
├─ main-config.jsonc           ← 主宠物
├─ main-animation/webm/*.webm
└─ pet/
   ├─ xiaoyi-config.json       ← 性格 A 的独立动画池
   ├─ xiaoyi-animation/*.webm
   ├─ chenmo-config.json       ← 性格 B 的独立动画池
   └─ chenmo-animation/*.webm
```

**每个人格 = 一只独立宠物（独立动画池 + 独立素材）**，切换人格 = 切换显示哪一只实例。

这与 [[persona-system.md]] §9.1 的"层级 ② 烘焙进权重"**互为镜像**：
LLM 层是"人格烘焙进权重"，形象层是"人格烘焙进动画池"。两条路可以同时走。

> 注意 pet pack 的隔离规则：素材只查自己的（`pet/xiaoyi-animation/`），**绝不回落到 main-animation**；
> `animations` / `animationWeights` 必须写全，缺失即配置错误。

---

## 7. 素材生成管线（路径 B 用）

上游是完整三件套：**① 提示词配方 → ② 素材生成链 → ③ 插件**。

```
① prompts/
   ├── 桌面宠物 10 秒动作提示词.md      ← AI 生成绿幕动画的提示词配方
   └── 系统通知图标 AI 生成提示词.md
② MAKE-YOUR-OWN-PET.md
   ① 提示词 → 源视频（绿幕规范 + 按秒分解）
   ② 源视频 → 透明动画
      路线 A（默认）：自动绿幕抠像（HSV 色相，无需人工）
      路线 B（可选）：PR 手工抠像覆盖（ProRes 4444 with Alpha）
      ②.5 Safari/HEVC 兼容素材（macOS 专用 .mov）
   ③ 动画 → 插件
```

**落素材的两个口子**：

- 往 `main-animation/webm/` 放自制的 VP9-alpha `.webm` → **优先级高于包内素材**
- `pet pack` 机制 → 一个**全新种类**的宠物（独立动画池 + 独立素材）

**技术规格**：VP9-alpha webm（透明）、24 fps、画布 412×344、共 16 组动作 / 3,444 帧。

---

## 8. 授权红线

| 对象 | 授权 |
|------|------|
| dsh-pet **代码** | MIT ✅ |
| dsh-pet **素材**（动画 / 提示词 / 源视频） | 允许开源使用，**禁止商用** |
| **大肥鱼形象**（鲸鱼娘） | **CC BY-NC-SA 4.0**（署名 · 非商业 · 相同方式共享）。原型「溟月」出自 B 站 @上善无形，DeepSeek 版设计出自 B 站 @ZipZipPipe |
| 二创 / 改版 / 换皮 | 公开渠道须附原作者 GitHub：`https://github.com/PC2005-cloud/dsh-pet` |
| dsh-dafeiyu 当前 `assets/pet/` | 来自 dsh-pet，MIT（见其 `ASSET_LICENSE.md`） |
| dsh-dafeiyu `legacy/dafeiyu/` | **受限** —— 来自 `QCYTSN/ds-local-pet`，MIT 代码许可**不覆盖**这些视觉文件；已被排除出 npm 包 |

> ⚠️ **本项目目前纯自用** → 上面的非商用条款不构成障碍，但**署名义务仍然要履行**。
> ⚠️ **一旦有商用打算 → 必须切路径 B 做原创形象**，大肥鱼的素材和形象许可都不允许商用。
>
> ⚠️ 另注意：dsh-pet 的 HTTP 接口**无鉴权、只监听 127.0.0.1**。任何能访问该端口的本机进程都能调用（含恶意网页的 CSRF）。我们自己的封装**必须**校验来源、且**不得转发到公网**。

---

## 9. 平台注意事项

| 项 | 说明 |
|---|---|
| 浏览器 | Chromium（Chrome/Edge）✅ Firefox ✅ **Safari ❌**（macOS 不认 webm alpha → 黑底，需 `.mov` 素材） |
| Windows | 随包提供 Helper，无需自建 Python 环境；首次启动解压 ~100 MB Qt 运行库到临时目录，**杀毒实时扫描会让冷启动明显变慢**（等待上限已放宽到 180 秒） |
| 临时目录 | Windows `%LOCALAPPDATA%\dsh-dafeiyu\tmp`；超一天的 `_MEI*` 陈旧目录下次启动自动清理 |
| 日志 | Windows `%LOCALAPPDATA%\dsh-dafeiyu\logs\helper.log`；`DSH_DAFEIYU_LOG_FILE=<路径>` 可改，`off` 关闭 |
| 无图形环境 | Linux 无 `DISPLAY`/`WAYLAND_DISPLAY` 时自动跳过桌面窗，浏览器形态不受影响 |
| 多显示器 | 跨屏漫游/抛掷按各屏工作区为界，异构缩放已处理 |
| 与我们的显存账本 | 桌宠是 **CPU / GPU 都几乎不占**（Electron 渲染 + 视频解码），但**首次启动要占磁盘 ~100 MB 临时空间**，且会拉一个常驻 Electron 进程（RAM 几百 MB）。与 [[hardware-budget.md]] 的显存账本不冲突 |

---

## 10. 执行手册（给部署机 agent）

> **这份手册是自包含的** —— 拿到它的 agent 不需要向任何人提问，按步骤做即可。
> 每一步都带**判定标准**和**失败怎么办**。遇到 §12 表里的确认项时，
> 表里已经给了默认答案 —— **默认答案就是决定**，只有在默认答案被证伪时才需要回头找人。

### 10.0 自主执行规则

1. **按顺序做**，不要跳步。每步做完先跑它的验收命令，通过再进下一步。
2. **不要碰红线**（§8）：不改 `OLLAMA_HOST`、不转发 127.0.0.1 的端口、不引入云端 API、
   不把声纹原始音频落盘。
3. **形象层失败必须无感**。桌宠挂了、端口不对、动画名找不到 —— 都不能影响对话。
   适配层已经这么设计（吞异常 + 连续失败自我关闭），**不要在它外面加会抛异常的逻辑**。
4. **每完成一个阶段就写一行进展**到本节对应清单（打勾 + 一句结论）。
5. **拿不准的时候按 §12 的默认答案走**，不要停下来等回复。

### 10.1 阶段一：装 dsh-pet（路径 A）

```bash
# 10.1.1 装
npm install -g dsh-pet

# 10.1.2 体检
dsh-pet-standalone --check
```

| 判定 | 含义 |
|------|------|
| ✅ 输出无 ERROR、端口可用 | 继续 10.2 |
| ❌ 提示缺 Electron / 缺 Python | 记下缺什么，**先继续做 10.2 的其他项**，回头再补 |
| ❌ 提示 Node 版本过低 | 升级 Node 到 ≥ 20 再重试 |

```bash
# 10.1.3 起服务（后台常驻）
dsh-pet-standalone
# 换端口用：dsh-pet-standalone --port 3100
```

**验收**（必须全部通过）：

```bash
curl http://127.0.0.1:3080/health          # 期望：服务与插件信息，含监听端口
curl http://127.0.0.1:3080/dsh-pet-7340/state   # 期望：JSON，含 counter / sections / pets
```

- ✅ 两个都返回 JSON → 继续 10.2
- ❌ 3080 被占 → 查 `netstat -ano | findstr :3080`；要么杀掉占用进程，要么换端口并**同步改** `avatar.base_url`
- ❌ 状态里 `pets` 是空的 → 桌宠实例没加载，查 `dsh-pet` 的日志；**不影响继续**，10.3 会再确认

### 10.2 阶段一：抄下它的实际动画池名字

这是路径 A 唯一必须人工核对的一步，但**判定标准是机械的**：

```bash
# 把服务端认为"存在"的动画都列出来
curl http://127.0.0.1:3080/dsh-pet-7340/config
```

响应里的 `animations` 对象就是动画池：

```jsonc
"animations": {
  "idle": ["待机"],
  "turn": [],
  "drag": [],
  "clicks": ["打滚"],
  "moves": {...},
  "categories": [...],
  "events": {...}
}
```

**把 `idle` / `turn` / `clicks` / `categories` / `events` 里出现过的所有名字**整理成一张表：

| 我们的档位 | 索引 | 用的动画名 | 从哪个池里来的 | 素材是否存在 |
|---|---|---|---|---|
| idle | 0 | 待机 | idle | ✅ |
| listening | 1 | （找最接近的；找不到就填 待机） | — | ❌ 需路径 B |
| caring | 2 | … | — | ❌ |
| playful | 3 | … | — | ❌ |
| serious | 4 | … | — | ❌ |
| tired | 5 | 打瞌睡 | idle | ✅ |
| thinking | 6 | 走 `/work-status` 的「思考」档 | events | ✅ |
| speaking | 7 | （找最接近的；找不到就填 待机） | — | ❌ |
| proactive | 8 | （同上） | — | ❌ |
| error | 9 | 走 `/work-status` 的「出错」档 | events | ✅ |

**判定标准**：
- 某个档位在池里**找不到近似动画** → 填 `待机`，并在 §12 的表里标「待路径 B」。
  **不要自己编名字** —— 桌宠找不到同名动画就是 404，编了不会报错，只会"没反应"，极难排查。
- `idle` 池里**一定**有"待机"这类常驻动画 —— 如果连它都没有，说明配置被改坏了，回头查 §10.1。

**把这张表写进 `config/avatar.example.yaml` 的 `tier_animations`**，同时更新本节。

### 10.3 阶段一：接进我们的配置

```yaml
# 加到实际生效的配置里（AstrBot 主配置，见 §10.5 定位）
avatar:
  enabled: true
  base_url: "http://127.0.0.1:3080/dsh-pet-7340"
  pet_id: "main"
  timeout: 3.0
  max_consecutive_failures: 5
  menu_owner: "companion-bot"
  tier_animations:
    0: "待机"
    5: "打瞌睡"
    # ...按 10.2 的表填全
```

**验收**：

```bash
python scripts/test-avatar.py
```

- ✅ 输出 `[OK] all assertions passed` 且 `[OK] auto-disabled after repeated failures` → 继续 10.4
- ❌ 断言失败 → 看实际调用序列，对照 §3.1 的接口表核对路径和参数

### 10.4 阶段一：端到端验收

```bash
# 1) 桌宠单独说话（不经过我们的 LLM）
curl -X POST "http://127.0.0.1:3080/dsh-pet-7340/lock?pet=main" -d '{}' -H "Content-Type: application/json"
#    → 拿到 lockId

curl -X POST "http://127.0.0.1:3080/dsh-pet-7340/broadcast?pet=main&lock=<lockId>" \
  -H "Content-Type: application/json" -d '{"text":"测试气泡"}'

curl -X POST "http://127.0.0.1:3080/dsh-pet-7340/lock/release?pet=main&lock=<lockId>" -d '{}'
```

- ✅ 桌宠头顶出现"测试气泡" → 接口调通了，继续
- ❌ 返回 `lock-required` → `lock` 参数没带上
- ❌ 返回 `lock-lost` → 锁被撤销了（用户拖过桌宠，或上一次没释放）。**重新取锁再试**
- ❌ 气泡没出来但接口返回 ok → 动画名/素材有问题，回 10.2

然后走一遍完整链路：

| 场景 | 期望 |
|------|------|
| 发一条消息 | 桌宠弹气泡显示回复；LLM 生成期间切「思考」 |
| 说"我有点累" | 情绪切到 tired → 播打瞌睡 |
| 说"哈哈太好笑了" | 情绪切到 playful → 播对应动画（或退回待机） |
| **把桌宠服务杀掉，再发一条消息** | **对话完全正常**，只是没有气泡 —— 这是硬性验收项 |

### 10.5 阶段一：配置落在哪（重要）

AstrBot 的**实际主配置不在仓库里**，在部署机上：

```
D:\dev\AstrBot\data\cmd_config.json      ← AstrBot 主配置（provider / memory / persona ...）
D:\dev\companion\config.json             ← 组件统一配置（路径 / 端口 / 环境变量）
```

`avatar:` 段加到 **`cmd_config.json`** 里（我们 `CompanionHandler` 拿到的就是这份 config dict）。
`config/avatar.example.yaml` 只是**模板和档位表的存档**，不是运行时读的文件。

### 10.6 阶段二：原创形象（路径 B）

**触发条件**：阶段一验收通过，且确认要做情绪向的动画（§4 说的那六档）。

1. **定动作清单** —— 按 `prompts/桌面宠物 10 秒动作提示词.md` 的配方，每档一个动作：
   倾听 / 关心 / 俏皮 / 认真 / 说话 / 主动搭话 / 思考 / 出错
2. **出素材** —— 绿幕视频 → 按 MAKE-YOUR-OWN-PET.md ② 的路线 A（HSV 自动抠像）
   → VP9-alpha webm，24 fps，412×344
3. **落盘** —— 两种方式：
   - 简单：放进 `main-animation/webm/`，**优先级高于包内素材** → 直接改 `tier_animations`
   - 完整：做成 pet pack（`pet/<名字>-config.json` + `pet/<名字>-animation/`），
     适合"每个人格一只独立宠物"
4. **验收** —— 逐档 `/anim` 点播，画面动作对得上

### 10.7 完成后要写回本仓库的东西

| 内容 | 写到哪 |
|------|--------|
| 实际动画池的名字表 | `config/avatar.example.yaml` 的 `tier_animations` + 本文 §10.2 的表 |
| 实测的端口、启动方式、坑 | `docs/local-stack.md`（本机实际运行栈） |
| 阶段进度 | `plans/roadmap.md` 的 Phase 4.5 清单 |
| 新的坑 / API 差异 | 本文的 §11「踩坑记录」 |

---

## 11. 踩坑记录（执行时补充）

| 现象 | 原因 | 解法 |
|------|------|------|
| 桌宠完全不出现 | 服务没起 / 端口不对 / profile 是 desktop 不是 web | `curl /health` 确认端口；`dsh-pet-standalone` 默认 3080 |
| 气泡没出来但接口返回 ok | 动画名在池里不存在（404 被吞） | 回 §10.2 核对动画名 |
| `lock-required` | 动作接口没带 `?lock=` | 先 `POST /lock` 拿 lockId |
| `lock-lost` | 锁过期 / 被用户拖走抢走 / 上次没释放 | 重新取锁；`cause` 字段会说原因 |
| 桌宠一直不动 | **锁没释放** —— 持锁期间它完全静止 | 检查是否漏了 `POST /lock/release` |
| 浏览器里透明背景变黑 | Safari 不支持 webm alpha | 用 Chromium/Firefox；macOS 改用 `.mov` 素材 |
| Windows 首次启动很慢 | 解压 ~100 MB Qt 运行库，杀毒实时扫描拖慢 | 等（上限 180 秒）；别重复启动 |
| `dsh-pet-standalone` 报缺 Electron | 首次运行要自动下载 Electron | 联网等下载完；或手动 `cd dsh-pet && npm run ensure:electron` |
| 我们的对话变慢了 | 适配层每次动作 3 个 HTTP 往返 | 正常开销只有几毫秒；若真慢了，检查是不是没释放锁导致桌宠反复重载 |

---

## 12. 确认项登记表

> **这张表是决策记录，不是待办。**「默认答案」= 已定的做法，agent 直接照做即可，
> 只有当现场证据**证伪**了默认答案时，才需要停下来找人确认。

| # | 确认项 | 默认答案 | 什么时候需要推翻它 |
|---|--------|---------|-----------------|
| 1 | 走哪条路径 | **路径 A 先行，路径 B 后续** | 路径 A 验收不通过，或一开始就确定要商用 |
| 2 | 能不能用大肥鱼素材 | **能**（目前纯自用） | 出现任何商业计划 → 立刻切路径 B |
| 3 | 署名义务 | 公开渠道附 `https://github.com/PC2005-cloud/dsh-pet` | —— |
| 4 | 桌宠跑在哪个端口 | **3080**（`dsh-pet-standalone` 默认） | 端口被占 → 换端口并同步改 `avatar.base_url` |
| 5 | 动画名怎么定 | **抄它实际的池子**，找不到就填"待机" | 池子里确实没有常驻动画 → 配置坏了，回查安装 |
| 6 | 六档情绪向动画 | **路径 A 阶段先占位**，路径 B 再做 | —— |
| 7 | 适配层失败怎么办 | **吞掉 + 连续 5 次自我关闭** | 对话真的被形象层拖慢了 → 再查 HTTP 往返 |
| 8 | `avatar:` 配置写哪 | **`D:\dev\AstrBot\data\cmd_config.json`** | 部署结构变了 → 以 `docs/local-stack.md` 为准 |
| 9 | 要不要锁 | **每个动作一个锁周期**（取→演→放） | 出现"桌宠不动" → 检查锁没释放 |
| 10 | 桌宠要不要接语音时序 | **暂不接**（先只做文本→气泡） | 语音链路稳定后再做「说话动画与 TTS 首包对齐」 |

---

## 13. 与本文相关的其他确认项（2026-10-26 顺带发现的文档不一致）

> 这些不是形象层的事，但会让部署机 agent 读到互相矛盾的文档，**已按默认答案处理**：

| # | 不一致 | 默认答案 | 处理 |
|---|--------|---------|------|
| 1 | `config/astrbot.example.yaml` 已从仓库删除，但 `deployment.md` / `model-strategy.md` 还在引用 | 主配置已迁到 `D:\dev\AstrBot\data\cmd_config.json` | 已把两处引用改成指向新位置 |
| 2 | 多处文档写 TTS 用 IndexTTS2，实测用的是 **VoxCPM2（主）/ Qwen3-TTS（备）** | 以实测为准 | 已改 `hardware-budget.md` / `model-strategy.md` 的 TTS 表述 |
| 3 | 文档写 Ollama "≥ v0.31.2"，实际部署的是 **v0.40.10** | 以实际为准 | 已更新版本要求 |
| 4 | `config/*.yaml` 被 `.gitignore` 挡掉，新增的 `avatar.example.yaml` 进不了版本库 | 模板必须进库 | 已在 `.gitignore` 加 `!config/*.example.yaml` 例外 |

---

## 相关文档

[[architecture.md]] · [[persona-system.md]] · [[model-strategy.md]] · [[companion-features.md]] · [[streaming-pipeline.md]] · [[local-stack.md]] · [[deployment.md]]
