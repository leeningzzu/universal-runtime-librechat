$ErrorActionPreference = 'Stop'
# Real PowerShell 5.1 current first-party launcher methods in a disposable owner tree.
# This test never starts Docker, reads real User/Project assets, or calls a model.
$Repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$Entry = Join-Path $Repo 'windows\inquiry_desk\payload\product\windows\InquiryDesk.ps1'
$Nsis = Join-Path $Repo 'windows\inquiry_desk\installer\InquiryDesk_Setup_R241_NONSHIPPING.nsi'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Entry, [ref]$tokens, [ref]$errors)
if (@($errors).Count -ne 0) { throw 'R241_RELEASE_NATIVE_PS51_SYNTAX_INVALID' }
$functions = @($ast.FindAll({ param($a) $a -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true))
foreach ($name in @('Get-Digest','Assert-CodeOnlyManifest','Get-Owner','New-OwnerFolder','Shutdown-Core')) {
    $match = @($functions | Where-Object Name -eq $name)
    if ($match.Count -ne 1) { throw ('R241_REQUIRED_FUNCTION_MISSING_OR_DUPLICATE_' + $name) }
    . ([ScriptBlock]::Create($match[0].Extent.Text))
}
$actualInstaller = [IO.File]::ReadAllText($Nsis)
if ($actualInstaller -notmatch 'IfFileExists "\$INSTDIR\\manifest\\SHA256SUMS" 0 \+3') {
    throw 'R241_UNVERIFIED_OVERWRITE_GUARD_MISSING'
}
$TestRoot = Join-Path ([IO.Path]::GetTempPath()) ('InquiryDesk-R241-Synthetic-CI-' + [Guid]::NewGuid().ToString('N'))
if (Test-Path -LiteralPath $TestRoot) { throw 'R241_RANDOM_TEST_DIR_ALREADY_EXISTS' }
try {
    New-Item -ItemType Directory -Path $TestRoot -Force | Out-Null
    $Root = Join-Path $TestRoot 'installed'
    $OwnerRoot = Join-Path $TestRoot 'private_owner'
    $OwnerFile = Join-Path $OwnerRoot 'owner.json'
    $SourceManifest = Join-Path $Root 'manifest\SHA256SUMS'
    # This historical negative fixture exercises the CURRENT R002 launcher
    # code owner, not the retired v0.8.8 precompiled API. Keep the C5
    # tamper/update/uninstall rejection proof family unchanged.
    $listedFiles = @(
        'product\runtime\src\universal_runtime\webapp.py',
        'product\runtime\src\universal_runtime\cli.py',
        'product\runtime\scripts\c5_current_protected_snapshot.py',
        'product\overlay\adapter\adapter.js',
        'product\overlay\librechat\server.index.js',
        'product\overlay\librechat\projects.js',
        'product\overlay\librechat\ProjectAssistantProfile.js',
        'product\overlay\librechat\projectRuntimeMemoryContext.js',
        'product\overlay\librechat\projectChatToolsBridge.js',
        'product\overlay\librechat\C5WholeProjectDeleteOwners.js',
        'product\overlay\librechat\C5WriteFence.js',
        'product\overlay\librechat\frontend-dist\index.html'
    )
    foreach ($name in $listedFiles) {
        $path = Join-Path $Root $name
        New-Item -ItemType Directory -Path (Split-Path $path -Parent) -Force | Out-Null
        [IO.File]::WriteAllText($path, 'R241_SYNTHETIC_INERT_SOURCE_ONLY', [Text.UTF8Encoding]::new($false))
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
    if (-not (Get-Owner)) { throw 'R241_VALID_OWNER_NOT_ACCEPTED' }
    # Negative case introduced by official rc1 consumer replacement:
    # an old precompiled API shadow MUST be rejected even if every listed
    # new product-source SHA remains unchanged.
    $legacy = Join-Path $Root 'product\overlay\librechat\api.index.cjs'
    [IO.File]::WriteAllText($legacy,'R241_SYNTHETIC_STALE_OWNER_ONLY',[Text.UTF8Encoding]::new($false))
    $shadowRejected = $false
    try { $null = Get-Owner } catch {
        $shadowRejected = ($_.Exception.Message -match 'LEGACY_COMPILED_API_MUST_NOT_SHADOW_RC1_NATIVE_PROJECT_FILES')
    }
    if (-not $shadowRejected) { throw 'RC1_RETIRED_COMPILED_API_SHADOW_ACCEPTED' }
    Remove-Item -LiteralPath $legacy -Force

    [IO.File]::WriteAllText((Join-Path $Root $listedFiles[0]), 'R241_SYNTHETIC_TAMPER', [Text.UTF8Encoding]::new($false))
    $tamper = $false
    try { $null = Get-Owner } catch { $tamper = ($_.Exception.Message -match 'RELEASE_HASH_DRIFT') }
    if (-not $tamper) { throw 'R241_DAILY_TAMPER_ACCEPTED' }
    $uninstaller = $false
    try { Shutdown-Core } catch { $uninstaller = ($_.Exception.Message -match 'RELEASE_HASH_DRIFT') }
    if (-not $uninstaller) { throw 'R241_UNINSTALL_TAMPER_ACCEPTED' }
    Write-TestSourceManifest
    $update = $false
    try { $null = Get-Owner } catch { $update = ($_.Exception.Message -match 'UNAPPROVED_PRODUCT_SOURCE_UPDATE') }
    if (-not $update) { throw 'R241_SILENT_MANIFEST_UPDATE_ACCEPTED' }
    [pscustomobject]@{
        stage = 'PASS_R241_WINDOWS_NATIVE_OWNER_TAMPER_AND_UNINSTALL_INTEGRITY'
        original_owner = 'ACCEPTED'
        modified_code_daily = 'REJECTED'
        modified_code_uninstall = 'REJECTED'
        unapproved_version = 'REJECTED'
        stale_v088_compiled_api_shadow = 'REJECTED'
        in_place_overwrite = 'BLOCKED'
        user_project_data_effect = 0
    } | ConvertTo-Json -Compress
}
finally {
    $ExpectedPrefix = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\InquiryDesk-R241-Synthetic-CI-'
    $Actual = [IO.Path]::GetFullPath($TestRoot)
    if (-not $Actual.StartsWith($ExpectedPrefix,[StringComparison]::OrdinalIgnoreCase)) {
        throw 'R241_SYNTHETIC_ROOT_CLEANUP_SCOPE_INVALID'
    }
    if (Test-Path -LiteralPath $TestRoot) {
        Remove-Item -LiteralPath $TestRoot -Recurse -Force -ErrorAction Stop
    }
}
