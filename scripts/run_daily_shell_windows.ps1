param(
    [switch]$CheckOnly
)

$ErrorActionPreference = 'Stop'
$RuntimeRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RuntimeRoot

$DailyUrl = 'http://127.0.0.1:13080'
$RuntimePort = 19103
$RuntimeUrl = "http://127.0.0.1:$RuntimePort"
$RuntimeHealthUrl = "$RuntimeUrl/api/health"
$RuntimeStateRoot = Join-Path $env:LOCALAPPDATA 'UniversalRuntime\WEB_R004\S0_DAILY_ENTRY_R005'
$RuntimePython = Join-Path $RuntimeRoot '.venv\Scripts\python.exe'
$RuntimeOverlay = Join-Path $RuntimeStateRoot 'cumulative_runtime_r001'
$RuntimeStdout = Join-Path $RuntimeStateRoot 'runtime_19103.stdout.log'
$RuntimeStderr = Join-Path $RuntimeStateRoot 'runtime_19103.stderr.log'
$DailyContainers = @(
    'ur-web-r004-daily-mongo-r004',
    'ur-web-r004-daily-adapter-r005',
    'ur-web-r004-daily-ui-r005'
)

function Invoke-NativeCapture {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = & $FilePath @Arguments 2>$null
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previous
    }

    return [pscustomobject]@{
        ExitCode = $exitCode
        Output = @($output)
    }
}

function Test-DockerReady {
    param([Parameter(Mandatory = $true)][string]$DockerPath)
    $probe = Invoke-NativeCapture -FilePath $DockerPath -Arguments @('version', '--format', '{{.Server.Version}}')
    return ($probe.ExitCode -eq 0 -and $probe.Output.Count -gt 0)
}

function Resolve-EdgePath {
    foreach ($registryPath in @(
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe',
        'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe'
    )) {
        if (Test-Path $registryPath) {
            $value = (Get-ItemProperty $registryPath).'(default)'
            if ($value -and (Test-Path -LiteralPath $value)) {
                return $value
            }
        }
    }
    return $null
}

function Test-DailyHttpReady {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $DailyUrl -Method Head -TimeoutSec 3
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400)
    }
    catch {
        return $false
    }
}

function Test-RuntimeReady {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $RuntimeHealthUrl -Method Get -TimeoutSec 3
        return ($response.StatusCode -eq 200 -and $response.Content -match '"status"\s*:\s*"ok"')
    }
    catch {
        return $false
    }
}

function Test-TcpPortListening {
    param([Parameter(Mandatory = $true)][int]$Port)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $iar = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        if (-not $iar.AsyncWaitHandle.WaitOne(500)) {
            return $false
        }
        $client.EndConnect($iar)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $client.Close()
    }
}

function Get-DailyEdgeWindow {
    if (-not ('DailyEdgeWindowNativeR001' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text;

public sealed class DailyEdgeWindowInfoR001 {
    public IntPtr Handle { get; set; }
    public int ProcessId { get; set; }
    public string Title { get; set; }
}

public static class DailyEdgeWindowNativeR001 {
    private delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern bool EnumWindows(EnumWindowsProc callback, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern bool IsWindowVisible(IntPtr hWnd);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int maxCount);

    [DllImport("user32.dll")]
    private static extern int GetWindowTextLength(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);

    [DllImport("user32.dll")]
    private static extern bool ShowWindowAsync(IntPtr hWnd, int command);

    [DllImport("user32.dll")]
    private static extern bool SetForegroundWindow(IntPtr hWnd);

    private static bool IsDailyTitle(string title) {
        if (String.IsNullOrWhiteSpace(title)) {
            return false;
        }
        return title.Equals("Universal Runtime", StringComparison.OrdinalIgnoreCase)
            || title.StartsWith("Universal Runtime -", StringComparison.OrdinalIgnoreCase)
            || title.Equals("LibreChat", StringComparison.OrdinalIgnoreCase)
            || title.StartsWith("LibreChat -", StringComparison.OrdinalIgnoreCase);
    }

    public static DailyEdgeWindowInfoR001[] FindDailyWindows() {
        var rows = new List<DailyEdgeWindowInfoR001>();
        EnumWindows((hWnd, lParam) => {
            if (!IsWindowVisible(hWnd)) {
                return true;
            }

            int length = GetWindowTextLength(hWnd);
            if (length <= 0) {
                return true;
            }

            var title = new StringBuilder(length + 1);
            GetWindowText(hWnd, title, title.Capacity);
            string text = title.ToString();
            if (!IsDailyTitle(text)) {
                return true;
            }

            uint processId;
            GetWindowThreadProcessId(hWnd, out processId);
            try {
                using (var process = Process.GetProcessById((int)processId)) {
                    if (!process.ProcessName.Equals("msedge", StringComparison.OrdinalIgnoreCase)) {
                        return true;
                    }
                }
            }
            catch {
                return true;
            }

            rows.Add(new DailyEdgeWindowInfoR001 {
                Handle = hWnd,
                ProcessId = (int)processId,
                Title = text,
            });
            return true;
        }, IntPtr.Zero);
        return rows.ToArray();
    }

    public static void Activate(IntPtr hWnd) {
        const int SW_RESTORE = 9;
        ShowWindowAsync(hWnd, SW_RESTORE);
        SetForegroundWindow(hWnd);
    }
}
'@
    }

    return @([DailyEdgeWindowNativeR001]::FindDailyWindows())
}

function Try-ActivateExistingDailyWindow {
    try {
        $window = Get-DailyEdgeWindow | Select-Object -First 1
        if (-not $window) {
            return $false
        }
        [DailyEdgeWindowNativeR001]::Activate($window.Handle)
        return $true
    }
    catch {}
    return $false
}

$RepairScript = Join-Path $PSScriptRoot 'first_run_or_repair_windows.ps1'
if (-not (Test-Path -LiteralPath $RepairScript)) {
    throw 'S0_DAILY_REPAIR_HELPER_NOT_FOUND'
}
$PowerShellExe = Join-Path $PSHOME 'powershell.exe'
if (-not (Test-Path -LiteralPath $PowerShellExe)) {
    throw 'S0_DAILY_POWERSHELL_NOT_FOUND'
}

if ($CheckOnly) {
    $checkRaw = & $PowerShellExe -NoProfile -ExecutionPolicy Bypass -File $RepairScript -CheckOnly -Json
    $checkCode = $LASTEXITCODE
    $checkRaw
    exit $checkCode
}

try {
    $repairRaw = & $PowerShellExe -NoProfile -ExecutionPolicy Bypass -File $RepairScript -EnsureReady -Json
    $repairCode = $LASTEXITCODE
    $repair = $repairRaw | ConvertFrom-Json
    if ($repairCode -ne 0 -or $repair.overall_state -ne 'READY') {
        & $PowerShellExe -NoProfile -ExecutionPolicy Bypass -File $RepairScript -ShowUi | Out-Null
        throw "S0_DAILY_PREREQUISITES_NOT_READY:$($repair.overall_state)"
    }

    $dockerPath = [string]$repair.state.docker_cli
    if (-not $dockerPath -or -not (Test-Path -LiteralPath $dockerPath)) {
        throw 'S0_DAILY_DOCKER_CLI_CURRENTNESS_FAILED'
    }
    $dockerDesktopPath = [string]$repair.state.docker_desktop_exe
    $edgePath = [string]$repair.state.edge_path
    if (-not $edgePath -or -not (Test-Path -LiteralPath $edgePath)) {
        throw 'S0_DAILY_EDGE_CURRENTNESS_FAILED'
    }

$containerStates = @()
foreach ($container in $DailyContainers) {
    $probe = Invoke-NativeCapture -FilePath $dockerPath -Arguments @('inspect', '--format', '{{.State.Status}}', $container)
    $containerStates += [pscustomobject]@{
        Name = $container
        Exists = ($probe.ExitCode -eq 0)
        State = if ($probe.ExitCode -eq 0 -and $probe.Output.Count -gt 0) { [string]$probe.Output[0] } else { $null }
    }
}

if ($containerStates.Where({ -not $_.Exists }).Count -gt 0) {
    $missing = ($containerStates.Where({ -not $_.Exists }).Name -join ', ')
    throw "S0_DAILY_STACK_NOT_INSTALLED: $missing"
}

if (-not (Test-DockerReady -DockerPath $dockerPath)) {
    $desktopStart = Invoke-NativeCapture -FilePath $dockerPath -Arguments @('desktop', 'start', '--detach', '--timeout', '120')
    if ($desktopStart.ExitCode -ne 0 -and $dockerDesktopPath -and (Test-Path -LiteralPath $dockerDesktopPath)) {
        Start-Process -FilePath $dockerDesktopPath | Out-Null
    }
    $deadline = (Get-Date).AddSeconds(120)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
        if (Test-DockerReady -DockerPath $dockerPath) {
            break
        }
    }
    if (-not (Test-DockerReady -DockerPath $dockerPath)) {
        throw 'S0_DAILY_DOCKER_ENGINE_START_TIMEOUT'
    }
}

if (-not (Test-Path -LiteralPath $RuntimePython) -or -not (Test-Path -LiteralPath (Join-Path $RuntimeOverlay 'universal_runtime\webapp.py'))) {
    throw 'S0_DAILY_RUNTIME_EXE_NOT_FOUND'
}
if (-not (Test-RuntimeReady)) {
    if (Test-TcpPortListening -Port $RuntimePort) {
        throw 'S0_DAILY_RUNTIME_PORT_19103_OCCUPIED_BUT_HEALTH_FAILED'
    }
    New-Item -ItemType Directory -Force -Path $RuntimeStateRoot | Out-Null
    $env:PYTHONPATH = "$RuntimeOverlay;$RuntimeRoot\src"
    $env:UNIVERSAL_RUNTIME_ARTIFACT_ROOT = Join-Path $RuntimeRoot 'artifacts'
    $env:UNIVERSAL_RUNTIME_PACK_AUTHORITY_ROOT = $RuntimeRoot
    $env:UNIVERSAL_RUNTIME_FASTEMBED_SIDECAR_ROOT = Join-Path $RuntimeRoot '.sidecars\fastembed_0_8_0_multilingual_minilm_r001'
    Start-Process -FilePath $RuntimePython `
        -ArgumentList @('-m','universal_runtime.cli','web','--host','127.0.0.1','--port',[string]$RuntimePort) `
        -WorkingDirectory $RuntimeRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $RuntimeStdout `
        -RedirectStandardError $RuntimeStderr | Out-Null
    $runtimeDeadline = (Get-Date).AddSeconds(90)
    while ((Get-Date) -lt $runtimeDeadline) {
        if (Test-RuntimeReady) {
            break
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not (Test-RuntimeReady)) {
        throw 'S0_DAILY_RUNTIME_19093_READY_TIMEOUT'
    }
}

foreach ($container in $DailyContainers) {
    $probe = Invoke-NativeCapture -FilePath $dockerPath -Arguments @('inspect', '--format', '{{.State.Status}}', $container)
    if ($probe.ExitCode -ne 0) {
        throw "S0_DAILY_CONTAINER_CURRENTNESS_FAILED: $container"
    }
    $state = if ($probe.Output.Count -gt 0) { [string]$probe.Output[0] } else { '' }
    if ($state -ne 'running') {
        $start = Invoke-NativeCapture -FilePath $dockerPath -Arguments @('start', $container)
        if ($start.ExitCode -ne 0) {
            throw "S0_DAILY_CONTAINER_START_FAILED: $container"
        }
    }
}

$httpDeadline = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $httpDeadline) {
    if (Test-DailyHttpReady) {
        break
    }
    Start-Sleep -Seconds 2
}
if (-not (Test-DailyHttpReady)) {
    throw 'S0_DAILY_HTTP_READY_TIMEOUT'
}

if (Try-ActivateExistingDailyWindow) {
    Write-Host 'S0_DAILY_ENTRY_PASS_EXISTING_WINDOW' -ForegroundColor Green
    Write-Host "URL=$DailyUrl"
    exit 0
}

Start-Process -FilePath $edgePath -ArgumentList @("--app=$DailyUrl", '--new-window', '--start-maximized') | Out-Null

$windowDeadline = (Get-Date).AddSeconds(10)
$libreChatWindow = $null
while ((Get-Date) -lt $windowDeadline) {
    $libreChatWindow = Get-DailyEdgeWindow | Select-Object -First 1
    if ($libreChatWindow) {
        break
    }
    Start-Sleep -Milliseconds 500
}
if (-not $libreChatWindow) {
    throw 'S0_DAILY_EDGE_VISIBLE_WINDOW_NOT_OBSERVED'
}

Write-Host 'S0_DAILY_ENTRY_PASS_VISIBLE_WINDOW' -ForegroundColor Green
Write-Host "WINDOW_TITLE=$($libreChatWindow.Title)"
Write-Host "URL=$DailyUrl"
}
catch {
    $failure = $_.Exception.Message
    try {
        $latestRaw = & $PowerShellExe -NoProfile -ExecutionPolicy Bypass -File $RepairScript -CheckOnly -Json
        $latest = $latestRaw | ConvertFrom-Json
        if ($latest.overall_state -ne 'READY') {
            & $PowerShellExe -NoProfile -ExecutionPolicy Bypass -File $RepairScript -ShowUi | Out-Null
        }
        else {
            Add-Type -AssemblyName System.Windows.Forms
            [void][System.Windows.Forms.MessageBox]::Show(
                "Universal Runtime local services are ready, but the app window could not open.`r`n`r`nTry the desktop icon again. If it keeps happening, share this code:`r`n$failure",
                'Universal Runtime',
                [System.Windows.Forms.MessageBoxButtons]::OK,
                [System.Windows.Forms.MessageBoxIcon]::Warning
            )
        }
    }
    catch {}
    exit 50
}
