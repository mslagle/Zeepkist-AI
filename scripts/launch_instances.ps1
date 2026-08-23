param (
    [int]$Instances = 2,
    [string]$Track = "EZ01",
    [int]$WindowWidth = 960,
    [int]$WindowHeight = 540,
    [int]$StaggerDelay = 10,
    [switch]$RebuildMod = $true
)

$GamePath = "M:\SteamLibrary\steamapps\common\Zeepkist\Zeepkist.exe"
$ModPath = "M:\Code\ZeepkistAi\mod\Zeepkist.Ai"
$AppIdFile = "M:\SteamLibrary\steamapps\common\Zeepkist\steam_appid.txt"

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " Zeepkist AI Multi-Instance Auto-Launcher" -ForegroundColor Cyan
Write-Host " Replicas: $Instances | Track: $Track | Resolution: ${WindowWidth}x${WindowHeight}" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# 1. Terminate any running Zeepkist instances
Write-Host "`n[1/5] Stopping running Zeepkist processes..." -ForegroundColor Yellow
Stop-Process -Name "Zeepkist" -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

# 2. Ensure steam_appid.txt exists
"1440670" | Set-Content -Path $AppIdFile -Encoding ASCII -NoNewline

# 3. Configure Windows Registry for Windowed Mode
Write-Host "`n[2/5] Setting Unity Registry to Windowed Mode (${WindowWidth}x${WindowHeight})..." -ForegroundColor Yellow
$regPath = "HKCU:\Software\Steelpan Interactive\Zeepkist"
if (Test-Path $regPath) {
    Set-ItemProperty -Path $regPath -Name "Screenmanager Fullscreen mode_h3630240806" -Value 3 -ErrorAction SilentlyContinue
    Set-ItemProperty -Path $regPath -Name "Screenmanager Resolution Use Native_h1405027254" -Value 0 -ErrorAction SilentlyContinue
    Set-ItemProperty -Path $regPath -Name "Screenmanager Resolution Width_h182942802" -Value $WindowWidth -ErrorAction SilentlyContinue
    Set-ItemProperty -Path $regPath -Name "Screenmanager Resolution Height_h2627697771" -Value $WindowHeight -ErrorAction SilentlyContinue
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

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32 {
    [DllImport("user32.dll")]
    public static extern bool MoveWindow(IntPtr hWnd, int X, int Y, int nWidth, int nHeight, bool bRepaint);
    [DllImport("user32.dll", CharSet = CharSet.Auto)]
    public static extern bool SetWindowText(IntPtr hWnd, string lpString);
}
"@ -ErrorAction SilentlyContinue

$processes = @()
for ($i = 0; $i -lt $Instances; $i++) {
    $portOffset = $i * 10
    $telemPort = 9090 + $portOffset
    $inPort = 9091 + $portOffset
    $ptsPort = 9092 + $portOffset

    $posX = ($i % 2) * ($WindowWidth + 25) + 40
    $posY = [math]::Floor($i / 2) * ($WindowHeight + 50) + 40

    $launchArgs = "-screen-fullscreen 0 -screen-width $WindowWidth -screen-height $WindowHeight -popupwindow -windowed -winX $posX -winY $posY -winW $WindowWidth -winH $WindowHeight -aiPortOffset $portOffset -autoTrack $Track"

    Write-Host "  -> Launching Instance #$i (Ports: Telem=$telemPort, In=$inPort, Pts=$ptsPort) at Pos ($posX, $posY)" -ForegroundColor Green
    $proc = Start-Process -FilePath $GamePath -ArgumentList $launchArgs -PassThru
    $processes += @{ Process = $proc; Index = $i; X = $posX; Y = $posY; W = $WindowWidth; H = $WindowHeight }
    
    if ($i -lt ($Instances - 1)) {
        Write-Host "     Waiting $StaggerDelay seconds before launching next instance..." -ForegroundColor Cyan -NoNewline
        for ($s = $StaggerDelay; $s -gt 0; $s--) {
            Write-Host "`r     Waiting $StaggerDelay seconds before launching next instance... (${s}s remaining) " -ForegroundColor Cyan -NoNewline
            
            # Snap active windows during the wait period
            foreach ($item in $processes) {
                try {
                    $p = Get-Process -Id $item.Process.Id -ErrorAction SilentlyContinue
                    if ($p -and $p.MainWindowHandle -ne [IntPtr]::Zero) {
                        [Win32]::SetWindowText($p.MainWindowHandle, "Zeepkist #$($item.Index + 1)")
                        [Win32]::MoveWindow($p.MainWindowHandle, $item.X, $item.Y, $item.W, $item.H, $true)
                    }
                } catch { }
            }
            Start-Sleep -Seconds 1
        }
        Write-Host "`r     Waiting $StaggerDelay seconds before launching next instance... Done!             " -ForegroundColor Green
    } else {
        Start-Sleep -Seconds 2
    }
}

# Snap windows to exact positions and rename titles for OBS
Write-Host "`n[5/5] Snapping windows into side-by-side grid & setting window titles..." -ForegroundColor Yellow
for ($step = 0; $step -lt 6; $step++) {
    Start-Sleep -Seconds 1
    foreach ($item in $processes) {
        try {
            $p = Get-Process -Id $item.Process.Id -ErrorAction SilentlyContinue
            if ($p -and $p.MainWindowHandle -ne [IntPtr]::Zero) {
                [Win32]::SetWindowText($p.MainWindowHandle, "Zeepkist #$($item.Index + 1)")
                [Win32]::MoveWindow($p.MainWindowHandle, $item.X, $item.Y, $item.W, $item.H, $true)
            }
        } catch { }
    }
}

Write-Host "`nAll $Instances instances configured in side-by-side windowed mode (${WindowWidth}x${WindowHeight})! Track: '$Track'." -ForegroundColor Cyan
Write-Host "You can now run 'python scripts/python/train.py --instances $Instances' in M:\Code\ZeepkistAi" -ForegroundColor Green
