# A股每日复盘报告系统

基于 AkShare 数据源 + DeepSeek AI 的 A 股每日行情分析复盘系统，提供涨停分析、连板天梯、板块轮动、情绪周期、消息面解读、AI 综合决策以及多周期板块趋势预测等功能。

## 功能概览

### 1. 市场数据与情绪
- 今日 vs 昨日核心指标对比（涨停/跌停/炸板/连板/北向资金等）
- 昨日涨停溢价分析（晋级率、盈亏比）
- 情绪周期自动判断（亢奋→上升→修复→震荡→退潮→冰点）
- 涨停池按主题分类展示

### 2. 连板天梯与龙头判断
- 首板到最高板的完整梯队可视化
- 梯队完整性、断层位置、核心龙头识别
- 龙头明日预期判断

### 3. 板块轮动分析
- 强势板块 TOP5（涨停家数、龙头个股、涨跌幅）
- 行业/概念涨幅 TOP10
- 板块轮动特征（共振/轮动/跷跷板判断）
- 退潮预警

### 4. 消息面
- 财联社实时新闻抓取
- 自动匹配受影响板块并标注

### 5. AI 综合分析与决策输出
- 接入 DeepSeek 大模型
- 输出：今日主线、核心龙头、明日预期、退潮风险、可观察标的

### 6. 板块趋势与轮动预测
- TOP 行业/概念板块多周期（1周/1月/3月/半年/1年）涨幅热力图
- AI 分析板块轮动全景、强势追踪、新兴方向挖掘、衰退预警
- 未来不同时间维度（明日→本周→未来1月）趋势预测

### 静态快照
- 每次加载报告后自动保存为独立 HTML 文件（`reports/YYYYMMDD.html`）
- 无需启动服务即可直接打开浏览器查看历史报告

## 技术栈

| 组件 | 技术 |
|------|------|
| 数据源 | [AkShare](https://akshare.akfamily.xyz/) |
| 后端 | Flask + Pandas |
| AI 分析 | DeepSeek API（兼容 OpenAI SDK） |
| 前端 | 原生 HTML/CSS/JS + marked.js |
| 缓存 | 本地 JSON 文件 |

## 项目结构

```
a-stock-daily-report/
├── app.py              # Flask 后端（数据拉取、分析、AI 调用）
├── requirements.txt    # Python 依赖
├── static/
│   └── index.html      # 前端单页应用
├── cache/              # 日报数据缓存（YYYYMMDD.json）
├── cache_trend/        # 板块趋势缓存（YYYYMMDD.json）
└── reports/            # 静态 HTML 快照（YYYYMMDD.html）
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 DeepSeek API Key

AI 分析功能需要配置 DeepSeek API 密钥。将以下内容添加到 `~/.zshrc` 或 `~/.bashrc`：

```bash
export DEEPSEEK_API_KEY="your-api-key-here"
```

然后重新加载：

```bash
source ~/.zshrc
```

> 不配置此变量时，系统仍可正常运行，仅 AI 分析和趋势预测部分不可用。

### 3. 启动服务

```bash
python app.py
```

服务启动后访问 http://127.0.0.1:5788 ，页面会自动加载当日复盘数据。

首次加载约需 2-3 分钟（包含数据拉取 + 两次 AI 分析），后续访问会读取缓存，秒级响应。

### 4. 查看历史快照

无需启动服务，直接用浏览器打开：

```bash
open reports/20260424.html
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 前端页面 |
| GET | `/api/report?date=YYYYMMDD&force=0\|1` | 获取日报数据（force=1 清缓存重新拉取） |
| POST | `/api/ai_analyze` | 单独触发 AI 分析 |
| POST | `/api/save_snapshot` | 保存 HTML 快照 |
| GET | `/reports/YYYYMMDD.html` | 访问静态快照 |
| GET | `/api/dates` | 获取近期交易日列表 |

## 数据缓存机制

- 每个交易日的数据拉取后缓存为 `cache/YYYYMMDD.json`，避免重复调用 AkShare
- 板块趋势数据独立缓存在 `cache_trend/YYYYMMDD.json`
- 点击页面"刷新"按钮（带 `force=1`）可强制清缓存重新拉取

## 注意事项

- 本系统设计用于 A 股交易日收盘后复盘使用
- "上涨/下跌家数"来自乐咕实时接口，仅当日数据准确，历史日期显示为当日实时值
- AkShare 部分接口有频率限制，系统已内置延时和重试机制
- 所有分析仅供复盘参考，不构成投资建议
