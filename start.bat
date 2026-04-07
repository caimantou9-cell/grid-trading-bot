@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

:: ============================================================
:: Neutral Grid Bot — Windows 启动脚本
:: ============================================================
:: 第一次运行请双击运行此脚本，或在终端中执行: start.bat
::
:: 使用方法:
::   start.bat                    # 交互式菜单
::   start.bat extendedx          # 使用 ExtendedX 交易所
::   start.bat lighter            # 使用 Lighter 交易所
::   start.bat extendedx debug     # 以 DEBUG 模式启动
::   start.bat lighter info       # 以 INFO 模式启动
::
:: 如果是第一次运行，此脚本会自动：
::   1. 检查并安装 Python 3.10+（如未安装）
::   2. 创建 Python 虚拟环境
::   3. 安装所有依赖
::   4. 复制 config.json.example → config.json（如 config.json 不存在）
::   5. 提示你编辑配置文件
:: ============================================================

set "SCRIPT_DIR=%~dp0"
set "VENV_DIR=%SCRIPT_DIR%.venv"
set "CONFIG_FILE=%SCRIPT_DIR%config.json"
set "CONFIG_EXAMPLE=%SCRIPT_DIR%config.json.example"
set "REQUIREMENTS=%SCRIPT_DIR%requirements.txt"
set "PYTHON_CMD="

:: 检测命令行参数
set "MODE="
set "LOG_LEVEL="
for %%a in (%*) do (
    if /i "%%a"=="extendedx" set "MODE=extendedx"
    if /i "%%a"=="lighter"    set "MODE=lighter"
    if /i "%%a"=="debug"     set "LOG_LEVEL=DEBUG"
    if /i "%%a"=="info"      set "LOG_LEVEL=INFO"
    if /i "%%a"=="warning"   set "LOG_LEVEL=WARNING"
)

:: 颜色定义
set "ESC="
for /f tokens^=2delims^=^" %%A in ('"prompt $H"') do set "BS=%%A"
call :Print "" 2>nul || set "ESC="
set "C_RESET=  "
set "C_GREEN=  "
set "C_YELLOW=  "
set "C_RED=  "
set "C_CYAN=  "
set "C_BOLD=  "

:: ============================================================
:: 步骤 1: 检测 Python
:: ============================================================
:check_python
echo.
call :PrintC "C_CYAN" "========================================"
call :PrintC "C_CYAN" "  Neutral Grid Bot  —  启动脚本"
call :PrintC "C_CYAN" "========================================"
echo.
call :PrintC "C_YELLOW" "[1/5] 检查 Python..."

:: 尝试从虚拟环境获取 Python
if exist "%VENV_DIR%\Scripts\python.exe" (
    set "PYTHON_CMD=%VENV_DIR%\Scripts\python.exe"
    for /f "delims=" %%v in ('"%PYTHON_CMD%" --version 2^>^&1') do set "PYTHON_VERSION=%%v"
    call :PrintC "C_GREEN" "  发现虚拟环境 Python: %PYTHON_VERSION%"
    goto :check_venv
)

:: 尝试系统 Python
where python >nul 2>&1
if %errorlevel%==0 (
    for /f "delims=" %%v in ('python --version 2^>^&1') do set "PYTHON_VERSION=%%v"
    call :PrintC "C_GREEN" "  发现系统 Python: %PYTHON_VERSION%"
    set "PYTHON_CMD=python"
) else (
    where python3 >nul 2>&1
    if !errorlevel!==0 (
        for /f "delims=" %%v in ('python3 --version 2^>^&1') do set "PYTHON_VERSION=%%v"
        call :PrintC "C_GREEN" "  发现系统 Python3: !PYTHON_VERSION!"
        set "PYTHON_CMD=python3"
    )
)

if !PYTHON_CMD!=="" (
    call :PrintC "C_RED" ""
    call :PrintC "C_RED" "  [错误] 未找到 Python！"
    call :PrintC "C_RED" ""
    call :PrintC "C_YELLOW" "  请先安装 Python 3.10 或更高版本："
    call :PrintC "C_YELLOW" "  https://www.python.org/downloads/"
    echo.
    call :PrintC "C_CYAN" "  安装后请重新运行此脚本。"
    echo.
    pause
    exit /b 1
)

:: 检查版本
for /f "tokens=2" %%v in ('!PYTHON_CMD! --version 2^>^&1') do set "PYTHON_VERSION=%%v"
echo !PYTHON_VERSION! | findstr /R "^Python\ 3\.[0-9]" >nul
if %errorlevel% neq 0 (
    call :PrintC "C_RED" "  [错误] Python 版本过低，需要 3.10+"
    pause
    exit /b 1
)

:: ============================================================
:: 步骤 2: 创建虚拟环境
:: ============================================================
:check_venv
echo.
call :PrintC "C_YELLOW" "[2/5] 设置 Python 虚拟环境..."

if not exist "%VENV_DIR%" (
    call :PrintC "C_YELLOW" "  创建虚拟环境..."
    !PYTHON_CMD! -m venv "%VENV_DIR%"
    if %errorlevel% neq 0 (
        call :PrintC "C_RED" "  [错误] 虚拟环境创建失败"
        pause
        exit /b 1
    )
    call :PrintC "C_GREEN" "  虚拟环境创建成功"
) else (
    call :PrintC "C_GREEN" "  虚拟环境已存在，跳过"
)

set "PIP_CMD=%VENV_DIR%\Scripts\pip.exe"
set "PYTHON=%VENV_DIR%\Scripts\python.exe"

:: ============================================================
:: 步骤 3: 安装依赖
:: ============================================================
:install_deps
echo.
call :PrintC "C_YELLOW" "[3/5] 安装 Python 依赖..."

if not exist "%REQUIREMENTS%" (
    call :PrintC "C_RED" "  [错误] requirements.txt 未找到"
    pause
    exit /b 1
)

"%PIP_CMD%" install --upgrade pip >nul 2>&1
"%PIP_CMD%" install -r "%REQUIREMENTS%" >nul 2>&1
if %errorlevel% neq 0 (
    call :PrintC "C_RED" "  [错误] 依赖安装失败，请查看上方错误信息"
    pause
    exit /b 1
)
call :PrintC "C_GREEN" "  基础依赖安装成功 (pydantic)"

:: ============================================================
:: 步骤 4: 安装交易所 SDK
:: ============================================================
:install_exchange_sdk
echo.
call :PrintC "C_YELLOW" "[4/5] 安装交易所 SDK..."

:: ExtendedX SDK
if exist "%SCRIPT_DIR%exchanges\extendedx.py" (
    call :PrintC "C_CYAN" "  ExtendedX 适配器已找到"

    :: 检查 x10 SDK 是否已安装
    "%PYTHON%" -c "import x10" 2>nul
    if %errorlevel% neq 0 (
        call :PrintC "C_YELLOW" "  x10-python-trading-starknet 未安装"
        echo   请选择:
        echo   [1] 使用 pip 安装（需先从 GitHub 下载 x10-python-trading-starknet）
        echo   [2] 跳过，稍后手动安装
        echo   [3] 继续启动（如果其他 SDK 已可用）
        set /p SDK_CHOICE="  请输入选择 [3]: "
        if "!SDK_CHOICE!"=="1" (
            call :PrintC "C_YELLOW" "  请运行: pip install x10-python-trading-starknet"
            call :PrintC "C_YELLOW" "  或从 https://github.com/extended-exchange/x10-python-trading-starknet 下载后运行:"
            call :PrintC "C_YELLOW" "    pip install /path/to/extended-pythonsdk"
        )
    ) else (
        call :PrintC "C_GREEN" "  x10-python-trading-starknet 已安装"
    )
)

:: Lighter SDK (aiohttp 已在 requirements 中)
if exist "%SCRIPT_DIR%exchanges\lighter.py" (
    call :PrintC "C_CYAN" "  Lighter 适配器已找到"
    "%PYTHON%" -c "import lighter" 2>nul
    if %errorlevel% neq 0 (
        call :PrintC "C_YELLOW" "  lighter-sdk 未安装"
        call :PrintC "C_YELLOW" "  请运行:"
        call :PrintC "C_YELLOW" "    git clone https://github.com/lighter-exchange/lighter-v2-api C:\lighter-sdk"
        call :PrintC "C_YELLOW" "  然后重新运行此脚本"
    ) else (
        call :PrintC "C_GREEN" "  lighter-sdk 已安装"
    )
)

:: ============================================================
:: 步骤 5: 检查/引导配置
:: ============================================================
:check_config
echo.
call :PrintC "C_YELLOW" "[5/5] 检查配置文件..."

if not exist "%CONFIG_FILE%" (
    if not exist "%CONFIG_EXAMPLE%" (
        call :PrintC "C_RED" "  [错误] config.json.example 也未找到！"
        pause
        exit /b 1
    )
    call :PrintC "C_YELLOW" "  未找到 config.json，正在从示例创建..."
    copy "%CONFIG_EXAMPLE%" "%CONFIG_FILE%" >nul
    if %errorlevel%==0 (
        call :PrintC "C_GREEN" "  已创建 config.json"
    ) else (
        call :PrintC "C_RED" "  [错误] 创建 config.json 失败"
        pause
        exit /b 1
    )
    echo.
    call :PrintC "C_RED" "  ==========================================="
    call :PrintC "C_RED" "  请先编辑 config.json 填写交易所凭证！"
    call :PrintC "C_RED" "  ==========================================="
    echo.
    echo   文件位置: %CONFIG_FILE%
    echo.
    echo   必填项:
    echo     - exchange.adapter    ^<- 交易所适配器路径
    echo     - exchange.api_key    ^<- API 密钥
    echo     - exchange.api_secret ^<- API 密钥
    echo     - strategy.symbol     ^<- 交易对
    echo     - strategy.lower_price ^<- 价格下限
    echo     - strategy.upper_price ^<- 价格上限
    echo     - strategy.grid_count  ^<- 网格数量
    echo.
    set /p OPEN_EDITOR="  是否现在用记事本打开 config.json？(Y/N): "
    if /i "!OPEN_EDITOR!"=="Y" (
        start notepad "%CONFIG_FILE%"
    )
    echo.
    call :PrintC "C_YELLOW" "  编辑完成后重新运行此脚本启动机器人"
    echo.
    pause
    exit /b 0
)

call :PrintC "C_GREEN" "  config.json 已就绪"

:: ============================================================
:: 步骤 6: 启动机器人
:: ============================================================
:launch_bot
echo.
call :PrintC "C_GREEN" "========================================"
call :PrintC "C_GREEN" "  启动网格机器人..."
call :PrintC "C_GREEN" "========================================"
echo.
call :PrintC "C_CYAN" "  配置文件: %CONFIG_FILE%"
if defined LOG_LEVEL (
    call :PrintC "C_CYAN" "  日志级别: %LOG_LEVEL%"
) else (
    call :PrintC "C_CYAN" "  日志级别: INFO (从 config.json 读取)"
)
echo.

:: 构造启动命令
set "BOT_CMD=%PYTHON% "%SCRIPT_DIR%main.py" --config "%CONFIG_FILE%""
if defined LOG_LEVEL (
    set "BOT_CMD=!BOT_CMD! --log-level %LOG_LEVEL%"
)

:: 设置 PYTHONPATH（确保 exchange SDK 可被找到）
set "PYTHONPATH=%SCRIPT_DIR%;%PYTHONPATH%"

:: 直接执行，不使用 cmd /c 来保留虚拟环境变量
!BOT_CMD!
exit /b %errorlevel%

:: ============================================================
:: 辅助函数
:: ============================================================
:PrintC
setlocal
set "col=%~1"
set "text=%~2"
endlocal & (
    if defined ESC (
        <nul set /p "str=%ESC%[%colCode%m%text%%ESC%[0m"
    ) else (
        echo %text%
    )
)
goto :eof

:Print
( %~1 ) 2>nul
goto :eof

endlocal
