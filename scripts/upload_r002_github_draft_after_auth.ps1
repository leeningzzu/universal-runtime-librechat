param([string]$Repo = 'leeningzzu/universal-runtime-librechat',
      [string]$Tag = 'inquiry-desk-p4a-rc1-r002-nonshipping')
# Owner-only GitHub DRAFT upload; NEVER publish or promote.
$ErrorActionPreference='Stop'
$Root=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$Exe=Join-Path $Root 'windows/inquiry_desk/output/InquiryDesk_Setup_P4A_RC1NativeProjectFiles_R002_NONSHIPPING.exe'
$Sum=Join-Path $Root 'release/P4A_RC1_R002_NONSHIPPING_EXE_SHA256SUMS.txt'
$Notes=Join-Path $Root 'release/P4A_RC1_R002_NONSHIPPING_RELEASE_NOTES.md'
$ExpectedSha='81420f4aacc56100d0027f335e8eaa460d4c9322f79afe7362c7ac86d0822c18'
$ExpectedBytes=19341420
$Branch='candidate/inquiry-desk-windows-product'
if(!(Test-Path $Exe -PathType Leaf) -or !(Test-Path $Sum -PathType Leaf) -or !(Test-Path $Notes -PathType Leaf)){throw 'EXACT_RELEASE_ASSET_OR_NOTES_MISSING'}
$item=Get-Item $Exe
if($item.Length -ne $ExpectedBytes -or (Get-FileHash $Exe -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedSha){throw 'NONSHIPPING_ASSET_SOURCE_SHA_MISMATCH'}
if(([IO.File]::ReadAllText($Sum)).Trim() -cne ($ExpectedSha+'  '+$item.Name)){throw 'ASSET_CHECKSUM_SIDECAR_MISMATCH'}
Push-Location $Root
try {
  $sha=(& git rev-parse HEAD).Trim()
  if($LASTEXITCODE -ne 0 -or $sha -notmatch '^[0-9a-f]{40}$'){throw 'LOCAL_GIT_HEAD_INVALID'}
  $remote=@(& git -c credential.interactive=never ls-remote ('https://github.com/'+$Repo+'.git') ('refs/heads/'+$Branch))
  if($LASTEXITCODE -ne 0 -or $remote.Count -ne 1 -or (($remote[0] -split '\s+')[0] -cne $sha)){throw 'EXACT_GITHUB_SOURCE_COMMIT_NOT_PUSHED'}
  $gh=Get-Command gh.exe -ErrorAction SilentlyContinue
  if(!$gh){throw 'GITHUB_CLI_UNAVAILABLE_REQUIRE_OWNER_AUTH'}
  & $gh.Source auth status 1>$null
  if($LASTEXITCODE -ne 0){throw 'GITHUB_OAUTH_AUTHORIZATION_REQUIRED'}
  $old=$ErrorActionPreference
  try {
    $ErrorActionPreference='Continue'
    $existing=@(& $gh.Source release view $Tag -R $Repo --json isDraft,tagName --jq '.' 2>$null)
    $priorExit=$LASTEXITCODE
  }finally{$ErrorActionPreference=$old}
  if($priorExit -eq 0){
    $prior=($existing -join [Environment]::NewLine)|ConvertFrom-Json
    if($prior.isDraft -ne $true){throw 'TAG_ALREADY_PUBLIC_DO_NOT_TOUCH'}
    throw 'DRAFT_ALREADY_EXISTS_REVIEW_REMOTE_ASSETS_BEFORE_RETRY'
  }
  $args=@('release','create',$Tag,$Exe,$Sum,'-R',$Repo,'--target',$sha,'--draft','--prerelease','--title',
          'Inquiry Desk P4A rc1 R002 NONSHIPPING (Product Gate2/3 unverified)','--notes-file',$Notes)
  & $gh.Source @args
  if($LASTEXITCODE -ne 0){throw 'GITHUB_ASSET_UPLOAD_OUTCOME_UNKNOWN_NO_AUTO_RETRY'}
  $out=@(& $gh.Source release view $Tag -R $Repo --json isDraft,tagName,assets --jq '.')
  if($LASTEXITCODE -ne 0){throw 'DRAFT_RELEASE_METADATA_UNVERIFIED'}
  $release=($out -join [Environment]::NewLine)|ConvertFrom-Json
  if($release.isDraft -ne $true){throw 'DRAFT_WAS_UNEXPECTEDLY_PUBLISHED_STOP'}
  $assets=@($release.assets|Where-Object{$_.name -eq $item.Name})
  if($assets.Count -ne 1 -or $assets[0].size -ne $ExpectedBytes){throw 'REMOTE_RELEASE_ASSET_NAME_OR_BYTES_MISMATCH'}
  $tmp=Join-Path ([IO.Path]::GetTempPath()) ('ID_GitHub_Draft_Readback_'+[Guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Path $tmp | Out-Null
  try{
    & $gh.Source release download $Tag -R $Repo -p $item.Name -D $tmp
    if($LASTEXITCODE -ne 0){throw 'GITHUB_DRAFT_DOWNLOAD_FAILED'}
    $target=Join-Path $tmp $item.Name
    if((Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ExpectedSha){throw 'GITHUB_DOWNLOADED_DRAFT_EXE_SHA_MISMATCH'}
  }finally{Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue}
  Write-Output ('GITHUB_DRAFT_ASSET_VERIFIED_SHA256='+$ExpectedSha)
  Write-Output ('REMOTE_SOURCE_COMMIT='+$sha)
  Write-Output 'PUBLIC_LATEST_RELEASE=NO;GITHUB_DRAFT_ONLY=YES'
}finally{Pop-Location}
