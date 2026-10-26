# Local Companion Bot: 注册为 Windows 服务
# 需要：管理员权限 + 已安装 NSSM (https://nssm.cc/)
# 注册后：AstrBot / Mem0 跟随系统启动，崩溃 5 秒自动恢复

$ErrorActionPreference = "Stop"

# 检查管理员
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "✗ 需要以管理员权限运行" -ForegroundColor Red
    exit 1
}

# 检查 NSSM
$nssm = Get-Command "nssm" -ErrorAction SilentlyContinue
if (-not $nssm) {
    Write-Host "✗ 未找到 NSSM。安装方法：" -ForegroundColor Red
    Write-Host "  winget install NSSM.NSSM" -ForegroundColor Yellow
    exit 1
}

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogsDir = Join-Path $ProjectRoot "logs"
New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null

function Register-Service {
    param(
        [string]$ServiceName,
        [string]$DisplayName,
        [string]$Description,
        [string]$Command,
        [string]$Args
    )
    Write-Host "注册服务: $ServiceName ..." -ForegroundColor Cyan
    nssm install $ServiceName $Command $Args | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  ✗ 注册失败" -ForegroundColor Red
        return
    }
    nssm set $ServiceName AppDirectory $ProjectRoot | Out-Null
    nssm set $ServiceName DisplayName $DisplayName | Out-Null
    nssm set $ServiceName Description $Description | Out-Null
    nssm set $ServiceName Start SERVICE_AUTO_START | Out-Null
    nssm set $ServiceName AppRestartDelay 5000 | Out-Null
    nssm set $ServiceName AppStdout (Join-Path $LogsDir "$ServiceName.out.log") | Out-Null
    nssm set $ServiceName AppStderr (Join-Path $LogsDir "$ServiceName.err.log") | Out-Null
    nssm set $ServiceName AppRotateFiles 1 | Out-Null
    nssm set $ServiceName AppRotateBytes 10485760 | Out-Null
    Write-Host "  ✓ 已注册" -ForegroundColor Green
}

# Ollama 通常已经作为自己的服务安装，这里跳过
Write-Host "Ollama 通常自带服务，跳过注册。"
Write-Host ""

# Mem0
$mem0Path = Join-Path $ProjectRoot "mem0\server.py"
if (Test-Path $mem0Path) {
    Register-Service `
        -ServiceName "LocalCompanionBot-Mem0" `
        -DisplayName "Local Companion Bot - Mem0 API" `
        -Description "本地长期记忆引擎，端口 8888" `
        -Command "python" `
        -Args "`"$mem0Path`""
} else {
    Write-Host "⚠ Mem0 server.py 未找到，跳过" -ForegroundColor Yellow
}

# AstrBot
$astrbotPath = Join-Path $ProjectRoot "astrbot\main.py"
if (Test-Path $astrbotPath) {
    Register-Service `
        -ServiceName "LocalCompanionBot-AstrBot" `
        -DisplayName "Local Companion Bot - AstrBot" `
        -Description "陪伴机器人调度中枢，端口 6185" `
        -Command "python" `
        -Args "`"$astrbotPath`""
} else {
    Write-Host "⚠ AstrBot main.py 未找到，跳过" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "===========================================" -ForegroundColor Cyan
Write-Host "  服务注册完成" -ForegroundColor Cyan
Write-Host "===========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "立即启动（不重启）：Start-Service LocalCompanionBot-AstrBot" -ForegroundColor DarkGray
Write-Host "查看状态：Get-Service LocalCompanionBot-*" -ForegroundColor DarkGray
Write-Host "卸载：.\scripts\uninstall-windows-service.ps1" -ForegroundColor DarkGray
