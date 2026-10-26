# Local Companion Bot: 一键关闭
# 关闭顺序：卸载 LLM 模型 → 关闭 AstrBot → 关闭 Mem0 + ChromaDB → 可选关闭 Ollama

$ErrorActionPreference = "SilentlyContinue"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

function Kill-Port {
    param([int]$Port, [string]$Name)
    $procs = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($procs) {
        $procs | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
        Write-Host "  ✓ $Name 已关闭" -ForegroundColor Green
    } else {
        Write-Host "  · $Name 未在运行" -ForegroundColor DarkGray
    }
}

Write-Host "===========================================" -ForegroundColor Cyan
Write-Host "  Local Companion Bot: 关闭" -ForegroundColor Cyan
Write-Host "===========================================" -ForegroundColor Cyan
Write-Host ""

# 1. 让 Ollama 主动卸载模型（不重启服务，模型层 release）
#    枚举 /api/ps 里所有驻留模型并逐个卸载 —— 主对话、提取器、可能还有人格 LoRA 模型
Write-Host "[1/4] 卸载 Ollama 模型..." -ForegroundColor Yellow
try {
    $ps = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/ps" -TimeoutSec 5
    $models = @($ps.models | ForEach-Object { $_.name } | Sort-Object -Unique)
    if ($models.Count -eq 0) {
        Write-Host "  · 没有驻留模型" -ForegroundColor DarkGray
    } else {
        foreach ($m in $models) {
            try {
                $body = @{ model = $m; keep_alive = 0 } | ConvertTo-Json -Compress
                Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/generate" `
                    -Method POST `
                    -ContentType "application/json" `
                    -Body $body `
                    -TimeoutSec 5 | Out-Null
                Write-Host "  ✓ $m 已从显存卸载" -ForegroundColor Green
            } catch {
                Write-Host "  · $m 卸载失败（可能已在卸载中）" -ForegroundColor DarkGray
            }
        }
    }
} catch {
    Write-Host "  · Ollama 未响应，跳过" -ForegroundColor DarkGray
}

# 2. AstrBot
Write-Host "[2/4] 关闭 AstrBot..." -ForegroundColor Yellow
Kill-Port 6185 "AstrBot"

# 3. Mem0 + ChromaDB
Write-Host "[3/4] 关闭 Mem0 / ChromaDB..." -ForegroundColor Yellow
Kill-Port 8888 "Mem0"
Kill-Port 8000 "ChromaDB"

# 4. Ollama 进程（可选）
Write-Host "[4/4] Ollama 进程..." -ForegroundColor Yellow
$ollamaRunning = Get-Process "ollama" -ErrorAction SilentlyContinue
if ($ollamaRunning) {
    $ans = Read-Host "  完全终止 ollama.exe 进程？(y/N)"
    if ($ans -eq "y") {
        Stop-Process -Name "ollama" -Force -ErrorAction SilentlyContinue
        Write-Host "  ✓ Ollama 已关闭" -ForegroundColor Green
    } else {
        Write-Host "  · Ollama 进程保留（仅模型已 unload，~0.3 GB VRAM）" -ForegroundColor DarkGray
    }
} else {
    Write-Host "  · Ollama 未运行" -ForegroundColor DarkGray
}

Write-Host ""
Write-Host "===========================================" -ForegroundColor Cyan
Write-Host "  资源已释放" -ForegroundColor Cyan
Write-Host "===========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "显存现在归你。游戏愉快 🎮" -ForegroundColor Green
Write-Host ""
