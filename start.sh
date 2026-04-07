#!/bin/bash
# ============================================================
# Neutral Grid Bot — Linux/macOS 启动脚本
# ============================================================
#
# 使用方法:
#   ./start.sh                    # 交互式菜单
#   ./start.sh extendedx          # 使用 ExtendedX 交易所
#   ./start.sh lighter            # 使用 Lighter 交易所
#   ./start.sh extendedx debug    # 以 DEBUG 模式启动
#
# 第一次运行会自动：
#   1. 检查并安装 Python 3.10+（如未安装）
#   2. 创建 Python 虚拟环境
#   3. 安装所有依赖
#   4. 复制 config.json.example → config.json（如 config.json 不存在）
#   5. 提示你编辑配置文件
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
CONFIG_FILE="$SCRIPT_DIR/config.json"
CONFIG_EXAMPLE="$SCRIPT_DIR/config.json.example"
REQUIREMENTS="$SCRIPT_DIR/requirements.txt"

# 检测命令行参数
MODE=""
LOG_LEVEL="INFO"
for arg in "$@"; do
    case "$arg" in
        extendedx|lighter) MODE="$arg" ;;
        debug)  LOG_LEVEL="DEBUG" ;;
        info)   LOG_LEVEL="INFO" ;;
        warning) LOG_LEVEL="WARNING" ;;
    esac
done

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

print_info()  { echo -e "${CYAN}[i]${NC} $*"; }
print_ok()     { echo -e "${GREEN}[✓]${NC} $*"; }
print_warn()   { echo -e "${YELLOW}[!]${NC} $*"; }
print_error()  { echo -e "${RED}[✗]${NC} $*" >&2; }
print_header() { echo -e "\n${BOLD}${CYAN}==== $* ====${NC}"; }

# ============================================================
# 步骤 1: 检测 Python
# ============================================================
check_python() {
    print_header "检查 Python 环境"

    # 优先使用虚拟环境中的 Python
    if [[ -x "$VENV_DIR/bin/python" ]]; then
        PYTHON_CMD="$VENV_DIR/bin/python"
        PY_VERSION=$("$PYTHON_CMD" --version 2>&1)
        print_ok "发现虚拟环境 Python: $PY_VERSION"
        return 0
    fi

    # 检测系统 Python
    PYTHON_CMD=""
    if command -v python3 &> /dev/null; then
        PY_VERSION=$(python3 --version 2>&1)
        PYTHON_CMD="python3"
    elif command -v python &> /dev/null; then
        PY_VERSION=$(python --version 2>&1)
        PYTHON_CMD="python"
    else
        print_error "未找到 Python！"
        echo ""
        echo "请先安装 Python 3.10 或更高版本："
        echo "  Ubuntu/Debian:  sudo apt install python3 python3-venv python3-pip"
        echo "  macOS:          brew install python"
        echo "  Windows:        https://www.python.org/downloads/"
        echo ""
        echo "安装后请重新运行此脚本。"
        exit 1
    fi

    PY_VERSION=$("$PYTHON_CMD" --version 2>&1)
    print_ok "发现系统 Python: $PY_VERSION"

    # 检查版本
    PY_MAJOR=$("$PYTHON_CMD" -c 'import sys; print(sys.version_info.major)')
    PY_MINOR=$("$PYTHON_CMD" -c 'import sys; print(sys.version_info.minor)')
    if [[ "$PY_MAJOR" -lt 3 ]] || [[ "$PY_MAJOR" -eq 3 && "$PY_MINOR" -lt 10 ]]; then
        print_error "Python 版本过低，需要 3.10+，当前: $PY_VERSION"
        exit 1
    fi
}

# ============================================================
# 步骤 2: 创建虚拟环境
# ============================================================
setup_venv() {
    print_header "设置 Python 虚拟环境"

    if [[ ! -d "$VENV_DIR" ]]; then
        print_info "创建虚拟环境..."
        "$PYTHON_CMD" -m venv "$VENV_DIR"
        print_ok "虚拟环境创建成功"
    else
        print_ok "虚拟环境已存在，跳过"
    fi

    PIP_CMD="$VENV_DIR/bin/pip"
    PYTHON="$VENV_DIR/bin/python"
}

# ============================================================
# 步骤 3: 安装依赖
# ============================================================
install_deps() {
    print_header "安装 Python 依赖"

    if [[ ! -f "$REQUIREMENTS" ]]; then
        print_error "requirements.txt 未找到"
        exit 1
    fi

    # 升级 pip
    "$PIP_CMD" install --upgrade pip --quiet

    # 安装基础依赖
    "$PIP_CMD" install -r "$REQUIREMENTS" --quiet
    print_ok "基础依赖安装成功 (pydantic)"

    # 检查交易所 SDK
    install_exchange_sdk
}

# ============================================================
# 步骤 4: 安装交易所 SDK
# ============================================================
install_exchange_sdk() {
    print_header "安装交易所 SDK"

    # ExtendedX SDK
    if [[ -f "$SCRIPT_DIR/exchanges/extendedx.py" ]]; then
        print_info "ExtendedX 适配器已找到"

        if "$PYTHON" -c "import x10" 2>/dev/null; then
            print_ok "x10-python-trading-starknet 已安装"
        else
            print_warn "x10-python-trading-starknet 未安装"
            echo ""
            echo "  ExtendedX 需要 x10-python-trading-starknet SDK"
            echo ""
            echo "  获取方式（选择一种）："
            echo "    方式 A — 从 PyPI 安装（如果已发布）:"
            echo "      pip install x10-python-trading-starknet"
            echo ""
            echo "    方式 B — 从 GitHub 克隆后安装:"
            echo "      git clone https://github.com/extended-exchange/x10-python-trading-starknet.git /tmp/extended-pythonsdk"
            echo "      pip install -e /tmp/extended-pythonsdk"
            echo ""
            read -p "  请先安装 SDK，完成后按回车继续... " -r
        fi
    fi

    # Lighter SDK
    if [[ -f "$SCRIPT_DIR/exchanges/lighter.py" ]]; then
        print_info "Lighter 适配器已找到"

        if "$PYTHON" -c "import lighter" 2>/dev/null; then
            print_ok "lighter-sdk 已安装"
        else
            print_warn "lighter-sdk 未安装"
            echo ""
            echo "  Lighter 需要 lighter-v2-api SDK"
            echo ""
            echo "  获取方式："
            echo "    git clone https://github.com/lighter-exchange/lighter-v2-api.git /tmp/lighter-sdk"
            echo "    export PYTHONPATH=/tmp/lighter-sdk:\$PYTHONPATH"
            echo ""
            echo "  或者用 pip 直接安装（如果 SDK 支持）："
            echo "    pip install lighter-sdk"
            echo ""
            read -p "  请先安装 SDK，完成后按回车继续... " -r
        fi
    fi
}

# ============================================================
# 步骤 5: 检查/引导配置
# ============================================================
check_config() {
    print_header "检查配置文件"

    if [[ ! -f "$CONFIG_FILE" ]]; then
        if [[ ! -f "$CONFIG_EXAMPLE" ]]; then
            print_error "config.json.example 也未找到！"
            exit 1
        fi
        print_warn "未找到 config.json，正在从示例创建..."
        cp "$CONFIG_EXAMPLE" "$CONFIG_FILE"
        print_ok "已创建 config.json"
        echo ""
        echo -e "${BOLD}${RED}========================================${NC}"
        echo -e "${BOLD}${RED}  请先编辑 config.json 填写交易所凭证！${NC}"
        echo -e "${BOLD}${RED}========================================${NC}"
        echo ""
        echo "  文件位置: $CONFIG_FILE"
        echo ""
        echo "  必填项:"
        echo "    - exchange.adapter    <- 交易所适配器路径"
        echo "    - exchange.api_key    <- API 密钥"
        echo "    - exchange.api_secret <- API 密钥"
        echo "    - strategy.symbol     <- 交易对"
        echo "    - strategy.lower_price <- 价格下限"
        echo "    - strategy.upper_price <- 价格上限"
        echo "    - strategy.grid_count  <- 网格数量"
        echo ""
        echo "  快速打开方式:"
        echo "    Linux:   nano $CONFIG_FILE"
        echo "    macOS:   nano $CONFIG_FILE  或  open -t $CONFIG_FILE"
        echo ""
        read -p "  编辑完成后按回车继续... " -r
    else
        print_ok "config.json 已就绪"
    fi
}

# ============================================================
# 步骤 6: 启动机器人
# ============================================================
launch_bot() {
    print_header "启动网格机器人"

    echo "  配置文件: $CONFIG_FILE"
    echo "  日志级别: $LOG_LEVEL"
    echo ""

    # 设置 PYTHONPATH 以便找到 exchange SDK
    export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"

    print_info "执行命令:"
    echo "  $PYTHON $SCRIPT_DIR/main.py --config $CONFIG_FILE --log-level $LOG_LEVEL"
    echo ""

    # 启动机器人
    "$PYTHON" "$SCRIPT_DIR/main.py" --config "$CONFIG_FILE" --log-level "$LOG_LEVEL"
}

# ============================================================
# 主流程
# ============================================================
main() {
    echo ""
    echo -e "${BOLD}${CYAN}========================================${NC}"
    echo -e "${BOLD}${CYAN}  Neutral Grid Bot  —  启动脚本${NC}"
    echo -e "${BOLD}${CYAN}========================================${NC}"

    check_python
    setup_venv
    install_deps
    check_config
    launch_bot
}

main "$@"
