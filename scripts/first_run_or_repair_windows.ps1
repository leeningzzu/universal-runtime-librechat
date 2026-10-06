param(
    [switch]$CheckOnly,
    [switch]$EnsureReady,
    [switch]$ShowUi,
    [switch]$Json,
    [ValidateSet('AUTO','en','zh-Hans')]
    [string]$Language = 'AUTO',
    [ValidateSet('NONE','READY','DOCKER_STOPPED','RUNTIME_STOPPED','CONTAINERS_STOPPED','DOCKER_MISSING','EDGE_MISSING','WSL_MISSING','RUNTIME_MISSING','STACK_MISSING','PORT_CONFLICT')]
    [string]$SimulateScenario = 'NONE'
)

$ErrorActionPreference = 'Stop'

$CandidateRoot = Split-Path -Parent $PSScriptRoot
if ((Split-Path -Leaf $CandidateRoot) -eq 'candidate') {
    $RuntimeRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
    $ConfigRoot = $CandidateRoot
}
else {
    $RuntimeRoot = Split-Path -Parent $PSScriptRoot
    $ConfigRoot = $RuntimeRoot
}

$ManifestPath = Join-Path $ConfigRoot 'config\windows_prerequisites.json'
$Manifest = Get-Content -Raw -LiteralPath $ManifestPath | ConvertFrom-Json
$StringsPath = Join-Path $ConfigRoot 'config\shell_strings.json'
$Strings = Get-Content -Raw -Encoding UTF8 -LiteralPath $StringsPath | ConvertFrom-Json
$DailyUrl = 'http://127.0.0.1:13080'
$RuntimePort = 19103
$RuntimeHealthUrl = "http://127.0.0.1:$RuntimePort/api/health"
$RuntimeStateRoot = Join-Path $env:LOCALAPPDATA 'UniversalRuntime\WEB_R004\S0_DAILY_ENTRY_R005'
$RuntimePython = Join-Path $RuntimeRoot '.venv\Scripts\python.exe'
$RuntimeOverlay = Join-Path $RuntimeStateRoot 'cumulative_runtime_r001'
$DailyContainers = @('ur-web-r004-daily-mongo-r004','ur-web-r004-daily-adapter-r005','ur-web-r004-daily-ui-r005')

function Resolve-UiLanguage {
    if ($Language -ne 'AUTO') { return $Language }
    $tag = $null
    try {
        $first = @(Get-WinUserLanguageList | Select-Object -First 1)
        if ($first.Count -gt 0) { $tag = [string]$first[0].LanguageTag }
    }
    catch {}
    if (-not $tag) {
        try { $tag = [string](Get-Culture).Name } catch { $tag = 'en' }
    }
    if ($tag -match '^zh') { return 'zh-Hans' }
    return 'en'
}

$UiLanguage = Resolve-UiLanguage
$UiStrings = $Strings.PSObject.Properties[$UiLanguage].Value
if (-not $UiStrings) { $UiLanguage = 'en'; $UiStrings = $Strings.en }

function T {
    param([string]$Key)
    $property = $UiStrings.PSObject.Properties[$Key]
    if ($property) { return [string]$property.Value }
    return $Key
}

function Invoke-NativeCapture {
    param([string]$FilePath,[string[]]$Arguments)
    $previous = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $output = & $FilePath @Arguments 2>&1
        $exitCode = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previous }
    [pscustomobject]@{ ExitCode = $exitCode; Output = @($output) }
}

function Resolve-EdgePath {
    foreach ($registryPath in @(
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe',
        'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe'
    )) {
        if (Test-Path $registryPath) {
            $value = (Get-ItemProperty $registryPath).'(default)'
            if ($value -and (Test-Path -LiteralPath $value)) { return $value }
        }
    }
    foreach ($path in @(
        (Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'),
        (Join-Path $env:ProgramFiles 'Microsoft\Edge\Application\msedge.exe')
    )) {
        if ($path -and (Test-Path -LiteralPath $path)) { return $path }
    }
    return $null
}

function Resolve-DockerCli {
    $cmd = Get-Command docker.exe -ErrorAction SilentlyContinue
    if ($cmd -and (Test-Path -LiteralPath $cmd.Source)) { return $cmd.Source }
    foreach ($path in @(
        (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'),
        (Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe')
    )) {
        if ($path -and (Test-Path -LiteralPath $path)) { return $path }
    }
    return $null
}

function Resolve-DockerDesktopExe {
    foreach ($path in @(
        (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\frontend\Docker Desktop.exe'),
        (Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe')
    )) {
        if ($path -and (Test-Path -LiteralPath $path)) { return $path }
    }
    return $null
}

function Test-HttpReady {
    param([string]$Url,[switch]$RequireRuntimeShape)
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -Method Get -TimeoutSec 3
        if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 400) { return $false }
        if ($RequireRuntimeShape -and $response.Content -notmatch '"status"\s*:\s*"ok"') { return $false }
        return $true
    }
    catch { return $false }
}

function Test-TcpPortListening {
    param([int]$Port)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $iar = $client.BeginConnect('127.0.0.1', $Port, $null, $null)
        if (-not $iar.AsyncWaitHandle.WaitOne(400)) { return $false }
        $client.EndConnect($iar)
        return $true
    }
    catch { return $false }
    finally { $client.Close() }
}

function Get-OsBuild {
    try { return [int](Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').CurrentBuildNumber }
    catch { return [Environment]::OSVersion.Version.Build }
}

function Test-WslReady {
    $wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
    if (-not $wsl) { return $false }
    $probe = Invoke-NativeCapture -FilePath $wsl.Source -Arguments @('--status')
    return ($probe.ExitCode -eq 0)
}

function Get-DockerDesktopStatus {
    param([string]$DockerCli)
    if (-not $DockerCli) { return 'missing' }
    $probe = Invoke-NativeCapture -FilePath $DockerCli -Arguments @('desktop','status','--format','json')
    if ($probe.ExitCode -eq 0) {
        try {
            $parsed = (($probe.Output -join "`n") | ConvertFrom-Json)
            if ($parsed.Status) { return ([string]$parsed.Status).ToLowerInvariant() }
        }
        catch {}
    }
    $engine = Invoke-NativeCapture -FilePath $DockerCli -Arguments @('version','--format','{{.Server.Version}}')
    if ($engine.ExitCode -eq 0 -and $engine.Output.Count -gt 0) { return 'running' }
    return 'stopped'
}

function Get-ContainerStates {
    param([string]$DockerCli)
    $rows = @()
    foreach ($name in $DailyContainers) {
        if (-not $DockerCli) {
            $rows += [pscustomobject]@{ name=$name; exists=$false; state=$null }
            continue
        }
        $probe = Invoke-NativeCapture -FilePath $DockerCli -Arguments @('inspect','--format','{{.State.Status}}',$name)
        $rows += [pscustomobject]@{
            name = $name
            exists = ($probe.ExitCode -eq 0)
            state = if ($probe.ExitCode -eq 0 -and $probe.Output.Count -gt 0) { [string]$probe.Output[0] } else { $null }
        }
    }
    return @($rows)
}

function New-SimulationState {
    param([string]$Scenario)
    $base = [ordered]@{
        windows = 'ready'; edge = 'ready'; wsl2 = 'ready'; docker_desktop = 'running'
        runtime_bundle = 'ready'; runtime = 'running'; production_stack = 'running'; ports = 'ready'; daily_http = 'ready'
    }
    switch ($Scenario) {
        'DOCKER_STOPPED' { $base.docker_desktop = 'stopped'; $base.production_stack = 'stopped'; $base.daily_http = 'stopped' }
        'RUNTIME_STOPPED' { $base.runtime = 'stopped'; $base.production_stack = 'stopped'; $base.daily_http = 'stopped' }
        'CONTAINERS_STOPPED' { $base.production_stack = 'stopped'; $base.daily_http = 'stopped' }
        'DOCKER_MISSING' { $base.docker_desktop = 'missing'; $base.production_stack = 'missing'; $base.daily_http = 'stopped' }
        'EDGE_MISSING' { $base.edge = 'missing' }
        'WSL_MISSING' { $base.wsl2 = 'missing'; $base.docker_desktop = 'stopped'; $base.production_stack = 'stopped'; $base.daily_http = 'stopped' }
        'RUNTIME_MISSING' { $base.runtime_bundle = 'missing'; $base.runtime = 'missing'; $base.production_stack = 'stopped'; $base.daily_http = 'stopped' }
        'STACK_MISSING' { $base.production_stack = 'missing'; $base.daily_http = 'stopped' }
        'PORT_CONFLICT' { $base.runtime = 'stopped'; $base.ports = 'conflict'; $base.production_stack = 'stopped'; $base.daily_http = 'stopped' }
    }
    return [pscustomobject]$base
}

function Get-ObservedState {
    if ($SimulateScenario -ne 'NONE') { return New-SimulationState -Scenario $SimulateScenario }
    $build = Get-OsBuild
    $edge = Resolve-EdgePath
    $docker = Resolve-DockerCli
    $dockerExe = Resolve-DockerDesktopExe
    $dockerStatus = Get-DockerDesktopStatus -DockerCli $docker
    if (-not $docker -and -not $dockerExe) { $dockerStatus = 'missing' }
    $runtimeBundle = (Test-Path -LiteralPath $RuntimePython) -and (Test-Path -LiteralPath (Join-Path $RuntimeOverlay 'universal_runtime\webapp.py'))
    $runtimeReady = Test-HttpReady -Url $RuntimeHealthUrl -RequireRuntimeShape
    $portConflict = (-not $runtimeReady) -and (Test-TcpPortListening -Port $RuntimePort)
    $wslReady = Test-WslReady
    $containers = @()
    $productionStack = 'blocked_by_prerequisite'
    if ($wslReady -and $dockerStatus -eq 'running') {
        $containers = Get-ContainerStates -DockerCli $docker
        $missingContainers = @($containers | Where-Object { -not $_.exists }).Count
        $stoppedContainers = @($containers | Where-Object { $_.exists -and $_.state -ne 'running' }).Count
        $productionStack = if ($missingContainers -gt 0) { 'missing' } elseif ($stoppedContainers -gt 0) { 'stopped' } else { 'running' }
    }
    [pscustomobject]@{
        windows = if ([Environment]::Is64BitOperatingSystem -and $build -ge 19041) { 'ready' } else { 'unsupported' }
        edge = if ($edge) { 'ready' } else { 'missing' }
        wsl2 = if ($wslReady) { 'ready' } else { 'missing' }
        docker_desktop = $dockerStatus
        runtime_bundle = if ($runtimeBundle) { 'ready' } else { 'missing' }
        runtime = if ($runtimeReady) { 'running' } elseif ($runtimeBundle) { 'stopped' } else { 'missing' }
        production_stack = $productionStack
        ports = if ($portConflict) { 'conflict' } else { 'ready' }
        daily_http = if (Test-HttpReady -Url $DailyUrl) { 'ready' } else { 'stopped' }
        edge_path = $edge
        docker_cli = $docker
        docker_desktop_exe = $dockerExe
        os_build = $build
        containers = $containers
    }
}

function Get-Assessment {
    param($State)
    $blockers = @()
    $auto = @()
    if ($State.windows -ne 'ready') { $blockers += 'WINDOWS_UNSUPPORTED' }
    if ($State.edge -ne 'ready') { $blockers += 'EDGE_INSTALL_REQUIRED' }

    $platformReadyForDocker = ($State.windows -eq 'ready' -and $State.wsl2 -eq 'ready')
    if ($State.wsl2 -ne 'ready') {
        $blockers += 'WSL2_ENABLE_OR_INSTALL_REQUIRED'
    }
    elseif ($State.docker_desktop -eq 'missing') {
        $blockers += 'DOCKER_DESKTOP_INSTALL_REQUIRED'
    }
    elseif ($State.docker_desktop -ne 'running') {
        $auto += 'START_DOCKER_DESKTOP'
    }

    if ($State.runtime_bundle -ne 'ready') { $blockers += 'RUNTIME_BUNDLE_REPAIR_REQUIRED' }
    elseif ($State.runtime -ne 'running' -and $State.ports -ne 'conflict') { $auto += 'START_RUNTIME_19103' }
    if ($State.ports -eq 'conflict') { $blockers += 'PORT_19103_CONFLICT' }

    $dockerReadyForStack = ($platformReadyForDocker -and $State.docker_desktop -eq 'running')
    if ($dockerReadyForStack) {
        if ($State.production_stack -eq 'missing') { $blockers += 'PRODUCT_STACK_REPAIR_REQUIRED' }
        elseif ($State.production_stack -eq 'stopped') { $auto += 'START_PRODUCT_CONTAINERS' }
    }
    if ($State.daily_http -ne 'ready' -and $blockers.Count -eq 0 -and $auto.Count -eq 0) { $auto += 'WAIT_OR_RECHECK_DAILY_HTTP' }

    $overall = 'READY'
    if ($blockers -contains 'WINDOWS_UNSUPPORTED') { $overall = 'UNSUPPORTED' }
    elseif ($blockers.Count -gt 0) {
        if ($blockers | Where-Object { $_ -in @('EDGE_INSTALL_REQUIRED','WSL2_ENABLE_OR_INSTALL_REQUIRED','DOCKER_DESKTOP_INSTALL_REQUIRED','PORT_19103_CONFLICT') }) {
            $overall = 'USER_ACTION_REQUIRED'
        }
        else { $overall = 'REPAIR_REQUIRED' }
    }
    elseif ($auto.Count -gt 0) { $overall = 'AUTO_STARTABLE' }

    [pscustomobject]@{
        schema = 'UR_WEB_R004_FIRST_RUN_REPAIR_ASSESSMENT_R001'
        ui_language = $UiLanguage
        overall_state = $overall
        user_attention_required = ($overall -in @('USER_ACTION_REQUIRED','REPAIR_REQUIRED','UNSUPPORTED'))
        auto_start_plan = @($auto)
        blockers = @($blockers)
        state = $State
        simulation = ($SimulateScenario -ne 'NONE')
    }
}

function Wait-Until {
    param([scriptblock]$Predicate,[int]$Seconds,[int]$SleepMs = 500)
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if (& $Predicate) { return $true }
        Start-Sleep -Milliseconds $SleepMs
    }
    return $false
}

function New-StartingUi {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $form = New-Object System.Windows.Forms.Form
    $form.Text = 'Universal Runtime'
    $form.StartPosition = 'CenterScreen'
    $form.Width = 460
    $form.Height = 165
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false
    $form.ControlBox = $false
    $form.TopMost = $true
    $form.FormBorderStyle = 'FixedDialog'

    $title = New-Object System.Windows.Forms.Label
    $title.Left = 24; $title.Top = 22; $title.Width = 390; $title.Height = 28
    $title.Font = [System.Drawing.Font]::new('Segoe UI',13,[System.Drawing.FontStyle]::Bold)
    $title.Text = T 'starting_title'
    $form.Controls.Add($title)

    $status = New-Object System.Windows.Forms.Label
    $status.Left = 25; $status.Top = 60; $status.Width = 390; $status.Height = 22
    $status.Font = [System.Drawing.Font]::new('Segoe UI',9)
    $status.Text = T 'preparing_services'
    $form.Controls.Add($status)

    $progress = New-Object System.Windows.Forms.ProgressBar
    $progress.Left = 25; $progress.Top = 92; $progress.Width = 390; $progress.Height = 16
    $progress.Style = [System.Windows.Forms.ProgressBarStyle]::Marquee
    $progress.MarqueeAnimationSpeed = 24
    $form.Controls.Add($progress)

    $form.Show()
    [System.Windows.Forms.Application]::DoEvents()
    return [pscustomobject]@{ Form=$form; Status=$status }
}

function Set-StartingUiStatus {
    param($Ui,[string]$Text)
    if (-not $Ui) { return }
    $Ui.Status.Text = $Text
    [System.Windows.Forms.Application]::DoEvents()
}

function Close-StartingUi {
    param($Ui)
    if (-not $Ui) { return }
    $Ui.Form.Close()
    $Ui.Form.Dispose()
    [System.Windows.Forms.Application]::DoEvents()
}

function Invoke-AutoStart {
    param($Assessment)
    if ($Assessment.simulation) { return $Assessment }
    $state = $Assessment.state
    $startingUi = New-StartingUi
    try {
        if ($Assessment.auto_start_plan -contains 'START_DOCKER_DESKTOP') {
            Set-StartingUiStatus -Ui $startingUi -Text (T 'starting_docker')
            $docker = [string]$state.docker_cli
            if ($docker) {
                $start = Invoke-NativeCapture -FilePath $docker -Arguments @('desktop','start','--detach','--timeout','120')
                if ($start.ExitCode -ne 0) {
                    $exe = [string]$state.docker_desktop_exe
                    if ($exe) { Start-Process -FilePath $exe | Out-Null }
                }
            }
            elseif ($state.docker_desktop_exe) { Start-Process -FilePath ([string]$state.docker_desktop_exe) | Out-Null }
            [void](Wait-Until -Seconds 120 -SleepMs 1000 -Predicate { (Get-DockerDesktopStatus -DockerCli (Resolve-DockerCli)) -eq 'running' })
        }

        if ($Assessment.auto_start_plan -contains 'START_RUNTIME_19103') {
            Set-StartingUiStatus -Ui $startingUi -Text (T 'starting_runtime')
            if (-not (Test-TcpPortListening -Port $RuntimePort)) {
                New-Item -ItemType Directory -Force -Path $RuntimeStateRoot | Out-Null
                $env:PYTHONPATH = "$RuntimeOverlay;$RuntimeRoot\src"
                $env:UNIVERSAL_RUNTIME_ARTIFACT_ROOT = Join-Path $RuntimeRoot 'artifacts'
                $env:UNIVERSAL_RUNTIME_PACK_AUTHORITY_ROOT = $RuntimeRoot
                $env:UNIVERSAL_RUNTIME_FASTEMBED_SIDECAR_ROOT = Join-Path $RuntimeRoot '.sidecars\fastembed_0_8_0_multilingual_minilm_r001'
                Start-Process -FilePath $RuntimePython -ArgumentList @('-m','universal_runtime.cli','web','--host','127.0.0.1','--port',[string]$RuntimePort) -WorkingDirectory $RuntimeRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $RuntimeStateRoot 'runtime_19103.stdout.log') -RedirectStandardError (Join-Path $RuntimeStateRoot 'runtime_19103.stderr.log') | Out-Null
                [void](Wait-Until -Seconds 90 -Predicate { Test-HttpReady -Url $RuntimeHealthUrl -RequireRuntimeShape })
            }
        }

        if ($Assessment.auto_start_plan -contains 'START_PRODUCT_CONTAINERS') {
            Set-StartingUiStatus -Ui $startingUi -Text (T 'starting_services')
            $docker = Resolve-DockerCli
            if ($docker) {
                foreach ($name in $DailyContainers) {
                    $probe = Invoke-NativeCapture -FilePath $docker -Arguments @('inspect','--format','{{.State.Status}}',$name)
                    if ($probe.ExitCode -eq 0 -and ([string]$probe.Output[0]) -ne 'running') {
                        [void](Invoke-NativeCapture -FilePath $docker -Arguments @('start',$name))
                    }
                }
            }
        }
        Set-StartingUiStatus -Ui $startingUi -Text (T 'finishing_startup')
        [void](Wait-Until -Seconds 90 -SleepMs 1000 -Predicate { Test-HttpReady -Url $DailyUrl })
    }
    finally {
        Close-StartingUi -Ui $startingUi
    }
    $after = Get-Assessment -State (Get-ObservedState)
    if ($after.overall_state -eq 'AUTO_STARTABLE') {
        $extra = @($after.blockers)
        if ($Assessment.auto_start_plan -contains 'START_DOCKER_DESKTOP' -and $after.state.docker_desktop -ne 'running') {
            $extra += 'DOCKER_DESKTOP_START_NEEDS_ATTENTION'
            $after.overall_state = 'USER_ACTION_REQUIRED'
        }
        elseif ($Assessment.auto_start_plan -contains 'START_RUNTIME_19103' -and $after.state.runtime -ne 'running') {
            $extra += 'RUNTIME_START_FAILED'
            $after.overall_state = 'REPAIR_REQUIRED'
        }
        elseif ($Assessment.auto_start_plan -contains 'START_PRODUCT_CONTAINERS' -and $after.state.production_stack -ne 'running') {
            $extra += 'PRODUCT_SERVICES_START_FAILED'
            $after.overall_state = 'REPAIR_REQUIRED'
        }
        else {
            $extra += 'PRODUCT_HTTP_NOT_READY'
            $after.overall_state = 'REPAIR_REQUIRED'
        }
        $after.blockers = @($extra)
        $after.user_attention_required = $true
    }
    return $after
}

function Get-FriendlyBlockerText {
    param([string]$Code)
    return T $Code
}

function Get-OfficialHelpUrl {
    param($Assessment)
    if ($Assessment.blockers -contains 'DOCKER_DESKTOP_INSTALL_REQUIRED' -or $Assessment.blockers -contains 'DOCKER_DESKTOP_START_NEEDS_ATTENTION') { return ($Manifest.requirements | Where-Object id -eq 'docker_desktop').provider.official_url }
    if ($Assessment.blockers -contains 'EDGE_INSTALL_REQUIRED') { return ($Manifest.requirements | Where-Object id -eq 'edge').provider.official_url }
    if ($Assessment.blockers -contains 'WSL2_ENABLE_OR_INSTALL_REQUIRED') { return ($Manifest.requirements | Where-Object id -eq 'wsl2').provider.official_url }
    return $null
}

function Show-RecoveryUi {
    param($Assessment)
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $form = New-Object System.Windows.Forms.Form
    $form.Text = 'Universal Runtime'
    $form.StartPosition = 'CenterScreen'
    $form.Width = 620
    $form.Height = 430
    $form.MaximizeBox = $false
    $form.FormBorderStyle = 'FixedDialog'
    $form.AutoScaleMode = [System.Windows.Forms.AutoScaleMode]::Dpi

    $title = New-Object System.Windows.Forms.Label
    $title.Left = 28; $title.Top = 25; $title.Width = 545; $title.Height = 36
    $title.Font = [System.Drawing.Font]::new('Segoe UI',16,[System.Drawing.FontStyle]::Bold)
    $title.Text = if ($Assessment.overall_state -eq 'UNSUPPORTED') { T 'unsupported_title' } else { T 'setup_title' }
    $form.Controls.Add($title)

    $subtitle = New-Object System.Windows.Forms.Label
    $subtitle.Left = 30; $subtitle.Top = 72; $subtitle.Width = 540; $subtitle.Height = 42
    $subtitle.Font = [System.Drawing.Font]::new('Segoe UI',9)
    $subtitle.Text = T 'setup_subtitle'
    $form.Controls.Add($subtitle)

    $box = New-Object System.Windows.Forms.TextBox
    $box.Left = 30; $box.Top = 125; $box.Width = 540; $box.Height = 145
    $box.Multiline = $true; $box.ReadOnly = $true; $box.BorderStyle = 'FixedSingle'
    $box.Font = [System.Drawing.Font]::new('Segoe UI',10)
    $box.Text = (($Assessment.blockers | ForEach-Object { [char]0x2022 + ' ' + (Get-FriendlyBlockerText $_) }) -join "`r`n`r`n")
    $form.Controls.Add($box)

    $try = New-Object System.Windows.Forms.Button
    $try.Text = T 'try_again'; $try.Left = 335; $try.Top = 305; $try.Width = 110; $try.Height = 34
    $try.DialogResult = [System.Windows.Forms.DialogResult]::Retry
    $form.Controls.Add($try)
    $form.AcceptButton = $try
    $try.TabIndex = 1

    $helpUrl = Get-OfficialHelpUrl -Assessment $Assessment
    $help = New-Object System.Windows.Forms.Button
    $help.Text = T 'official_help'; $help.Left = 215; $help.Top = 305; $help.Width = 110; $help.Height = 34
    $help.Enabled = [bool]$helpUrl
    if ($helpUrl) { $help.Add_Click({ Start-Process $helpUrl | Out-Null }) }
    $form.Controls.Add($help)
    $help.TabIndex = 0

    $close = New-Object System.Windows.Forms.Button
    $close.Text = T 'close'; $close.Left = 455; $close.Top = 305; $close.Width = 110; $close.Height = 34
    $close.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
    $form.Controls.Add($close)
    $close.TabIndex = 2
    $form.CancelButton = $close

    $detailsLink = New-Object System.Windows.Forms.LinkLabel
    $detailsLink.Left = 30; $detailsLink.Top = 360; $detailsLink.Width = 170; $detailsLink.Height = 24
    $detailsLink.Text = T 'show_details'
    $form.Controls.Add($detailsLink)
    $detailsLink.TabIndex = 3

    $detailsBox = New-Object System.Windows.Forms.TextBox
    $detailsBox.Left = 30; $detailsBox.Top = 392; $detailsBox.Width = 535; $detailsBox.Height = 90
    $detailsBox.Multiline = $true; $detailsBox.ReadOnly = $true; $detailsBox.ScrollBars = 'Vertical'
    $detailsBox.Font = [System.Drawing.Font]::new('Consolas',8)
    $detailsBox.Text = (T 'advanced_code') + ': ' + (($Assessment.blockers) -join ', ')
    $detailsBox.Visible = $false
    $form.Controls.Add($detailsBox)

    $copyDetails = New-Object System.Windows.Forms.Button
    $copyDetails.Text = T 'copy_details'; $copyDetails.Left = 420; $copyDetails.Top = 356; $copyDetails.Width = 145; $copyDetails.Height = 28
    $copyDetails.Visible = $false; $copyDetails.TabIndex = 4
    $copyDetails.Add_Click({
        $safeState = [ordered]@{
            schema = $Assessment.schema
            ui_language = $Assessment.ui_language
            overall_state = $Assessment.overall_state
            blockers = @($Assessment.blockers)
            windows = $Assessment.state.windows
            os_build = $Assessment.state.os_build
            wsl2 = $Assessment.state.wsl2
            docker_desktop = $Assessment.state.docker_desktop
            runtime_bundle = $Assessment.state.runtime_bundle
            runtime = $Assessment.state.runtime
            production_stack = $Assessment.state.production_stack
            ports = $Assessment.state.ports
            daily_http = $Assessment.state.daily_http
        }
        [System.Windows.Forms.Clipboard]::SetText(($safeState | ConvertTo-Json -Depth 4 -Compress))
    })
    $form.Controls.Add($copyDetails)

    $detailsLink.Add_Click({
        if ($detailsBox.Visible) {
            $detailsBox.Visible = $false
            $copyDetails.Visible = $false
            $detailsLink.Text = T 'show_details'
            $form.Height = 430
        }
        else {
            $detailsBox.Visible = $true
            $copyDetails.Visible = $true
            $detailsLink.Text = T 'hide_details'
            $form.Height = 540
        }
    })
    return $form.ShowDialog()
}

$assessment = Get-Assessment -State (Get-ObservedState)
if ($EnsureReady -and $assessment.overall_state -eq 'AUTO_STARTABLE') {
    $assessment = Invoke-AutoStart -Assessment $assessment
}
if ($ShowUi -and $assessment.simulation -and $assessment.overall_state -eq 'AUTO_STARTABLE') {
    $startingUi = New-StartingUi
    try {
        $previewText = if ($assessment.auto_start_plan -contains 'START_DOCKER_DESKTOP') {
            T 'starting_docker'
        }
        elseif ($assessment.auto_start_plan -contains 'START_RUNTIME_19103') {
            T 'starting_runtime'
        }
        else {
            T 'starting_services'
        }
        Set-StartingUiStatus -Ui $startingUi -Text $previewText
        Start-Sleep -Seconds 2
    }
    finally {
        Close-StartingUi -Ui $startingUi
    }
    $assessment.overall_state = 'READY'
    $assessment.user_attention_required = $false
    $assessment.auto_start_plan = @()
    $assessment.blockers = @()
}

if ($ShowUi -and $assessment.overall_state -eq 'AUTO_STARTABLE') {
    $assessment = Invoke-AutoStart -Assessment $assessment
}

if ($ShowUi -and $assessment.overall_state -ne 'READY') {
    do {
        $result = Show-RecoveryUi -Assessment $assessment
        if ($result -eq [System.Windows.Forms.DialogResult]::Retry) {
            $assessment = Get-Assessment -State (Get-ObservedState)
            if ($assessment.overall_state -eq 'AUTO_STARTABLE') { $assessment = Invoke-AutoStart -Assessment $assessment }
        }
    } while ($result -eq [System.Windows.Forms.DialogResult]::Retry -and $assessment.overall_state -ne 'READY')
}

if ($Json -or $CheckOnly -or $EnsureReady) { $assessment | ConvertTo-Json -Depth 8 -Compress }
if ($assessment.overall_state -eq 'READY') { exit 0 }
if ($assessment.overall_state -eq 'AUTO_STARTABLE') { exit 10 }
if ($assessment.overall_state -eq 'REPAIR_REQUIRED') { exit 20 }
if ($assessment.overall_state -eq 'USER_ACTION_REQUIRED') { exit 30 }
exit 40
