param([string]$MakensisPath = "")
$ErrorActionPreference = "Stop"
$Root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$Package = Join-Path $Root "windows\inquiry_desk"
$Payload = Join-Path $Package "payload"
$Installer = Join-Path $Package "installer"
$Output = Join-Path $Package "output\InquiryDesk_Setup_R232_NONSHIPPING.exe"
$Verifier = Join-Path $Root "tools\verify_distribution.py"
if (-not [Environment]::Is64BitOperatingSystem) { throw "WINDOWS_X64_REQUIRED" }
if (Test-Path -LiteralPath $Output) { throw "RELEASE_OUTPUT_EXISTS_NO_OVERWRITE" }
if (Test-Path "X:\") { throw "BUILD_ALIAS_ALREADY_CLAIMED" }
$python = Get-Command python.exe -ErrorAction Stop
$test = @(& $python.Source $Verifier)
if ($LASTEXITCODE -ne 0) { throw "R232_SOURCE_INTEGRITY_VERIFICATION_FAILED" }
if (-not $MakensisPath) {
    $cmd = Get-Command makensis.exe -ErrorAction SilentlyContinue
    if ($cmd) { $MakensisPath = $cmd.Source }
    if (-not $MakensisPath) {
        foreach ($location in @(
            (Join-Path ([Environment]::GetEnvironmentVariable('ProgramFiles(x86)')) "NSIS\makensis.exe"),
            (Join-Path $env:ProgramFiles "NSIS\makensis.exe")
        )) {
            if ($location -and (Test-Path -LiteralPath $location -PathType Leaf)) {
                $MakensisPath = $location
                break
            }
        }
    }
}
if (-not $MakensisPath -or -not (Test-Path -LiteralPath $MakensisPath -PathType Leaf)) { throw "OFFICIAL_NSIS_313_COMPILER_REQUIRED" }
New-Item -ItemType Directory -Path (Join-Path $Package "output") -Force | Out-Null
$mounted = $false
$pushed = $false
try {
    & subst.exe X: $Payload | Out-Null
    if ($LASTEXITCODE -ne 0 -or !(Test-Path "X:\product\windows\InquiryDesk.ps1")) { throw "COMPILER_ALIAS_NOT_READY" }
    $mounted = $true
    Push-Location -LiteralPath $Installer
    $pushed = $true
    $prev = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        $logs = @(& $MakensisPath "/V2" "InquiryDesk_Setup_R232_NONSHIPPING.nsi" 2>&1)
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $prev }
    if ($code -ne 0) { throw ("NSIS_COMPILATION_FAILED: "+($logs | Select-Object -Last 8 | Out-String)) }
} finally {
    if ($pushed) { Pop-Location }
    if ($mounted) { & subst.exe X: /D | Out-Null }
}
if (Test-Path "X:\") { throw "COMPILER_ALIAS_NOT_RELEASED" }
if (!(Test-Path -LiteralPath $Output -PathType Leaf)) { throw "EXE_NOT_GENERATED" }
[pscustomobject]@{
    scope = "CODE_ONLY_NONSHIPPING_BUILD_NOT_PRODUCT_PASS"
    exe = (Get-Item -LiteralPath $Output).FullName
    sha256 = (Get-FileHash -LiteralPath $Output -Algorithm SHA256).Hash.ToLowerInvariant()
    publisher_signed = $false
    GitHub_release_or_Product_PASS = $false
} | ConvertTo-Json -Compress
