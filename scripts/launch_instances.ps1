param (
    [int]$Instances = 2,
    [string]$Track = "EZ01",
    [switch]$RebuildMod = $true
)

$GamePath = "M:\SteamLibrary\steamapps\common\Zeepkist\Zeepkist.exe"
$ModPath = "M:\Code\ZeepkistAi\mod\Zeepkist.Ai"
$AppIdFile = "M:\SteamLibrary\steamapps\common\Zeepkist\steam_appid.txt"

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " Zeepkist AI Multi-Instance Auto-Launcher" -ForegroundColor Cyan
Write-Host " Replicas: $Instances | Target Track: $Track" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# 1. Terminate any running Zeepkist instances
Write-Host "`n[1/5] Stopping running Zeepkist processes..." -ForegroundColor Yellow
Stop-Process -Name "Zeepkist" -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

# 2. Ensure steam_appid.txt exists
"1440670" | Set-Content -Path $AppIdFile -Encoding ASCII -NoNewline

# 3. Configure Windows Registry for Windowed Mode
Write-Host "`n[2/5] Setting Unity Registry to Windowed Mode..." -ForegroundColor Yellow
$regPath = "HKCU:\Software\Steelpan Interactive\Zeepkist"
if (Test-Path $regPath) {
    Set-ItemProperty -Path $regPath -Name "Screenmanager Fullscreen mode_h3630240806" -Value 3 -ErrorAction SilentlyContinue
    Set-ItemProperty -Path $regPath -Name "Screenmanager Resolution Use Native_h1405027254" -Value 0 -ErrorAction SilentlyContinue
    Set-ItemProperty -Path $regPath -Name "Screenmanager Resolution Width_h182942802" -Value 640 -ErrorAction SilentlyContinue
    Set-ItemProperty -Path $regPath -Name "Screenmanager Resolution Height_h2627697771" -Value 360 -ErrorAction SilentlyContinue
}

# 4. Rebuild C# Mod if requested
if ($RebuildMod) {
    Write-Host "`n[3/5] Rebuilding C# Mod..." -ForegroundColor Yellow
    Push-Location $ModPath
    dotnet build -c Debug
    Pop-Location
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Mod build failed! Aborting." -ForegroundColor Red
        exit 1
    }
}

# 5. Launch instances with side-by-side positioning
Write-Host "`n[4/5] Launching $Instances game replicas side-by-side..." -ForegroundColor Yellow
$WindowWidth = 640
$WindowHeight = 360

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32 {
    [DllImport("user32.dll")]
    public static extern bool MoveWindow(IntPtr hWnd, int X, int Y, int nWidth, int nHeight, bool bRepaint);
}
"@ -ErrorAction SilentlyContinue

$processes = @()
for ($i = 0; $i -lt $Instances; $i++) {
    $portOffset = $i * 10
    $telemPort = 9090 + $portOffset
    $inPort = 9091 + $portOffset
    $ptsPort = 9092 + $portOffset

    $posX = ($i % 2) * ($WindowWidth + 20) + 40
    $posY = [math]::Floor($i / 2) * ($WindowHeight + 50) + 40

    $launchArgs = "-screen-fullscreen 0 -screen-width $WindowWidth -screen-height $WindowHeight -popupwindow -windowed -winX $posX -winY $posY -winW $WindowWidth -winH $WindowHeight -aiPortOffset $portOffset -autoTrack $Track"

    Write-Host "  -> Launching Instance #$i (Ports: Telem=$telemPort, In=$inPort, Pts=$ptsPort) at Pos ($posX, $posY)" -ForegroundColor Green
    $proc = Start-Process -FilePath $GamePath -ArgumentList $launchArgs -PassThru
    $processes += @{ Process = $proc; X = $posX; Y = $posY; W = $WindowWidth; H = $WindowHeight }
    Start-Sleep -Seconds 3
}

# Snap windows to exact positions
Write-Host "`n[5/5] Snapping windows into side-by-side grid..." -ForegroundColor Yellow
Start-Sleep -Seconds 2
foreach ($item in $processes) {
    try {
        $p = Get-Process -Id $item.Process.Id -ErrorAction SilentlyContinue
        if ($p -and $p.MainWindowHandle -ne [IntPtr]::Zero) {
            [Win32]::MoveWindow($p.MainWindowHandle, $item.X, $item.Y, $item.W, $item.H, $true)
        }
    } catch { }
}

Write-Host "`nAll $Instances instances launched in side-by-side windowed mode! Auto-track: '$Track'." -ForegroundColor Cyan
Write-Host "You can now run 'python train.py --instances $Instances' in M:\Code\ZeepkistAi\scripts" -ForegroundColor Green
