# 移动端英语词汇学习与生词本 Web 应用 —— 技术架构与 API 接口设计文档

> 版本：v1.2（升级：闪卡测试改为拼写填空 + 单项选择，含自动纠错）　|　状态：进入实现阶段

## 0. 设计目标与原则

1. **本地优先、离线可用**：核心查词（词形还原、合法性、形近词）与中文释义全部本地化，不依赖外网；在线词典仅作为兜底。
2. **分层解耦**：路由层（routers）→ 服务层（services）→ 数据层（models）。
3. **数据持久化**：SQLite 统一承载「历史记录 / 标签 / 单词库」。
4. **移动端优先**：极简列表 + 底部抽屉交互，适配 iPhone Safari 与 PWA。

## 技术栈总览

| 层次 | 选型 |
|---|---|
| Web 框架 | FastAPI + Uvicorn（绑定 0.0.0.0:8000） |
| ORM | SQLModel（SQLAlchemy 2.0 + Pydantic） |
| 数据库 | SQLite（WAL 模式） |
| 词形还原 / 屈折变化 | lemminflect |
| 合法性 / 拼写纠错 | pyspellchecker |
| 形近词 | 自实现 Norvig edits1 + 词频过滤 |
| 中文释义（主） | ECDICT 本地轻量词典（裁剪 SQLite） |
| 中文释义（兜底） | 在线 API（可选，需 Key） |
| Word 解析 | python-docx |
| 前端 | HTML5 + TailwindCSS + 原生 JS |

## 1. 目录结构

```
vocab-app/
├── app/
│   ├── main.py / config.py / database.py
│   ├── models/        (tag, word, tag_word, search_history)   # 闪卡测试复用现有表，不新增
│   ├── schemas/       (common, word, tag, history, import_job, quiz)
│   ├── routers/       (words, tags, history, import_docx, quiz)
│   ├── services/      (nlp_engine, dictionary, word_service, tag_service, docx_service, history_service, quiz_service)
│   └── utils/         (text)
├── scripts/build_dict.py
├── data/              (app.db, dict.sqlite)
├── static/            (index.html, style.css, app.js)
├── requirements.txt
└── README.md
```

## 2. 数据库表结构

### tags
| 字段 | 类型 | 约束 |
|---|---|---|
| id | INTEGER | PK |
| name | TEXT(64) | UNIQUE NOT NULL |
| color | TEXT(16) | NULL |
| created_at | DATETIME | NOT NULL |

### words
| 字段 | 类型 | 约束 |
|---|---|---|
| id | INTEGER | PK |
| lemma | TEXT(64) | UNIQUE NOT NULL INDEX |
| primary_pos | TEXT(16) | NULL |
| phonetic | TEXT(64) | NULL |
| translation | TEXT | NULL（JSON 字符串） |
| short_meaning | TEXT(255) | NULL |
| created_at / updated_at | DATETIME | NOT NULL |

### tag_words
| 字段 | 类型 | 约束 |
|---|---|---|
| id | INTEGER | PK |
| tag_id | INTEGER | FK→tags.id CASCADE INDEX |
| word_id | INTEGER | FK→words.id CASCADE INDEX |

联合唯一 `UNIQUE(tag_id, word_id)`。

### search_history
| 字段 | 类型 | 约束 |
|---|---|---|
| id | INTEGER | PK |
| query | TEXT(64) | NOT NULL INDEX |
| lemma | TEXT(64) | NULL |
| searched_at | DATETIME | NOT NULL INDEX |

去重：按 `query` 去重，写入前删旧插新。

## 3. NLP 与词典方案

- 词形还原 / 屈折变化：lemminflect（getAllLemmas / getAllInflections）。
- 形态判定：优先「真正还原」的词根；按已确定词性反查形态；原形一词多性如实并列。
- 合法性 / 纠错：pyspellchecker（known / correction）。
- 形近词：Norvig edits1 + known 过滤 + 词频降序，距离不足补距离 2，前置易混淆词表。
- 中文释义：本地 ECDICT SQLite 为主 → 已缓存 → 在线（可选）三级降级。

## 4. Word 解析与批量入库

- python-docx 提取段落与表格文本。
- 正则 `[A-Za-z]+(?:['’][A-Za-z]+)*` 提取，小写归一、长度过滤、停用词过滤、合法性校验、词形还原、去重。
- 性能：单事务、内存 set 去重、`INSERT OR IGNORE` 批量、分块 1000/组、后台线程。
- 进度：后台任务 + 内存任务表 + 轮询（queued → processing → done/error）。

## 5. API 规范

统一封装：`{ code, message, data }`。

错误码：0 成功；40001 单词非法；40002 参数错误；40401 资源不存在；40901 冲突；41301 文件过大；41501 类型不支持；42201 校验失败；50001 内部错误；50301 词典不可用。

接口清单：含 analyze / words CRUD / tags CRUD / import / history；本次新增 quiz（见第 8 章）。

## 6. 前端交互

- 移动端单列流式布局，抽屉（Bottom Sheet）展示详情。
- 查词 → analyze → 卡片 + 抽屉（音标/释义/词形表/形近词/链接/标签）。
- 上传：本地校验 → POST → 轮询 job → 完成刷新。
- 标签详情：标签点击进入 → 极简列表（原形 / 词性 / 释义）→ 点击单词即查（见第 7 章）。
- 闪卡测试：选标签 → 双向抽卡 → 循环防重（见第 8 章）。

## 7. 标签详情页与「点击即查」

### 7.1 交互流程

1. **标签可点击进入**：标签列表页中的每一个标签（含通过 docx 导入自动生成的标签）均为可点击项，点击进入「标签详情」视图。
2. **详情页极简列表**：进入后仅展示该标签下所有单词的极简列表，每行只显示三项——**单词原形（lemma）**、**主要词性（primary_pos）**、**中文翻译（short_meaning）**。顶部不额外添加搜索框，保持界面清爽。
3. **点击即查（核心交互）**：点击列表中任意单词，视同发起一次完整的「单词全量查询」，通过底部抽屉（Drawer）或模态框（Modal）直接展示深度解析结果：全部时态与复数变形、3–5 个形近词推荐、一键跳转外部搜索引擎的按钮。

### 7.2 数据库设计

**完全复用现有三表，不新增任何表**：

- `tags` / `tag_words` / `words` 已足够支撑该交互。
- 列表数据来源：`GET /api/tags/{tag_id}/words` → `tag_words JOIN words`，仅投影 `lemma / primary_pos / short_meaning` 三字段。
- 关键设计点：`words.short_meaning` 在**入库时即生成**（取首个词性 + 释义，截断 60 字），故列表态无需再查词典、零额外计算，保证秒开。
- 点击后的深度解析完全复用 `words.lemma` → 走既有 `analyze` 流程（NLP + 词典），无需冗余存储。

### 7.3 API 规范

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/tags/{tag_id}/words` | 标签下单词极简列表（`items: [{id, lemma, primary_pos, short_meaning}]`） |
| GET | `/api/words/analyze?word={lemma}` | 点击即查：全量深度解析（复用既有能力，同时写入历史） |

> 该交互**不新增端点**，仅在前端增加「标签详情视图」与「点击 → analyze → 抽屉」的跳转逻辑，后端复用既有能力。

## 8. 闪卡抽查测试系统（互动式测试 + 自动纠错）

### 8.1 目标与范围

- 独立测试模块：选定一个标签 → 进入「抽查阶段」。
- **两种题型**：
  - 中译英（zh2en）：**拼写填空**，长度下划线 + 20% 字母提示，输入满格即自动校验、错误字母精准标红。
  - 英译中（en2zh）：**单项选择**，4 个中文释义选项（1 对 3 干扰），点选即校验、正误自动标色。
  - 混合（mix）：逐卡随机题型。
- **循环重复**：目标出题数 `target` 可大于该标签单词数（如 400 词抽 500 遍）。
- **会话内防重**：同一单词被抽出后，须间隔该标签总单词量 30% 之后才有资格再次被抽（保留）。

### 8.2 数据库设计

- 抽查序列为**内存态、一次性生成、无状态**，不落库；数据来源复用 `tags / tag_words / words` 三表。
- **MVP 不新增表**。理由：防重是「同一会话内」的冷却逻辑，会话结束即失效，无需持久化。
- **扩展点（预留）**：若未来要做**跨会话**的间隔重复（SM-2 遗忘曲线）或答题统计（正确率/熟练度），可新增 `review_state` 表（见 8.7）。

### 8.3 卡片数据结构（两种题型）

单张卡片（Card）由服务端在生成序列时**一次性组装完整题目**（含选项 / 答案索引 / 填空槽位），前端无需再组合，仅负责渲染与判分。

**中译英（zh2en）卡片 —— 拼写填空**

```json
{
  "word_id": 123,
  "lemma": "apple",
  "phonetic": "ˈæpəl",
  "primary_pos": "名词",
  "short_meaning": "n. 苹果",
  "direction": "zh2en",
  "slots": ["", "p", "", "", "e"],   // 长度=字母数；非空=提示字母(锁定)，空=待填
  "options": null,
  "answer_index": null
}
```

- 题干：`short_meaning`（中文翻译）。
- 输入区：按 `slots` 渲染方块填空；提示字母 / 连字符格锁定显示，空格待用户填写。

**英译中（en2zh）卡片 —— 单项选择**

```json
{
  "word_id": 456,
  "lemma": "run",
  "phonetic": "rʌn",
  "primary_pos": "动词",
  "short_meaning": "vi. 跑",
  "direction": "en2zh",
  "slots": null,
  "options": ["vi. 跑", "n. 苹果", "n. 书", "adj. 快乐的"],
  "answer_index": 0
}
```

- 题干：`lemma`（英文，+ 音标）。
- 4 个选项：`options`（已由后端打乱顺序），`answer_index` 为正确项下标。

### 8.4 算法实现思路

#### （1）首轮洗牌 —— Fisher–Yates 彻底打乱

保证第一轮 `n` 个单词恰好各出现一次，且顺序**彻底随机**（O(n)）：

```python
order = words[:]
for i in range(len(order) - 1, 0, -1):
    j = random.randrange(i + 1)
    order[i], order[j] = order[j], order[i]
```

#### （2）循环防重 —— 冷却窗口（滑动窗口排除）

核心：维护一个长度为 `gap` 的「最近已抽」窗口（deque）。每次抽题时**候选池 = 全集 − 冷却窗口**，随机抽取；抽中后把该词压入窗口，窗口超出 `gap` 则弹出最旧者。

- `gap = int(n * 0.30)`（n 为标签单词总数；如 400 → 120）。
- 该机制保证：某词抽出后，接下来 `gap` 次抽取都不会再抽到它（它一直停留在窗口内），**两次出现之间至少间隔 gap 个其他单词**。
- 正确性：`gap < n` 恒成立（0.3n < n），故候选池永不为空；仍保留兜底分支以防极端边界。
- 复杂度：每次抽取 O(n)（构建候选列表），n 通常数百、target 数千，总量在数十万次比较内，完全可接受。

```python
recent = deque(w.id for w in order[-gap:])   # 用首轮末尾 gap 个词初始化冷却窗口
while len(seq) < target:
    pool = [w for w in words if w.id not in recent]   # 候选 = 全集 − 冷却窗口
    w = random.choice(pool if pool else words)        # 兜底防池空
    seq.append(w)
    recent.append(w.id)
    if len(recent) > gap:
        recent.popleft()                              # 窗口长度保持 ≤ gap
```

#### （3）中译英填空槽位 slots —— 长度 + 20% 随机字母

- 仅字母位参与遮挡；非字母（连字符 `-`、撇号 `'`）**原样保留且锁定**，作为可见分隔符。
- 提示字母数 `k = max(1, round(字母数 * 0.20))`（4 字母 → 1 个，10 字母 → 2 个）。
- 随机选 `k` 个字母位显示真实字母，其余字母位留空（待填）。
- 返回 `slots` 数组（长度 = 单词长度），提示字母与连字符预填、空格为空字符串（空串即待填位）。

```python
def build_slots(word):
    alpha = [i for i, c in enumerate(word) if c.isalpha()]
    k = max(1, round(len(alpha) * 0.20)) if alpha else 0
    shown = set(random.sample(alpha, k))
    slots = []
    for i, c in enumerate(word):
        if not c.isalpha():      # 连字符 / 撇号：原样锁定
            slots.append(c)
        elif i in shown:         # 提示字母：锁定
            slots.append(c)
        else:                    # 待填位
            slots.append("")
    return slots
```

#### （4）英译中选项生成 —— 1 正确项 + 3 干扰项

- 正确项：当前单词的 `short_meaning`。
- 干扰项来源优先级：**当前标签库其他单词 → 全局词库（`words` 表）→ 系统词典（`dict.sqlite`）兜底**，随机抽取 3 条中文释义。
- **语义去重（保证「区别明显、不歧义」）**：先剥离词性前缀（`n.` / `vi.` 等）得到「释义主体」，若某候选的释义主体与正确项或已选干扰项相同（近义），则跳过。这样「苹果」不会与「苹果树」等近义释义混入同一题。
- 不足 3 条时从系统词典随机取一条「未出现过」的中文释义补齐，始终凑满 4 个选项。
- 最后 Fisher–Yates 打乱 4 项顺序，并记录正确项下标 `answer_index`。

```python
def build_options(words, correct, n_opts=4):
    def body(m):                       # 剥离词性前缀，只留中文释义主体
        return m.split(" ", 1)[1] if " " in m else m

    correct_text = correct.short_meaning or "（暂无释义）"
    seen = {body(correct_text)}
    candidates = []
    for w in words:                    # 优先：同标签其他单词
        if w.id == correct.id or not w.short_meaning:
            continue
        if body(w.short_meaning) in seen:   # 语义重复 / 近义 → 跳过
            continue
        seen.add(body(w.short_meaning))
        candidates.append(w.short_meaning)
    random.shuffle(candidates)
    distractors = candidates[:n_opts - 1]
    while len(distractors) < n_opts - 1:    # 不足 → 系统词典兜底
        distractors.append(_random_dict_meaning(seen))
    options = [correct_text] + distractors
    random.shuffle(options)             # Fisher–Yates 打乱选项
    return options, options.index(correct_text)
```

#### （5）完整生成流程（伪代码）

```python
def make_card(w, mode, words):
    """按题型组装卡片：zh2en 填 slots，en2zh 填 options + answer_index。"""
    direction = pick_direction(mode)
    card = {"word_id": w.id, "lemma": w.lemma, "phonetic": w.phonetic,
            "primary_pos": w.primary_pos, "short_meaning": w.short_meaning,
            "direction": direction}
    if direction == "zh2en":
        card.update(slots=build_slots(w.lemma), options=None, answer_index=None)
    else:
        card["options"], card["answer_index"] = build_options(words, w)
        card["slots"] = None
    return card

def generate_cards(words, target, mode):
    n = len(words)
    if n == 0 or target <= 0:
        return []
    gap = int(n * 0.30)
    if gap == 0:                                  # n < 4：30% 不足 1，退化为普通随机
        seq = [random.choice(words) for _ in range(target)]
    else:
        # ① 首轮 Fisher–Yates 洗牌
        order = words[:]
        for i in range(n - 1, 0, -1):
            j = random.randrange(i + 1)
            order[i], order[j] = order[j], order[i]
        seq = list(order)
        # ② 冷却窗口循环补足 target
        recent = deque(w.id for w in order[-gap:])
        while len(seq) < target:
            pool = [w for w in words if w.id not in recent]
            w = random.choice(pool if pool else words)
            seq.append(w)
            recent.append(w.id)
            if len(recent) > gap:
                recent.popleft()
    # ③ 组装卡片（按题型填充 slots / options）
    return [make_card(w, mode, words) for w in seq[:target]]
```

### 8.5 前端交互与校验逻辑

#### 8.5.1 中译英：拼写填空（单隐藏 input 映射多方块）

**渲染**：按 `slots` 渲染成**只读方块**（`<span>`，非输入框），并放置一个透明覆盖在方块区之上的隐藏 `<input>` 作为唯一的键盘接收者：
- 非空槽位（提示字母 / 连字符）→ 锁定显示（`.locked` 蓝底），不可编辑；
- 空槽位 → 空白方块，实时回显用户输入。
- 隐藏 `<input>` 用 `opacity:0` 透明覆盖整个方块网格，`font-size:16px`（≥16px 防止 iOS 聚焦时页面缩放）。

**为什么不用「逐格 input」**：多输入框模式下，光标遇到提示字母（`readonly`）格会卡住，需要手动点击下一格才能继续，移动端打字不连贯。单隐藏 input 让一个 `<input>` 接收全部按键，彻底规避焦点在多格之间跳跃的卡顿。

**状态管理（原生 JS，模块级状态 + DOM 同步）**：
- `editable: number[]`：空槽位在 `slots` 中的下标列表（即可编辑位）。
- `answers: string[]`：长度 = `slots.length`，初始为 `slots` 拷贝（提示位已填、可编辑位为 `""`）。
- 事件委托 `input`：读取隐藏 input 的 `value`，**按顺序**把第 `j` 个字符写入第 `editable[j]` 个方块（`cells[editable[j]].textContent = value[j]`），并同步回 `answers`。

**输入长度判定（触发校验的关键）**：
- 当隐藏 input 的 `value.length === editable.length`（所有可编辑位已填满）时，**立即**调用 `validateSpelling()`，无需提交按钮。
- `maxlength = editable.length` 从源头限制长度，退格删除由单 input 原生处理，无需自定义焦点跳转。

**校验与反馈（前端本地判分，答案依据后端下发的 `lemma`）**：
- 对每个可编辑位 `i` 逐位比对 `answers[i].toLowerCase() === lemma[i].toLowerCase()`（大小写不敏感）。
- **正确**：所有位一致 → toast「正确」并锁定输入，`setTimeout(next, 600ms)` 自动进入下一题。
- **错误**：存在不一致位 → 暂停自动跳转：
  - 不一致的可编辑位加 `.err`（红底 / 红字）**精准标红错误字母**；
  - 下方展示正确单词 `lemma`（加粗 / 绿色）；
  - 显示默认隐藏的「继续」按钮，用户点击后 `next()`。

#### 8.5.2 英译中：单项选择

**渲染**：按 `options` 渲染 4 个选项按钮。

**校验（点击即判，本地比对 `answer_index`）**：
- 状态 `locked: boolean` 防重复点击。
- 点击选项 `i`：
  - `i === answer_index` → 正确：该选项 `.ok`（绿），`locked=true`，`setTimeout(next, 600ms)` 自动跳过；
  - `i !== answer_index` → 错误：点错项 `.err`（红底），同时正确项 `.ok`（绿底），`locked=true`，显示「继续」按钮。

**自动跳过 vs 手动继续（两题型统一）**：
- 答对 → 自动跳过（约 600ms 视觉反馈后）；
- 答错 → 暂停，展示正确答案与标色，需手动点「继续 / 下一题」。

### 8.6 API 规范

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/quiz` | 发起一场抽查，返回完整卡片序列（含选项 / 答案索引 / 填空槽位） |

请求体：

```json
{ "tag_id": 5, "target": 500, "mode": "mix" }
```

- `tag_id`：选中的标签；`target`：目标出题数（可 > 单词数，循环重复）；`mode`：`en2zh` / `zh2en` / `mix`（mix 时逐卡随机方向）。

响应：

```json
{
  "code": 0, "message": "ok",
  "data": {
    "tag_id": 5, "word_count": 400, "total": 500, "mode": "mix",
    "cards": [ /* Card 数组，见 8.3 */ ]
  }
}
```

> **设计决策（已定）**：en2zh 的 4 个选项由**后端在出题时直接组装并打乱**（含 `answer_index`）返回，前端只渲染与判分、不自行组合——保证正确项唯一、干扰项语义去重、顺序随机，且题目数据自洽可审计。
>
> 序列一次性返回，前端本地顺序出题、判分，**无状态**；刷新页面仅需重新请求。答题正误仅前端维护（若需服务端统计，见 8.7 扩展）。

### 8.7 预留扩展：跨会话间隔重复（可选）

若后续需跨天复习（SM-2 遗忘曲线），可新增 `review_state` 表，与 `word_id` 1:1 关联：

| 字段 | 类型 | 说明 |
|---|---|---|
| word_id | INTEGER PK FK→words.id | 单词 |
| ease_factor | REAL | 难易系数（SM-2） |
| interval | INTEGER | 下次复习间隔（天） |
| due_at | DATETIME | 到期时间 |
| reps / lapses | INTEGER | 复习次数 / 遗忘次数 |

> 当前 MVP 不做，避免过度设计；会话内防重（8.4）与 SM-2 在数据层天然隔离。

## 9. 关键决策（已确认）

1. ORM 用 SQLModel，端点用 def（线程池执行）。
2. 中文词典以流畅稳定优先：本地 ECDICT 离线为主。
3. 历史按输入原文去重。
4. 本文档存档于 docs/architecture.md。

## 10. 语音朗读（Text-to-Speech，面向大陆学习者）

### 10.1 目标与发音源

- 纯前端实现，**不依赖浏览器 `Web Speech API`**（各设备内置语音包质量参差、口音不统一）。
- 直接调用国内公开免费发音接口 **有道词典 dictvoice**，URL 拼接即可播放，无需后端：
  - `https://dict.youdao.com/dictvoice?audio={单词}&type=2`
  - `type=1` 英音，`type=2` 美音（**默认美音**，测试设置页可全局切换）。

### 10.2 UI 位置（小喇叭图标）

统一内联 SVG 喇叭（`.spk-btn`），插入以下英文单词展示位置：

| 位置 | 说明 |
| --- | --- |
| 标签详情页单词列表 | 每个英文单词 `twi-word` 旁 |
| 单词详情抽屉 | 顶部主单词 `dw-word` 旁 |
| 测试 · 英译中 | 卡片正面英文 `choice-word` 旁 |
| 测试 · 中译英 | 校验失败后「正确答案」`lemma` 旁 |

### 10.3 交互逻辑与兼容性

- 点击小喇叭 → `new Audio(url)` 加载并 `play()`；URL 用 `encodeURIComponent(word)` 转义。
- **阻止事件冒泡**：用 `document` 级**捕获阶段**委托（`addEventListener('click', handler, true)`），命中 `.spk-btn` 即 `stopPropagation()`，确保标签列表点喇叭只发音、不会触发「点击单词打开详情」。
- **iOS Safari 兼容**：`play()` 在用户点击（click）的同步调用栈内触发，符合 iOS 自动播放安全策略；`play()` 返回的 Promise 以 `.catch(() => {})` 兜底，避免网络失败产生未处理 rejection。

### 10.4 关键实现

```js
let voiceType = 2;  // 2=美音(默认)，1=英音

function spkBtn(word) {
  return `<button class="spk-btn" data-word="${escapeHtml(word)}">
    <svg class="spk-icon" viewBox="0 0 24 24" fill="currentColor">…</svg></button>`;
}

function speakWord(word) {
  const audio = new Audio(`https://dict.youdao.com/dictvoice?audio=${encodeURIComponent(word)}&type=${voiceType}`);
  audio.play().catch(() => {});
}

document.addEventListener('click', (e) => {
  const btn = e.target.closest('.spk-btn');
  if (!btn) return;
  e.stopPropagation();
  speakWord(btn.dataset.word);
}, true);  // 捕获阶段：先于所有冒泡委托拦截
```

> 音色切换在测试设置页（`voice-btn`，复用 `mode-btn` 样式），全局 `voiceType` 变量供 `speakWord` 读取。
