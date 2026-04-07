# 网格机器人 · 新手入门指南

本机器人在永续合约市场上运行网格策略：在价格区间内等间距（或等比距）挂单，价格下跌时买入，价格上涨时卖出，反复循环赚取价差。

---

## 1. 环境要求

| 组件 | 版本 |
|------|------|
| Python | 3.10 或以上 |
| 操作系统 | Linux / macOS / Windows |
| Exchange SDK | ExtendedX 或 Lighter（见下文） |

---

## 2. 安装步骤

```bash
# 1. 克隆代码
git clone https://github.com/your-org/grid-bot.git
cd grid-bot

# 2. 创建并激活虚拟环境（推荐）
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 安装交易所 SDK（根据你使用的交易所选择）
# ── ExtendedX ──────────────────────────────────
pip install -e /path/to/extended-pythonsdk
# ── Lighter ────────────────────────────────────
pip install -e /path/to/lighter-sdk
```

---

## 3. 配置文件

复制示例文件并重命名：

```bash
cp config.json.example config.json
```

然后用文本编辑器打开 `config.json`，按照下面的说明填写。

---

## 4. exchange 区块

### 4-A. 使用 ExtendedX

```json
"exchange": {
  "adapter": "exchanges.extendedx.ExtendedXAdapter",
  "api_key": "YOUR_STARK_PUBLIC_KEY",
  "api_secret": "YOUR_STARK_PRIVATE_KEY",
  "extra": {
    "stark_vault": 123456,
    "network": "mainnet"
  }
}
```

| 字段 | 说明 |
|------|------|
| `api_key` | Stark 公钥（以 `0x` 开头的十六进制字符串） |
| `api_secret` | Stark 私钥（以 `0x` 开头的十六进制字符串） |
| `extra.stark_vault` | 账户 vault ID（整数，在交易所控制台查询） |
| `extra.network` | `"mainnet"` 或 `"testnet"` |

> **如何获取 Stark 密钥？** 登录 ExtendedX 网页，进入"账户 → API 密钥"页面生成。

### 4-B. 使用 Lighter

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
| `api_key` | 账户索引（整数字符串，通常填 `"0"`） |
| `api_secret` | 钱包私钥（以 `0x` 开头的十六进制字符串） |
| `extra.market_map` | 市场名称 → market_id 的映射（BTC=1，ETH=0） |

---

## 5. strategy 区块（参数说明）

```json
"strategy": {
  "symbol":          "BTC-USD",
  "lower_price":     "60000",
  "upper_price":     "80000",
  "grid_count":      10,
  "is_arithmetic":   true,
  "qty_per_grid":    null,
  "total_investment":"500",
  "stop_loss":       null,
  "take_profit":     null
}
```

### 参数详情

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `symbol` | 字符串 | ✅ | 交易对名称，需与交易所完全一致（区分大小写） |
| `lower_price` | 数字字符串 | ✅ | 网格下边界价格 |
| `upper_price` | 数字字符串 | ✅ | 网格上边界价格 |
| `grid_count` | 整数 | ✅ | 网格区间数量（2 ~ 300）。区间越多，单格利润越小，交易越频繁 |
| `is_arithmetic` | 布尔值 | 否 | `true`= 等差网格（每格价格间距相等），`false`= 等比网格（每格价格比例相等）。默认 `true` |
| `qty_per_grid` | 数字字符串 | ✅① | 每格下单数量（以 **基础货币** 计，如 BTC）。优先级高于 `total_investment` |
| `total_investment` | 数字字符串 | ✅① | 总投入资金（以 **报价货币** 计，如 USDC）。自动计算每格数量 |
| `stop_loss` | 数字字符串 | 否 | 静态止损价。价格跌破此值时机器人自动停止并撤销所有挂单 |
| `take_profit` | 数字字符串 | 否 | 静态止盈价。价格突破此值时机器人自动停止 |

> ① `qty_per_grid` 和 `total_investment` 至少提供其中一个（填另一个为 `null`）。

#### 等差 vs 等比 网格

- **等差**：价格区间 60000 ~ 70000，10 格 → 每格间距 = 1000 USD（固定）
- **等比**：价格区间 60000 ~ 70000，10 格 → 每格比例 = 均匀分布对数空间（低价区间距更小，高价区更大）

等比网格更适合价格波动百分比较均匀的市场（大多数加密货币），等差网格适合价格在固定区间内震荡的市场。

---

## 6. 常用市场名称

| 交易所 | 市场 | `symbol` 填写值 |
|--------|------|-----------------|
| ExtendedX | BTC 永续 | `BTC-USD` |
| ExtendedX | ETH 永续 | `ETH-USD` |
| Lighter | BTC 永续 | `BTC-USDC-PERP` |
| Lighter | ETH 永续 | `ETH-USDC-PERP` |

---

## 7. 启动程序

```bash
# 确保虚拟环境已激活
source .venv/bin/activate

# 如果 SDK 不在 Python 环境中，需要手动指定 PYTHONPATH
export PYTHONPATH=/path/to/extended-pythonsdk:/path/to/lighter-sdk:$PYTHONPATH

# 启动机器人
python3 main.py --config config.json
```

启动后会在控制台看到类似输出：

```
INFO  [grid] Strategy initialized: BTC-USD arithmetic 10 grids [60000, 70000]
INFO  [grid] Initial mid price: 65432.00
INFO  [grid] Setup complete: 5 buy orders + 5 sell orders placed
INFO  [grid] Tick loop started (interval=10s)
```

---

## 8. 日志说明

| 日志关键词 | 含义 |
|------------|------|
| `Setup complete: N buy + N sell` | 初始建仓完成，N 个买单 + N 个卖单 |
| `FILLED buy @ 63000` | 63000 的买单成交，机器人挂出对应卖单 |
| `FILLED sell @ 64000` | 64000 的卖单成交，机器人挂出对应买单 |
| `Stop-loss triggered` | 价格触发止损，正在撤单并退出 |
| `Take-profit triggered` | 价格触发止盈，正在撤单并退出 |
| `Liq-safety stop-loss updated` | 动态止损更新（基于交易所爆仓价计算的安全边距） |

日志同时写入 `config.json` 中 `log_file` 所指定的文件（默认 `grid.log`）。

---

## 9. 安全停止

直接按 **Ctrl+C**，机器人会：
1. 停止接收新的行情数据
2. 取消所有未成交挂单
3. 安全退出

```
^C
INFO  [grid] Received shutdown signal
INFO  [grid] Cancelling 8 open orders...
INFO  [grid] Teardown complete. Exiting.
```

> **不要** 直接 `kill -9`，这会导致挂单留在交易所未被撤销。

---

## 10. 常见问题

**Q: 启动时报 `ModuleNotFoundError: No module named 'lighter'`**  
A: 确认已安装 Lighter SDK 并设置了正确的 `PYTHONPATH`。

**Q: 报 `Invalid hex private key`**  
A: `api_secret` 必须是有效的十六进制字符串（以 `0x` 开头，后跟 64 位十六进制字符）。

**Q: 报 `symbol not found` 或订单提交失败**  
A: 检查 `symbol` 是否与交易所要求完全一致，包括大小写和连字符。

**Q: 想同时运行多个交易对**  
A: 复制 `config.json` 为 `config_eth.json` 等，然后启动多个进程：
```bash
python3 main.py --config config_btc.json &
python3 main.py --config config_eth.json &
```

---

## 11. 配置示例

### ExtendedX BTC 等差网格（保守型）

```json
{
  "log_level": "INFO",
  "log_file": "grid_btc.log",
  "exchange": {
    "adapter": "exchanges.extendedx.ExtendedXAdapter",
    "api_key": "0x049d...",
    "api_secret": "0x0523...",
    "extra": { "stark_vault": 123456, "network": "mainnet" }
  },
  "strategy": {
    "symbol": "BTC-USD",
    "lower_price": "60000",
    "upper_price": "75000",
    "grid_count": 15,
    "is_arithmetic": true,
    "qty_per_grid": null,
    "total_investment": "1000",
    "stop_loss": "58000",
    "take_profit": "78000"
  }
}
```

### Lighter ETH 等比网格（积极型）

```json
{
  "log_level": "INFO",
  "log_file": "grid_eth.log",
  "exchange": {
    "adapter": "exchanges.lighter.LighterAdapter",
    "api_key": "0",
    "api_secret": "0xabcd1234...",
    "extra": { "market_map": { "ETH-USDC-PERP": 0 } }
  },
  "strategy": {
    "symbol": "ETH-USDC-PERP",
    "lower_price": "1800",
    "upper_price": "2400",
    "grid_count": 20,
    "is_arithmetic": false,
    "qty_per_grid": "0.01",
    "total_investment": null,
    "stop_loss": "1700",
    "take_profit": "2500"
  }
}
```
