param(
    [string]$GitHubRepository = "",
    [string]$InstallerPath = "",
    [switch]$ApprovePrivateDraftUpload
)
$ErrorActionPreference = "Stop"
$Root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$PolicyPath = Join-Path $Root "release\R232_DRAFT_RELEASE_ASSET_POLICY.json"
$Checksum = Join-Path $Root "release\R232_NONSHIPPING_EXE_SHA256SUMS.txt"
$Notes = Join-Path $Root "release\R232_PRIVATE_DRAFT_NOTES.md"
$Integrity = Join-Path $Root "tools\verify_distribution.py"
$Policy = Get-Content -LiteralPath $PolicyPath -Raw | ConvertFrom-Json
if ($Policy.release_channel -cne "PRIVATE_GITHUB_DRAFT_PRERELEASE_ONLY" -or
    $Policy.product_pass -ne $false -or $Policy.release_allowed_public -ne $false) {
    throw "PRIVATE_DRAFT_RELEASE_POLICY_MISSING_OR_NOT_ACCEPTED"
}
if (-not $InstallerPath) { throw "EXACT_R232_INSTALLER_PATH_REQUIRED_BY_DEVELOPER_CALLER" }
$Installer = [IO.Path]::GetFullPath($InstallerPath)
if (!(Test-Path -LiteralPath $Installer -PathType Leaf)) { throw "R232_INSTALLER_NOT_AVAILABLE" }
$Asset = Get-Item -LiteralPath $Installer
if ($Asset.Name -cne [string]$Policy.asset_name -or
    $Asset.Length -ne [int64]$Policy.asset_bytes) { throw "R232_ASSET_NAME_OR_BYTES_CHANGED" }
$Sha = (Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash.ToLowerInvariant()
if ($Sha -cne [string]$Policy.asset_sha256) { throw "R232_ASSET_SHA256_CHANGED" }
$Line = [IO.File]::ReadAllText($Checksum).Trim()
if ($Line -cne ($Sha + "  " + $Asset.Name)) { throw "R232_RELEASE_CHECKSUM_SIDECAR_CHANGED" }
$Stream = [IO.File]::OpenRead($Installer)
try { $Mz = ($Stream.ReadByte() -eq 77 -and $Stream.ReadByte() -eq 90) }
finally { $Stream.Dispose() }
if (-not $Mz) { throw "R232_NOT_WINDOWS_PE" }
$Git = Get-Command git.exe -ErrorAction Stop
$Branch = (@(& $Git.Source -C $Root branch --show-current) -join "").Trim()
if ($Branch -cne [string]$Policy.canonical_source_branch) { throw "WRONG_GIT_RELEASE_SOURCE_BRANCH" }
$Tracked = @(& $Git.Source -C $Root status --porcelain=v1 -uno)
if ($LASTEXITCODE -ne 0 -or $Tracked.Count -ne 0) { throw "UNCOMMITTED_GITHUB_SOURCE_CHANGES" }
$Head = (@(& $Git.Source -C $Root rev-parse HEAD) -join "").Trim()
if ($Head -cnotmatch "^[a-f0-9]{40}$") { throw "GIT_RELEASE_HEAD_NOT_EXACT" }
$Py = Get-Command python.exe -ErrorAction Stop
$VerifyOutput = @(& $Py.Source $Integrity)
if ($LASTEXITCODE -ne 0 -or ($VerifyOutput -join "") -notmatch "PASS_R232_NONSHIPPING_SOURCE_INTEGRITY_ONLY") {
    throw "EXACT_GIT_RELEASE_SOURCE_QA_NOT_PASS"
}
if (-not $ApprovePrivateDraftUpload) {
    [pscustomobject]@{
        status = "R232_LOCAL_EXE_AND_SOURCE_VERIFIED_GITHUB_NOT_UPLOADED"
        asset_bytes = $Asset.Length
        sha256 = $Sha
        source_commit_sha = $Head
        repository = if ($GitHubRepository) {$GitHubRepository} else {"UNBOUND"}
        target_release_kind = "PRIVATE_DRAFT_PRERELEASE_ONLY"
        no_external_effect = $true
    } | ConvertTo-Json -Compress
    exit 0
}
if ($GitHubRepository -cnotmatch "^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$") {
    throw "EXACT_GITHUB_OWNER_REPOSITORY_REQUIRED"
}
$Gh = Get-Command gh.exe -ErrorAction SilentlyContinue
if (-not $Gh) { throw "OFFICIAL_GITHUB_CLI_NOT_INSTALLED_OR_NOT_AUTHENTICATED" }
$Previous = $ErrorActionPreference
try {
    $ErrorActionPreference = "Continue"
    $null = @(& $Gh.Source auth status --hostname github.com 2>&1)
    $AuthCode = $LASTEXITCODE
} finally { $ErrorActionPreference = $Previous }
if ($AuthCode -ne 0) { throw "GITHUB_ACCOUNT_AUTHORIZATION_REQUIRED" }
$Raw = @(& $Gh.Source repo view $GitHubRepository --json nameWithOwner,isPrivate,viewerPermission)
if ($LASTEXITCODE -ne 0) { throw "TARGET_GITHUB_REPOSITORY_NOT_AUTHORIZED" }
$RepoInfo = ($Raw -join [Environment]::NewLine) | ConvertFrom-Json
if ($RepoInfo.nameWithOwner -cne $GitHubRepository -or
    $RepoInfo.isPrivate -ne $true -or
    $RepoInfo.viewerPermission -notin @("WRITE","MAINTAIN","ADMIN")) {
    throw "GITHUB_REPOSITORY_MUST_BE_OWNER_APPROVED_PRIVATE_WITH_WRITE_PERMISSION"
}
# Public GitHub branch must already contain exactly the locally approved
# privacy-clean commit. The Git history is never force-pushed by this action.
$EncodedBranch = [Uri]::EscapeDataString($Branch)
$Ref = "repos/$GitHubRepository/branches/$EncodedBranch"
$RemoteRaw = @(& $Gh.Source api $Ref --jq ".commit.sha")
if ($LASTEXITCODE -ne 0 -or ($RemoteRaw -join "").Trim() -cne $Head) {
    throw "PRIVATE_GITHUB_REMOTE_CANDIDATE_BRANCH_SHA_NOT_IDENTICAL"
}
$Tag = ([string]$Policy.tag_prefix) + "-" + $Head.Substring(0,12)
$Previous = $ErrorActionPreference
try {
    $ErrorActionPreference = "Continue"
    $Existing = @(& $Gh.Source release view $Tag -R $GitHubRepository --json isDraft 2>&1)
    $ExistingCode = $LASTEXITCODE
} finally { $ErrorActionPreference = $Previous }
if ($ExistingCode -eq 0) { throw "GITHUB_DRAFT_TAG_ALREADY_EXISTS_NO_CLOBBER_OR_REPLACE" }
$null = @(& $Gh.Source release create $Tag $Installer $Checksum -R $GitHubRepository --target $Head --draft --prerelease --latest=false --title "Inquiry Desk R232 NONSHIPPING (private QA)" --notes-file $Notes)
if ($LASTEXITCODE -ne 0) { throw "GITHUB_PRIVATE_DRAFT_CREATE_OR_UPLOAD_FAILED_PARTIAL_DRAFT_POSSIBLE" }
$VerificationJson = @(& $Gh.Source release view $Tag -R $GitHubRepository --json isDraft,isPrerelease,assets)
if ($LASTEXITCODE -ne 0) { throw "GITHUB_DRAFT_POSTUPLOAD_METADATA_NOT_VERIFIED" }
$Result = ($VerificationJson -join "") | ConvertFrom-Json
if ($Result.isDraft -ne $true -or $Result.isPrerelease -ne $true) {
    throw "GITHUB_RELEASE_WAS_NOT_A_PRIVATE_DRAFT"
}
$ActualNames = @($Result.assets | ForEach-Object { $_.name })
if ($Asset.Name -notin $ActualNames -or "R232_NONSHIPPING_EXE_SHA256SUMS.txt" -notin $ActualNames) {
    throw "GITHUB_RELEASE_EXPECTED_TWO_ASSETS_NOT_RECORDED"
}
# Verify the actual remote bytes; not a generic success message.
$VerifyDir = Join-Path ([IO.Path]::GetTempPath()) ("r232-draft-verify-" + [Guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $VerifyDir -Force | Out-Null
try {
    $null = @(& $Gh.Source release download $Tag -R $GitHubRepository --pattern $Asset.Name --dir $VerifyDir)
    if ($LASTEXITCODE -ne 0) { throw "GITHUB_PRIVATE_RELEASE_DOWNLOADED_ASSET_NOT_AVAILABLE" }
    $Downloaded = Join-Path $VerifyDir $Asset.Name
    if (!(Test-Path -LiteralPath $Downloaded -PathType Leaf)) { throw "PRIVATE_RELEASE_ASSET_MISSING" }
    $DownloadedSHA = (Get-FileHash -LiteralPath $Downloaded -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($DownloadedSHA -cne $Sha) { throw "PRIVATE_RELEASE_ASSET_SHA256_DIFFERENT_FROM_LOCAL_R232" }
} finally {
    if ($VerifyDir -match "r232-draft-verify-[a-f0-9]{32}$" -and
        (Test-Path -LiteralPath $VerifyDir)) { Remove-Item -LiteralPath $VerifyDir -Recurse -Force }
}
[pscustomobject]@{
    status = "PASS_PRIVATE_GITHUB_DRAFT_R232_EXE_REMOTE_SHA_VERIFIED_NOT_PUBLISHED"
    repository = $GitHubRepository
    private_draft_tag = $Tag
    source_commit_sha = $Head
    asset_sha256 = $Sha
    asset_bytes = $Asset.Length
    public_release = $false
    product_pass = $false
} | ConvertTo-Json -Compress
