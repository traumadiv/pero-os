# Pero OS: build the ISO from Windows via WSL2 Debian.
#   powershell -ExecutionPolicy Bypass -File .\build.ps1
#   powershell -ExecutionPolicy Bypass -File .\build.ps1 clean

param([string]$Action = "")

$ErrorActionPreference = "Stop"
$distro = "Debian"

if (-not ((wsl.exe -l -q) -replace "`0", "" | Where-Object { $_.Trim() -eq $distro })) {
    Write-Host ">>> Устанавливаю $distro в WSL2 (один раз)..."
    wsl.exe --install -d $distro --no-launch
}

# C:\path\to\pero-os -> /mnt/c/path/to/pero-os
$src = (Resolve-Path $PSScriptRoot).Path
$wslPath = "/mnt/" + $src.Substring(0, 1).ToLower() + ($src.Substring(2) -replace "\\", "/")

Write-Host ">>> Сборка в WSL ($distro), это 20-60 минут при первом запуске"
wsl.exe -d $distro -u root -- bash -c "sed 's/\r$//' '$wslPath/build.sh' > /root/pero-build.sh && PERO_SRC='$wslPath' bash /root/pero-build.sh $Action; cp /var/tmp/pero-build/build.log '$wslPath/out/' 2>/dev/null; exit 0"

Get-ChildItem "$src\out\*.iso" -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host ">>> ISO: $($_.FullName)  ($([math]::Round($_.Length / 1GB, 2)) GB)"
}
