# stage('Local Companion Bot: 一键启动')
# 启动顺序：Ollama → ChromaDB → Mem0 → AstrBot
# Windows 11 / PowerShell 5.1+
# 需以普通用户权限运行；如需注册为服务，使用 install-windows-service.ps1

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

function Test-Port {
    param([int]$Port)
    return $null -ne (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Wait-Port {
    param([int]$Port, [int]$TimeoutSec = 30)
    Write-Host "    等待端口 $Port 启动..." -NoNewline
    $elapsed = 0
    while (-not (Test-Port $Port)) {
        Start-Sleep -Seconds 1
        $elapsed++
        if ($elapsed -ge $TimeoutSec) {
            Write-Host " 超时" -ForegroundColor Red
            return $false
        }
    }
    Write-Host " 就绪" -ForegroundColor Green
    return $true
}

Write-Host "===========================================" -ForegroundColor Cyan
Write-Host "  Local Companion Bot: 启动" -ForegroundColor Cyan
Write-Host "===========================================" -ForegroundColor Cyan
Write-Host ""

# 1. Ollama
Write-Host "[1/4] Ollama (端口 11434)..." -ForegroundColor Yellow

# 1a. 加载 Ollama 环境变量（必须在 ollama serve 之前生效）
$ollamaEnvFile = Join-Path $ProjectRoot "config\ollama.env"
if (Test-Path $ollamaEnvFile) {
    Get-Content $ollamaEnvFile | ForEach-Object {
        if ($_ -match '^([A-Z_][A-Z0-9_]*)=(.*)$') {
            [Environment]::SetEnvironmentVariable($matches[1], $matches[2], "Process")
        }
    }
    Write-Host "  ✓ 已加载 config\ollama.env" -ForegroundColor Green
} else {
    Write-Host "  · 未找到 config\ollama.env，使用系统环境变量" -ForegroundColor DarkGray
}

if (Test-Port 11434) {
    Write-Host "  · Ollama 已在运行" -ForegroundColor DarkGray
    Write-Host "    ⚠ 已在运行的 Ollama 不会读取刚设置的环境变量。" -ForegroundColor Yellow
    Write-Host "      若要应用 KV_CACHE_TYPE / FLASH_ATTENTION，请先运行 stop-companion.ps1 完全退出。" -ForegroundColor Yellow
} else {
    Start-Process "ollama" "serve" -WindowStyle Hidden
    if (Wait-Port 11434) {
        Write-Host "  ✓ Ollama 已启动" -ForegroundColor Green
    } else {
        Write-Host "  ✗ Ollama 启动失败，请检查显卡驱动 / 端口占用" -ForegroundColor Red
        exit 1
    }
}

# 2. ChromaDB
Write-Host "[2/4] ChromaDB (端口 8000)..." -ForegroundColor Yellow
if (Test-Port 8000) {
    Write-Host "  · ChromaDB 已在运行" -ForegroundColor DarkGray
} else {
    Start-Process "python" "-m chromadb.cli.run_server --host 127.0.0.1 --port 8000" -WindowStyle Hidden
    if (Wait-Port 8000) {
        Write-Host "  ✓ ChromaDB 已启动" -ForegroundColor Green
    } else {
        Write-Host "  ✗ ChromaDB 启动失败，请检查 Python / chromadb 是否安装" -ForegroundColor Red
    }
}

# 3. Mem0
Write-Host "[3/4] Mem0 (端口 8888)..." -ForegroundColor Yellow
if (Test-Port 8888) {
    Write-Host "  · Mem0 已在运行" -ForegroundColor DarkGray
} else {
    $mem0Path = Join-Path $ProjectRoot "mem0\server.py"
    if (Test-Path $mem0Path) {
        # 加载 .env 到当前进程
        $envFile = Join-Path $ProjectRoot "config\mem0.env"
        if (Test-Path $envFile) {
            Get-Content $envFile | ForEach-Object {
                if ($_ -match '^([A-Z_][A-Z0-9_]*)=(.*)$') {
                    [Environment]::SetEnvironmentVariable($matches[1], $matches[2], "Process")
                }
            }
        }
        Start-Process "python" $mem0Path -WindowStyle Hidden
        if (Wait-Port 8888 -TimeoutSec 30) {
            Write-Host "  ✓ Mem0 已启动" -ForegroundColor Green
        } else {
            Write-Host "  ✗ Mem0 启动失败，请检查日志" -ForegroundColor Red
        }
    } else {
        Write-Host "  ⚠ mem0/server.py 未找到，请先部署 Mem0 服务代码" -ForegroundColor Red
    }
}

# 4. AstrBot
Write-Host "[4/4] AstrBot (端口 6185)..." -ForegroundColor Yellow
if (Test-Port 6185) {
    Write-Host "  · AstrBot 已在运行" -ForegroundColor DarkGray
} else {
    $astrbotPath = Join-Path $ProjectRoot "astrbot\main.py"
    if (Test-Path $astrbotPath) {
        Start-Process "python" $astrbotPath -WindowStyle Hidden
        if (Wait-Port 6185) {
            Write-Host "  ✓ AstrBot 已启动" -ForegroundColor Green
        } else {
            Write-Host "  ✗ AstrBot 启动失败" -ForegroundColor Red
        }
    } else {
        Write-Host "  ⚠ astrbot/main.py 未找到，请先部署 AstrBot 主程序" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "===========================================" -ForegroundColor Cyan
Write-Host "  启动完成" -ForegroundColor Cyan
Write-Host "===========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "AstrBot WebUI: http://127.0.0.1:6185" -ForegroundColor Cyan
Write-Host ""
Write-Host "可用命令：" -ForegroundColor DarkGray
Write-Host "  .\scripts\stop-companion.ps1   关闭全部并释放显存" -ForegroundColor DarkGray
Write-Host "  nvidia-smi                     查看当前显存占用" -ForegroundColor DarkGray
Write-Host ""
