# 明镜·部署数据导出（Windows 本机运行）：MySQL dump + Chroma 打包
# 用法：powershell -ExecutionPolicy Bypass -File deploy\export-data.ps1
# 产物在 dist-export/ 目录：
#   mingjing.sql       （约 51MB，导入云端 MySQL 容器）
#   chroma.tar.gz      （约几百 MB，解压到云端 ./data/chroma）
# 之后把两个文件通过 OSS 控制台/ossutil 上传，云端下载使用（见《云端部署手册》）。

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# 读取 .env 的 MySQL 配置（本地开发库）
$envMap = @{}
Get-Content ".env" | Where-Object { $_ -match "=" -and $_ -notmatch "^#" } | ForEach-Object {
    $k, $v = $_ -split "=", 2
    $envMap[$k.Trim()] = $v.Trim()
}

New-Item -ItemType Directory -Force -Path "dist-export" | Out-Null

Write-Host "[1/2] 导出 MySQL（$($envMap['MySQL_DATABASE'])）..."
& mysqldump -h $envMap["MySQL_HOST"] -P $envMap["MySQL_PORT"] -u $envMap["MySQL_USER"] `
    "-p$($envMap['MySQL_PASSWORD'])" --single-transaction --routines --default-character-set=utf8mb4 `
    $envMap["MySQL_DATABASE"] | Out-File -Encoding utf8 "dist-export/mingjing.sql"
Write-Host "      -> dist-export/mingjing.sql"

Write-Host "[2/2] 打包 Chroma 向量库（勿云端重灌，embedding 按量计费）..."
tar -czf "dist-export/chroma.tar.gz" -C $root Chromadb
Write-Host "      -> dist-export/chroma.tar.gz"

Write-Host ""
Write-Host "完成。下一步：把这两个文件通过 OSS 控制台上传到 mingjing-01 的 deploy/ 目录，"
Write-Host "然后在云服务器上按《云端部署手册》第 4 步下载恢复。"
