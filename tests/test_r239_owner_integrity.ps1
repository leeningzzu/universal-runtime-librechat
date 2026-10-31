$ErrorActionPreference = 'Stop'
# Real PowerShell 5.1 current first-party launcher methods in a disposable owner tree.
# This test never starts Docker, reads real User/Project assets, or calls a model.
$Repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$Entry = Join-Path $Repo 'windows\inquiry_desk\payload\product\windows\InquiryDesk.ps1'
$Nsis = Join-Path $Repo 'windows\inquiry_desk\installer\InquiryDesk_Setup_R239_NONSHIPPING.nsi'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Entry, [ref]$tokens, [ref]$errors)
if (@($errors).Count -ne 0) { throw 'R239_RELEASE_NATIVE_PS51_SYNTAX_INVALID' }
$functions = @($ast.FindAll({ param($a) $a -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true))
foreach ($name in @('Get-Digest','Assert-CodeOnlyManifest','Get-Owner','New-OwnerFolder','Shutdown-Core')) {
    $match = @($functions | Where-Object Name -eq $name)
    if ($match.Count -ne 1) { throw ('R239_REQUIRED_FUNCTION_MISSING_OR_DUPLICATE_' + $name) }
    . ([ScriptBlock]::Create($match[0].Extent.Text))
}
$actualInstaller = [IO.File]::ReadAllText($Nsis)
if ($actualInstaller -notmatch 'IfFileExists "\$INSTDIR\\manifest\\SHA256SUMS" 0 \+3') {
    throw 'R239_UNVERIFIED_OVERWRITE_GUARD_MISSING'
}
$TestRoot = Join-Path ([IO.Path]::GetTempPath()) ('InquiryDesk-R239-Synthetic-CI-' + [Guid]::NewGuid().ToString('N'))
if (Test-Path -LiteralPath $TestRoot) { throw 'R239_RANDOM_TEST_DIR_ALREADY_EXISTS' }
try {
    New-Item -ItemType Directory -Path $TestRoot -Force | Out-Null
    $Root = Join-Path $TestRoot 'installed'
    $OwnerRoot = Join-Path $TestRoot 'private_owner'
    $OwnerFile = Join-Path $OwnerRoot 'owner.json'
    $SourceManifest = Join-Path $Root 'manifest\SHA256SUMS'
    $listedFiles = @(
        'product\runtime\src\universal_runtime\webapp.py',
        'product\runtime\src\universal_runtime\cli.py',
        'product\runtime\scripts\c5_current_protected_snapshot.py',
        'product\overlay\adapter\adapter.js',
        'product\overlay\librechat\api.index.cjs'
    )
    foreach ($name in $listedFiles) {
        $path = Join-Path $Root $name
        New-Item -ItemType Directory -Path (Split-Path $path -Parent) -Force | Out-Null
        [IO.File]::WriteAllText($path, 'R239_SYNTHETIC_INERT_SOURCE_ONLY', [Text.UTF8Encoding]::new($false))
    }
    New-Item -ItemType Directory -Path (Split-Path $SourceManifest -Parent) -Force | Out-Null
    function Write-TestSourceManifest {
        $rows = @($listedFiles | ForEach-Object {
            $f = Join-Path $Root $_
            (Get-Digest $f) + '  ' + $_.Replace('\','/')
        })
        [IO.File]::WriteAllLines($SourceManifest, [string[]]$rows, [Text.UTF8Encoding]::new($false))
    }
    Write-TestSourceManifest
    New-OwnerFolder
    $owner = [pscustomobject]@{
        schema = 'INQUIRY_DESK_LOCAL_OWNER_R227'
        compose_project = 'aidescore-0123456789abcdef'
        runtime_port = 19217
        ui_port = 19218
        bundle_anchor = Get-Digest $SourceManifest
        state = 'SERVICE_STARTED_FIRST_USER_JOURNEY_NOT_PROVEN'
    }
    [IO.File]::WriteAllText($OwnerFile, ($owner | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
    if (-not (Get-Owner)) { throw 'R239_VALID_OWNER_NOT_ACCEPTED' }
    [IO.File]::WriteAllText((Join-Path $Root $listedFiles[0]), 'R239_SYNTHETIC_TAMPER', [Text.UTF8Encoding]::new($false))
    $tamper = $false
    try { $null = Get-Owner } catch { $tamper = ($_.Exception.Message -match 'RELEASE_HASH_DRIFT') }
    if (-not $tamper) { throw 'R239_DAILY_TAMPER_ACCEPTED' }
    $uninstaller = $false
    try { Shutdown-Core } catch { $uninstaller = ($_.Exception.Message -match 'RELEASE_HASH_DRIFT') }
    if (-not $uninstaller) { throw 'R239_UNINSTALL_TAMPER_ACCEPTED' }
    Write-TestSourceManifest
    $update = $false
    try { $null = Get-Owner } catch { $update = ($_.Exception.Message -match 'UNAPPROVED_PRODUCT_SOURCE_UPDATE') }
    if (-not $update) { throw 'R239_SILENT_MANIFEST_UPDATE_ACCEPTED' }
    [pscustomobject]@{
        stage = 'PASS_R239_WINDOWS_NATIVE_OWNER_TAMPER_AND_UNINSTALL_INTEGRITY'
        original_owner = 'ACCEPTED'
        modified_code_daily = 'REJECTED'
        modified_code_uninstall = 'REJECTED'
        unapproved_version = 'REJECTED'
        in_place_overwrite = 'BLOCKED'
        user_project_data_effect = 0
    } | ConvertTo-Json -Compress
}
finally {
    $ExpectedPrefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\InquiryDesk-R239-Synthetic-CI-'
    $Actual = [IO.Path]::GetFullPath($TestRoot)
    if (-not $Actual.StartsWith($ExpectedPrefix,[StringComparison]::OrdinalIgnoreCase)) {
        throw 'R239_SYNTHETIC_ROOT_CLEANUP_SCOPE_INVALID'
    }
    if (Test-Path -LiteralPath $TestRoot) {
        Remove-Item -LiteralPath $TestRoot -Recurse -Force -ErrorAction Stop
    }
}
