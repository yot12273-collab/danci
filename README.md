# 📚 英语词汇学习助手

移动端优先的英语词汇学习 Web 应用。输入单词（或它的变形），自动还原词根、展示全形态变化、推荐形近词、给出中文释义；支持生词本、标签分类、查询历史，以及从 `.docx` 文档批量导入生词。

## 功能特性

- **词法分析**：合法性校验（乱码/拼写错误给出明确提示）、形态追踪（`running→run` 现在分词、`cats→cat` 复数、`better→good` 比较级）、全形态展示（原形/过去式/过去分词/三单/现在分词/复数等）。
- **中文释义**：本地 SQLite 词典（ECDICT 裁剪，约 112 万词条），离线、零延迟、稳定。
- **形近词推荐**：基于编辑距离 + 词频排序 + 常见易混淆词表。
- **外部搜索**：一键跳转 Bing / 剑桥 / 韦氏 / 有道 / Google。
- **生词本**：词根去重入库，支持标签分类、按标签过滤。
- **标签管理**：增删改查，标签可关联多个单词。
- **查询历史**：按输入原文去重，支持单条删除、一键清空。
- **docx 导入**：解析段落 + 表格，提取英文单词、过滤中文/标点、词形还原去重，以文件名自动建标签批量入库，带进度反馈。

## 目录结构

```
vocab-app/
├── app/                      # 后端（FastAPI 应用包）
│   ├── main.py               # 应用入口：路由装配、静态托管、异常处理
│   ├── config.py             # 配置（路径、上传限制、可选在线词典密钥）
│   ├── database.py           # SQLModel/SQLAlchemy 引擎与会话（SQLite + WAL）
│   ├── models/               # 数据表模型：Tag / Word / TagWord / SearchHistory
│   ├── schemas/              # Pydantic 请求体 DTO + 统一响应信封/错误码
│   ├── services/             # 业务逻辑层
│   │   ├── nlp_engine.py     #   词法分析引擎（词形还原/形态/形近词/链接）
│   │   ├── dictionary.py     #   中文释义服务（本地词典查询）
│   │   ├── word_service.py   #   查词编排 + 生词库 CRUD
│   │   ├── tag_service.py    #   标签 CRUD
│   │   ├── history_service.py#   查询历史
│   │   └── docx_service.py   #   docx 解析导入 + 后台任务进度
│   ├── routers/              # 路由层（words / tags / history / import_docx）
│   └── utils/                # 工具（时间、文本分词）
├── data/
│   ├── dict.sqlite           # 中文词典库（已构建，约 112 万词条）
│   └── app.db                # 业务数据库（首次启动自动生成）
├── scripts/build_dict.py     # 从 ECDICT StarDict 重建 dict.sqlite 的脚本
├── docs/architecture.md      # 技术架构与 API 设计文档
├── static/                   # 前端（原生 JS，移动端优先）
│   ├── index.html
│   ├── style.css
│   └── app.js
└── requirements.txt          # 依赖清单
```

## 快速开始

```bash
# 1. 安装依赖（建议 Python 3.10+，可先用 venv 隔离环境）
pip install -r requirements.txt

# 2. 启动服务（绑定 0.0.0.0，供手机访问）
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

- 本机浏览器访问：`http://127.0.0.1:8000`
- 手机（同一 Wi-Fi）访问：`http://<本机局域网IP>:8000`

> 词典库 `data/dict.sqlite` 已随项目构建好，无需额外步骤；如需从 ECDICT 源码重建，见文末。

### 一键启停（Windows 双击脚本）

项目根目录已提供两个脚本，双击即可，无需手动敲命令：

| 脚本 | 作用 |
|------|------|
| `start.bat` | 启动服务（绑定 `0.0.0.0:8000`）；直接关闭该窗口，或在窗口里按 `Ctrl+C` 即可停止 |
| `stop.bat`  | 结束占用 8000 端口的服务进程（适用于后台运行、找不到启动窗口的情况） |

> 若当前目录存在 `.venv` / `venv` 虚拟环境，`start.bat` 会自动激活后再启动；未创建则直接使用系统 Python。

## 在手机上访问

1. **查本机局域网 IP**（Windows，在 cmd/PowerShell 执行）：
   ```
   ipconfig
   ```
   找到当前 Wi-Fi 网卡下的 **IPv4 地址**，形如 `192.168.1.100`。（macOS / Linux 用 `ifconfig` 或 `ip addr`）

2. **确保手机与电脑连同一 Wi-Fi**，然后在手机 Safari 输入 `http://192.168.x.x:8000`。首次打开建议「添加到主屏幕」，获得全屏 App 体验。

3. **防火墙放行 8000 端口**（若手机打不开，多半是 Windows 防火墙拦截）。以管理员身份运行：
   ```
   netsh advfirewall firewall add rule name="uvicorn8000" dir=in action=allow protocol=TCP localport=8000
   ```
   或手动：控制面板 → Windows Defender 防火墙 → 高级设置 → 入站规则 → 新建规则 → 端口 → TCP 8000 → 允许连接。

4. 若仍不通，检查路由器是否开启了「AP 隔离 / 客户端隔离」，有则关闭；也请确认手机未走系统代理（直连局域网）。

## API 概览

统一响应信封：`{ "code": 0, "message": "ok", "data": ... }`，`code != 0` 表示出错。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/api/words/analyze?word=` | 查词（NLP + 中文释义，写入历史） |
| GET  | `/api/words` | 生词本列表（支持 `tag_id` / `q` / 分页） |
| POST | `/api/words` | 添加单词 `{word, tag_ids}` |
| DELETE | `/api/words/{id}` | 删除单词 |
| PUT  | `/api/words/{id}/tags` | 覆盖式设置单词标签 |
| GET/POST | `/api/tags` | 标签列表 / 新建 |
| PUT/DELETE | `/api/tags/{id}` | 修改 / 删除标签 |
| GET  | `/api/tags/{id}/words` | 标签下的单词 |
| GET  | `/api/history` | 查询历史 |
| DELETE | `/api/history/{id}` / `/api/history` | 单删 / 清空历史 |
| POST | `/api/import/docx` | 上传 docx（返回 `job_id`） |
| GET  | `/api/import/{job_id}` | 查询导入进度 |

完整设计见 [docs/architecture.md](docs/architecture.md)。

## 技术栈

- **后端**：Python 3.10+ / FastAPI / Uvicorn / SQLModel（SQLAlchemy 2.0 + Pydantic）/ SQLite（WAL）
- **NLP**：`lemminflect`（词形还原+变形生成）、`pyspellchecker`（合法性+形近词）
- **词典**：ECDICT（skywind3000/ECDICT）StarDict 裁剪为 SQLite
- **文档解析**：`python-docx`（段落 + 表格）
- **前端**：原生 HTML/CSS/JS，移动端优先，无构建步骤、无 CDN 依赖（离线可用）

## 重建中文词典（可选）

`data/dict.sqlite` 已构建好，通常无需重建。如需从 ECDICT 源码重新生成：

```bash
# 1. 下载并解压 ECDICT StarDict 包（GitHub Releases）
# 2. 运行脚本，生成 data/dict.sqlite
python scripts/build_dict.py <解压目录> data/dict.sqlite
```

> 提示：构建完成后，`tmp/` 下的原始下载包（约 340MB）可删除以节省空间。
