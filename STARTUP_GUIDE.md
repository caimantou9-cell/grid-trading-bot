# Neutral Grid Bot — 零环境启动指南

本文档说明如何在**全新的电脑**（没有任何 Python 环境）上快速启动网格机器人。

---

## 一分钟快速启动

### Windows

双击运行 `start.bat`，脚本会自动检测环境、安装依赖、引导配置并启动机器人。

### Linux / macOS

```bash
chmod +x start.sh
./start.sh
```

---

## 准备工作

### 1. 安装 Python（仅首次需要）

如果电脑上没有 Python，需要先安装：

| 系统 | 安装方式 |
|------|----------|
| **Windows** | 下载 [Python 3.10+ 安装包](https://www.python.org/downloads/)，安装时**勾选 "Add Python to PATH"** |
| **macOS** | `brew install python`（需要先安装 [Homebrew](https://brew.sh/)） |
| **Linux** | `sudo apt install python3 python3-venv python3-pip`（Ubuntu/Debian） |

安装完成后，打开终端/命令行验证：

```bash
python --version   # 或 python3 --version
```

---

## 获取项目代码

### 方式 A：从 GitHub 克隆

```bash
git clone https://github.com/your-org/grid-bot.git
cd grid-bot
```

### 方式 B：复制文件夹

将整个项目文件夹复制到新电脑上。

---

## 启动方式

### Windows 用户：使用 start.bat

直接**双击 `start.bat`** 或在命令提示符（CMD）中运行：

```bash
cd C:\path\to\grid-bot
start.bat
```

`start.bat` 会自动完成以下工作：
1. 检测 Python 是否已安装
2. 创建 Python 虚拟环境（`.venv`）
3. 安装基础依赖（`pydantic`）
4. 检查交易所 SDK 是否已安装
5. 如果没有 `config.json`，从 `config.json.example` 自动创建
6. 引导你编辑配置文件
7. 启动机器人

**命令行参数**（可选）：

```bash
start.bat extendedx debug   # 使用 ExtendedX + DEBUG 日志级别
start.bat lighter info      # 使用 Lighter + INFO 日志级别
```

### Linux / macOS 用户：使用 start.sh

```bash
chmod +x start.sh           # 首次需要赋予执行权限
./start.sh                  # 运行启动脚本
```

**命令行参数**（可选）：

```bash
./start.sh extendedx debug   # 使用 ExtendedX + DEBUG 日志级别
./start.sh lighter warning    # 使用 Lighter + WARNING 日志级别
```

---

## 手动启动（不依赖启动脚本）

如果启动脚本遇到问题，或你想了解底层命令：

### 1. 创建虚拟环境

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# Linux / macOS
python3 -m venv .venv
source .venv/bin/activate
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 安装交易所 SDK（根据你使用的交易所选择）

**ExtendedX 用户：**

```bash
# 从 GitHub 克隆
git clone https://github.com/extended-exchange/x10-python-trading-starknet.git C:\path\to\extended-pythonsdk

# 设置 PYTHONPATH（Linux/macOS）
export PYTHONPATH=/path/to/extended-pythonsdk:$PYTHONPATH

# Windows：手动将路径添加到环境变量，或在启动命令中加入
set PYTHONPATH=C:\path\to\extended-pythonsdk;%PYTHONPATH%
```

**Lighter 用户：**

```bash
# 从 GitHub 克隆
git clone https://github.com/lighter-exchange/lighter-v2-api.git /opt/lighter-sdk

# 设置 PYTHONPATH
export PYTHONPATH=/opt/lighter-sdk:$PYTHONPATH
```

### 4. 配置机器人

```bash
# 复制配置文件模板
cp config.json.example config.json
```

用文本编辑器打开 `config.json`，填写以下内容：

```json
{
  "exchange": {
    "adapter": "exchanges.extendedx.ExtendedXAdapter",   // 或 exchanges.lighter.LighterAdapter
    "api_key": "YOUR_API_KEY",
    "api_secret": "YOUR_API_SECRET",
    "extra": { ... }
  },
  "strategy": {
    "symbol": "BTC-USD",
    "lower_price": "60000",
    "upper_price": "80000",
    "grid_count": 10,
    "is_arithmetic": true,
    "total_investment": "500"
  }
}
```

详细配置说明请参考 `docs/quickstart.md` 或本文档的"配置文件详解"章节。

### 5. 启动机器人

```bash
# 激活虚拟环境后
python main.py --config config.json

# 或指定日志级别
python main.py --config config.json --log-level DEBUG

# 或指定日志文件
python main.py --config config.json --log-file my_grid.log
```

---

## 配置文件详解

### exchange 区块

#### ExtendedX 配置

```json
"exchange": {
  "adapter": "exchanges.extendedx.ExtendedXAdapter",
  "api_key": "YOUR_STARK_PUBLIC_KEY",
  "api_secret": "YOUR_STARK_PRIVATE_KEY",
  "extra": {
    "stark_public": "0x...",
    "stark_vault": 123456,
    "network": "mainnet"
  }
}
```

| 字段 | 说明 |
|------|------|
| `api_key` | ExtendedX REST API Key（Bearer token） |
| `api_secret` | Stark 私钥（hex 字符串） |
| `extra.stark_public` | Stark 公钥（hex 字符串） |
| `extra.stark_vault` | 账户 Vault ID（整数） |
| `extra.network` | `"mainnet"` 或 `"testnet"` |

#### Lighter 配置

```json
"exchange": {
  "adapter": "exchanges.lighter.LighterAdapter",
  "api_key": "0",
  "api_secret": "0xYOUR_HEX_PRIVATE_KEY",
  "extra": {
    "market_map": {
      "BTC-USDC-PERP": 1,
      "ETH-USDC-PERP": 0
    }
  }
}
```

| 字段 | 说明 |
|------|------|
| `api_key` | 账户索引（通常填 `"0"`） |
| `api_secret` | 钱包私钥（hex 字符串，以 `0x` 开头） |
| `extra.market_map` | 市场名称到 ID 的映射 |

### strategy 区块

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `symbol` | 字符串 | ✅ | 交易对名称（如 `BTC-USD`、`BTC-USDC-PERP`） |
| `lower_price` | 数字 | ✅ | 网格价格下限 |
| `upper_price` | 数字 | ✅ | 网格价格上限 |
| `grid_count` | 整数 | ✅ | 网格数量（2~300） |
| `is_arithmetic` | 布尔 | 否 | `true` = 等差网格，`false` = 等比网格 |
| `qty_per_grid` | 数字 | 至少填一项 | 每格下单数量（基础货币） |
| `total_investment` | 数字 | 至少填一项 | 总投入资金（报价货币），自动计算每格数量 |
| `stop_loss` | 数字 | 否 | 止损价格 |
| `take_profit` | 数字 | 否 | 止盈价格 |

> `qty_per_grid` 和 `total_investment` **至少填其中一个**（另一个设为 `null`）。

---

## 常见问题

### Q: 启动时报 `ModuleNotFoundError: No module named 'pydantic'`

**原因**：虚拟环境未激活，或依赖未安装。

**解决**：
```bash
# 激活虚拟环境
source .venv/bin/activate   # Linux/macOS
.venv\Scripts\activate     # Windows

# 重新安装依赖
pip install -r requirements.txt
```

### Q: 启动时报 `ModuleNotFoundError: No module named 'x10'`

**原因**：ExtendedX SDK 未安装。

**解决**：
```bash
git clone https://github.com/extended-exchange/x10-python-trading-starknet.git /tmp/extended-pythonsdk
export PYTHONPATH=/tmp/extended-pythonsdk:$PYTHONPATH   # Linux/macOS
# Windows: set PYTHONPATH=C:\path\to\extended-pythonsdk;%PYTHONPATH%
```

### Q: 启动时报 `ModuleNotFoundError: No module named 'lighter'`

**原因**：Lighter SDK 未安装。

**解决**：
```bash
git clone https://github.com/lighter-exchange/lighter-v2-api.git /tmp/lighter-sdk
export PYTHONPATH=/tmp/lighter-sdk:$PYTHONPATH
```

### Q: 启动时报 `Invalid hex private key`

**原因**：`api_secret` 不是有效的十六进制字符串。

**解决**：检查 `config.json` 中的 `api_secret` 是否以 `0x` 开头且后跟有效的十六进制字符。

### Q: 启动时报 `symbol not found` 或订单提交失败

**原因**：`symbol` 与交易所要求不完全一致。

**解决**：检查 `strategy.symbol` 是否与交易所要求的格式完全一致（包括大小写和连字符）。

**常用 symbol 格式**：

| 交易所 | 市场 | `symbol` 值 |
|--------|------|-------------|
| ExtendedX | BTC 永续 | `BTC-USD` |
| ExtendedX | ETH 永续 | `ETH-USD` |
| Lighter | BTC 永续 | `BTC-USDC-PERP` |
| Lighter | ETH 永续 | `ETH-USDC-PERP` |

### Q: 想要同时运行多个交易对

**解决**：复制 `config.json` 为多个配置文件，然后启动多个进程：

```bash
python main.py --config config_btc.json &
python main.py --config config_eth.json &
```

### Q: 如何停止机器人？

**安全停止**：按 `Ctrl+C`，机器人会自动取消所有挂单并安全退出。

> ⚠️ **不要使用 `kill -9`**（强制终止），这会导致挂单留在交易所未被撤销。

---

## 日志解读

机器人运行时会输出以下关键日志：

| 日志关键词 | 含义 |
|------------|------|
| `Strategy initialized` | 网格策略初始化成功 |
| `Initial mid price` | 当前市场价格 |
| `Setup complete: N buy + N sell` | 初始挂单完成 |
| `FILLED buy @ XXXXX` | 买单在 XXXXX 价格成交 |
| `FILLED sell @ XXXXX` | 卖单在 XXXXX 价格成交 |
| `Stop-loss triggered` | 触发止损，正在撤单退出 |
| `Take-profit triggered` | 触发止盈，正在撤单退出 |
| `Liq-safety stop-loss updated` | 动态止损更新 |

日志同时写入 `config.json` 中 `log_file` 指定的文件（默认 `grid.log`）。

---

## 文件结构说明

```
grid-bot/
├── start.bat              # Windows 一键启动脚本
├── start.sh               # Linux/macOS 一键启动脚本
├── main.py                # 机器人入口文件
├── requirements.txt       # Python 依赖列表
├── config.json            # 配置文件（从 config.json.example 复制后编辑）
├── config.json.example    # 配置文件模板
├── exchanges/
│   ├── base.py            # 交易所适配器抽象接口
│   ├── extendedx.py        # ExtendedX 交易所适配器
│   └── lighter.py         # Lighter 交易所适配器
├── grid/
│   ├── config.py          # 网格配置参数模型
│   └── strategy.py        # 核心网格交易逻辑
├── docs/
│   └── quickstart.md      # 详细入门指南
└── STARTUP_GUIDE.md       # 本文档
```

---

## 启动命令速查表

```bash
# ===== Windows =====

# 方式 1：双击 start.bat（推荐）

# 方式 2：命令行
cd C:\path\to\grid-bot
start.bat

# 方式 3：手动命令
.venv\Scripts\activate
set PYTHONPATH=C:\path\to\extended-pythonsdk;%PYTHONPATH%
python main.py --config config.json --log-level INFO


# ===== Linux / macOS =====

# 方式 1：启动脚本（推荐）
chmod +x start.sh
./start.sh

# 方式 2：手动命令
source .venv/bin/activate
export PYTHONPATH=/path/to/extended-pythonsdk:$PYTHONPATH
python main.py --config config.json --log-level INFO
```
