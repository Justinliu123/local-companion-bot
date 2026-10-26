# Local Companion Bot: 卸载 Windows 服务
# 需要：管理员权限
# 注意：不会删除项目文件或模型权重

$ErrorActionPreference = "SilentlyContinue"

$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "✗ 需要以管理员权限运行" -ForegroundColor Red
    exit 1
}

$nssm = Get-Command "nssm" -ErrorAction SilentlyContinue
if (-not $nssm) {
    Write-Host "NSSM 未安装，无需卸载服务。" -ForegroundColor Yellow
    exit 0
}

$services = @(
    "LocalCompanionBot-Mem0",
    "LocalCompanionBot-AstrBot"
)

foreach ($svc in $services) {
    $exists = Get-Service $svc -ErrorAction SilentlyContinue
    if ($exists) {
        Write-Host "停止并移除: $svc" -ForegroundColor Cyan
        Stop-Service $svc -Force -ErrorAction SilentlyContinue
        nssm stop $svc | Out-Null
        nssm remove $svc confirm | Out-Null
        Write-Host "  ✓ 已卸载" -ForegroundColor Green
    } else {
        Write-Host "  · $svc 未安装" -ForegroundColor DarkGray
    }
}

Write-Host ""
Write-Host "卸载完成。项目文件未删除。" -ForegroundColor Green
