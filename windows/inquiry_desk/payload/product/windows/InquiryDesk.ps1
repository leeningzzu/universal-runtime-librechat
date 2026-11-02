param([ValidateSet('Open','Setup','Check','Shutdown','ConfigureFileSearch')][string]$Mode = 'Open')
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$Root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$OwnerRoot = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'InquiryDesk\Core_v088'
$OwnerFile = Join-Path $OwnerRoot 'owner.json'
$EnvFile = Join-Path $OwnerRoot 'secrets\core.env'
$RagEnvFile = Join-Path $OwnerRoot 'secrets\rag.env'
$PgEnvFile = Join-Path $OwnerRoot 'secrets\pgvector.env'
$ComposeFile = Join-Path $Root 'product\compose\docker-compose.online-nonshipping.yaml'
$SourceManifest = Join-Path $Root 'manifest\SHA256SUMS'
$ReleaseManifest = Join-Path $Root 'manifest\upstream-pinned-sources.NONSHIPPING.json'

function Notify([string]$Message,[switch]$Ask) {
    Add-Type -AssemblyName System.Windows.Forms
    $buttons = if($Ask){[Windows.Forms.MessageBoxButtons]::YesNo}else{[Windows.Forms.MessageBoxButtons]::OK}
    return [Windows.Forms.MessageBox]::Show($Message,'Inquiry Desk',$buttons,[Windows.Forms.MessageBoxIcon]::Information)
}
function Get-Digest([string]$File) {
    return ([string](Get-FileHash -Algorithm SHA256 -LiteralPath $File).Hash).ToLowerInvariant()
}
function Assert-CodeOnlyManifest {
    $rootPrefix = $Root.TrimEnd('\')+'\'
    if(!(Test-Path -LiteralPath $SourceManifest -PathType Leaf)){throw 'PRODUCT_MANIFEST_MISSING'}
    $seen = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    foreach($row in [IO.File]::ReadAllLines($SourceManifest)) {
        if($row -cnotmatch '^([0-9a-f]{64})  (.+)$'){throw 'RELEASE_MANIFEST_FORMAT_INVALID'}
        $expect = $Matches[1]
        $relative = $Matches[2]
        if(!$seen.Add($relative) -or $relative.Contains('..') -or $relative.Contains(':') -or $relative.StartsWith('/') -or $relative.StartsWith('\')){throw 'RELEASE_PATH_INVALID'}
        $target = [IO.Path]::GetFullPath((Join-Path $Root $relative.Replace('/','\')))
        if(!$target.StartsWith($rootPrefix,[StringComparison]::OrdinalIgnoreCase)){throw 'RELEASE_PATH_ESCAPE'}
        if(!(Test-Path -LiteralPath $target -PathType Leaf)){throw 'RELEASE_FILE_MISSING'}
        $item = Get-Item -Force -LiteralPath $target
        if(($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0){throw 'RELEASE_SYMLINK_FORBIDDEN'}
        if((Get-Digest $target) -cne $expect){throw 'RELEASE_HASH_DRIFT'}
    }
    # The pinned rc1 official API comes from the exact vendor container image,
    # not the removed v0.8.8 compiled API overlay. Verify all actual consumers.
    foreach($relative in @(
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
    )) {
        if(!(Test-Path -LiteralPath (Join-Path $Root $relative) -PathType Leaf)){throw 'PROJECT_CORE_OWNER_MISSING'}
    }
    if(Test-Path -LiteralPath (Join-Path $Root 'product\overlay\librechat\api.index.cjs')) {
        throw 'LEGACY_COMPILED_API_MUST_NOT_SHADOW_RC1_NATIVE_PROJECT_FILES'
    }
}
function Assert-Windows {
    if(![Environment]::Is64BitOperatingSystem){throw 'WINDOWS_X64_REQUIRED'}
    $os = Get-CimInstance Win32_OperatingSystem
    $build = [int]$os.BuildNumber
    if(($os.Caption -notmatch 'Windows 10|Windows 11') -or $build -lt 19045 -or ($build -gt 19045 -and $build -lt 22631)){throw 'WINDOWS_VERSION_VENDOR_SUPPORT_UNVERIFIED'}
    $ram = [int64](Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory
    if($ram -lt 8GB){throw 'RAM_EIGHT_GB_REQUIRED'}
    return [pscustomobject]@{Build=$build;Edition=[string]$os.Caption}
}
function VendorLink([string]$What,[string]$Url) {
    if((Notify "$What is required. Open its official installation page? Return to this desktop icon after the vendor setup finishes." -Ask) -eq [Windows.Forms.DialogResult]::Yes) {
        Start-Process $Url | Out-Null
    }
    throw 'VENDOR_PREREQUISITE_REQUIRED'
}
function Get-Docker {
    $c=Get-Command docker.exe -ErrorAction SilentlyContinue
    if($c -and (Test-Path -LiteralPath $c.Source)){return $c.Source}
    foreach($p in @((Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\resources\bin\docker.exe'),(Join-Path $env:ProgramFiles 'Docker\Docker\resources\bin\docker.exe'))) {
        if(Test-Path -LiteralPath $p -PathType Leaf){return $p}
    }
    VendorLink 'Docker Desktop' 'https://docs.docker.com/desktop/setup/install/windows-install/'
}
function Invoke-Native([string]$Exe,[string[]]$NativeArgv,[string]$Stage) {
    $prev=$ErrorActionPreference
    try { $ErrorActionPreference='Continue'; $lines=@(& $Exe @NativeArgv 2>&1); $code=$LASTEXITCODE }
    finally {$ErrorActionPreference=$prev}
    if($code -ne 0){throw ('PRODUCT_'+$Stage+'_FAILED')}
    return ($lines -join [Environment]::NewLine)
}
function Test-DockerEngine([string]$Docker) {
    $prev=$ErrorActionPreference
    try {$ErrorActionPreference='Continue'; $r=@(& $Docker info --format '{{.OSType}}' 2>$null);$exit=$LASTEXITCODE}
    finally {$ErrorActionPreference=$prev}
    return ($exit -eq 0 -and ($r -join '').Trim() -ceq 'linux')
}
function Ensure-Docker {
    $wsl=Get-Command wsl.exe -ErrorAction SilentlyContinue
    if(!$wsl){VendorLink 'Microsoft WSL2' 'https://learn.microsoft.com/windows/wsl/install'}
    $docker=Get-Docker
    if(Test-DockerEngine $docker){return $docker}
    Notify 'Docker Desktop is installed but not running. Inquiry Desk will attempt to start it automatically; first-time license or Windows permission prompts remain yours.' | Out-Null
    $prev=$ErrorActionPreference
    try {$ErrorActionPreference='Continue'; $null=@(& $docker desktop start --detach --timeout 120 2>&1);$startCode=$LASTEXITCODE}
    finally {$ErrorActionPreference=$prev}
    if($startCode -ne 0) {
        foreach($p in @((Join-Path $env:LOCALAPPDATA 'Programs\DockerDesktop\Docker Desktop.exe'),(Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'))) {
            if(Test-Path -LiteralPath $p -PathType Leaf){Start-Process -FilePath $p | Out-Null;break}
        }
    }
    for($i=0;$i -lt 60;$i++){
        if(Test-DockerEngine $docker){return $docker}
        Start-Sleep -Seconds 2
    }
    throw 'DOCKER_START_TIMEOUT_CHECK_VENDOR_LICENSE_OR_WSL'
}
function Get-Python312 {
    $py=Get-Command py.exe -ErrorAction SilentlyContinue
    if($py){
        $prev=$ErrorActionPreference
        try {$ErrorActionPreference='Continue';$res=@(& $py.Source -3.12 -c 'import sys;print(sys.executable)' 2>$null);$exit=$LASTEXITCODE}
        finally {$ErrorActionPreference=$prev}
        if($exit -eq 0 -and $res.Count -gt 0 -and (Test-Path -LiteralPath $res[0] -PathType Leaf)){return [string]$res[0]}
    }
    $python=Get-Command python.exe -ErrorAction SilentlyContinue
    if($python){
        $prev=$ErrorActionPreference
        try {$ErrorActionPreference='Continue'; $v=@(& $python.Source -c 'import sys; print(int(sys.version_info[:2] == (3,12)))' 2>$null);$exit=$LASTEXITCODE}
        finally {$ErrorActionPreference=$prev}
        if($exit -eq 0 -and ($v -join '').Trim() -ceq '1'){return $python.Source}
    }
    VendorLink 'Python 3.12' 'https://www.python.org/downloads/windows/'
}
function Get-Owner {
    # Daily use, shutdown, resume and any future approved upgrade must all
    # verify the exact installed product bytes, not merely the manifest SHA.
    Assert-CodeOnlyManifest
    if(!(Test-Path -LiteralPath $OwnerFile -PathType Leaf)){throw 'NO_LOCAL_PRODUCT_OWNER_RUN_SETUP'}
    $o=Get-Content -Raw -LiteralPath $OwnerFile | ConvertFrom-Json
    if($o.schema -ne 'INQUIRY_DESK_LOCAL_OWNER_R227' -or $o.compose_project -cnotmatch '^aidescore-[0-9a-f]{16}$'){throw 'FOREIGN_OWNER_INVALID'}
    if([int]$o.runtime_port -lt 1024 -or [int]$o.ui_port -lt 1024){throw 'OWNER_PORT_INVALID'}
    if(!(Get-Acl -LiteralPath $OwnerRoot).AreAccessRulesProtected){throw 'OWNER_ACL_UNPROTECTED'}
    if((Get-Digest $SourceManifest) -cne [string]$o.bundle_anchor){throw 'UNAPPROVED_PRODUCT_SOURCE_UPDATE'}
    return $o
}
function New-Hex([int]$Count) {
    $raw=New-Object byte[] $Count
    $rng=[Security.Cryptography.RandomNumberGenerator]::Create()
    try {$rng.GetBytes($raw)}finally{$rng.Dispose()}
    return ([BitConverter]::ToString($raw)).Replace('-','').ToLowerInvariant()
}
function New-OwnerFolder {
    $parent=Split-Path $OwnerRoot -Parent
    if(!(Test-Path -LiteralPath $parent)){New-Item -ItemType Directory -Path $parent | Out-Null}
    if(Test-Path -LiteralPath $OwnerRoot){throw 'PARTIAL_OWNER_NEEDS_USER_APPROVED_REPAIR_NOT_AUTOMATIC_REPLACEMENT'}
    New-Item -ItemType Directory -Path $OwnerRoot | Out-Null
    $sid=[Security.Principal.WindowsIdentity]::GetCurrent().User
    $acl=New-Object Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true,$false)
    $flags=[Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [Security.AccessControl.InheritanceFlags]::ObjectInherit
    $acl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new($sid,[Security.AccessControl.FileSystemRights]::FullControl,$flags,[Security.AccessControl.PropagationFlags]::None,[Security.AccessControl.AccessControlType]::Allow))
    Set-Acl -LiteralPath $OwnerRoot -AclObject $acl
    if(!(Get-Acl -LiteralPath $OwnerRoot).AreAccessRulesProtected){throw 'PRIVATE_DATA_ACCESS_FENCE_FAILURE'}
    foreach($sub in @('secrets','python','runtime','runtime\artifacts','runtime\machine_local','runtime\tmp')){New-Item -ItemType Directory -Path (Join-Path $OwnerRoot $sub) -Force|Out-Null}
}
function New-Port {
    $l=[Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,0)
    try {$l.Start();return ([Net.IPEndPoint]$l.LocalEndpoint).Port}finally{$l.Stop()}
}
function Get-Pins {
    if(!(Test-Path -LiteralPath $ReleaseManifest -PathType Leaf)){throw 'EXACT_IMAGE_RELEASE_MANIFEST_REQUIRED'}
    $items=@((Get-Content -Raw -LiteralPath $ReleaseManifest | ConvertFrom-Json).upstream_images)
    $roles=@{
        librechat='ghcr.io/librechat-ai/librechat'
        mongodb='docker.io/library/mongo'
        'node-adapter-runtime'='docker.io/library/node'
        pgvector='docker.io/pgvector/pgvector'
        'rag-api'='registry.librechat.ai/librechat-ai/librechat-rag-api-dev-lite'
    }
    if($items.Count -ne $roles.Count){throw 'EXACT_NATIVE_PROJECT_IMAGE_COUNT_INVALID'}
    $found=@{}
    foreach($x in $items) {
        $role=[string]$x.role;$repo=[string]$x.repository;$digest=[string]$x.digest
        if(!$roles.ContainsKey($role) -or $roles[$role] -cne $repo -or
           $digest -cnotmatch '^sha256:[a-f0-9]{64}$' -or
           $found.ContainsKey($role)) {throw 'UNTRUSTED_PROJECT_NATIVE_IMAGE_IDENTITY'}
        $found[$role]=$repo+'@'+$digest
    }
    if($found.Count -ne $roles.Count){throw 'MISSING_NATIVE_PROJECT_IMAGE'}
    return $found
}
function Set-ComposeEnv([psobject]$Owner,[hashtable]$Pins) {
    $m=@{
        AIDES_LOCAL_COMPOSE_ID=[string]$Owner.compose_project
        AIDES_LIBRECHAT_IMAGE=[string]$Pins['librechat']
        AIDES_ADAPTER_IMAGE=[string]$Pins['node-adapter-runtime']
        AIDES_MONGODB_IMAGE=[string]$Pins['mongodb']
        AIDES_PGVECTOR_IMAGE=[string]$Pins['pgvector']
        AIDES_RAG_API_IMAGE=[string]$Pins['rag-api']
        AIDES_PGVECTOR_ENV_FILE=$PgEnvFile
        AIDES_RAG_ENV_FILE=$RagEnvFile
        AIDES_PAYLOAD_ROOT=Join-Path $Root 'product\overlay'
        AIDES_PRIVATE_ENV_FILE=$EnvFile
        AIDES_RUNTIME_BASE_URL=('http://host.docker.internal:'+[string]$Owner.runtime_port)
        AIDES_LOOPBACK_PORT=[string]$Owner.ui_port
    }
    return $m
}
function Invoke-Compose([string]$Docker,[psobject]$Owner,[hashtable]$Pins,[string[]]$ComposeArgv) {
    $m=Set-ComposeEnv $Owner $Pins;$prior=@{}
    foreach($k in $m.Keys){$prior[$k]=[Environment]::GetEnvironmentVariable($k,'Process');[Environment]::SetEnvironmentVariable($k,$m[$k],'Process')}
    try {return Invoke-Native $Docker (@('compose','--project-name',[string]$Owner.compose_project,'--file',$ComposeFile)+$ComposeArgv) 'OWNER_COMPOSE'}
    finally {foreach($k in $m.Keys){[Environment]::SetEnvironmentVariable($k,$prior[$k],'Process')}}
}
function Test-Health([string]$Url) {
    try {$r=Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3;return $r.StatusCode -eq 200}catch{return $false}
}
function Ensure-Runtime([psobject]$Owner,[string]$Docker,[hashtable]$Pins) {
    $url='http://127.0.0.1:'+[string]$Owner.runtime_port+'/api/health'
    if(Test-Health $url){return}
    $py=Join-Path $OwnerRoot 'python\core\Scripts\python.exe'
    if(!(Test-Path -LiteralPath $py -PathType Leaf)){throw 'RUNTIME_PYTHON_MISSING_REPAIR_REQUIRED'}
    $psi=New-Object Diagnostics.ProcessStartInfo
    $psi.FileName=$py
    $psi.Arguments='-m uvicorn universal_runtime.webapp:app --host 127.0.0.1 --port '+[string]$Owner.runtime_port+' --no-access-log'
    $psi.WorkingDirectory=Join-Path $Root 'product\runtime'
    $psi.UseShellExecute=$false;$psi.CreateNoWindow=$true
    $psi.EnvironmentVariables['PYTHONPATH']=Join-Path $Root 'product\runtime\src'
    $psi.EnvironmentVariables['PYTHONNOUSERSITE']='1'
    $psi.EnvironmentVariables['INQUIRY_DOCLING_SIDE_CAR_ROOT']=Join-Path $OwnerRoot 'python\docling'
    $psi.EnvironmentVariables['PYTHONDONTWRITEBYTECODE']='1'
    $psi.EnvironmentVariables['UNIVERSAL_RUNTIME_ARTIFACT_ROOT']=Join-Path $OwnerRoot 'runtime\artifacts'
    $psi.EnvironmentVariables['UNIVERSAL_RUNTIME_MACHINE_LOCAL_STATE_ROOT']=Join-Path $OwnerRoot 'runtime\machine_local'
    $psi.EnvironmentVariables['LOCALAPPDATA']=Join-Path $OwnerRoot 'runtime'
    $psi.EnvironmentVariables['TMP']=Join-Path $OwnerRoot 'runtime\tmp'
    $psi.EnvironmentVariables['TEMP']=Join-Path $OwnerRoot 'runtime\tmp'
    $lines=Get-Content -LiteralPath $EnvFile
    $envVals=@{}
    foreach($line in $lines){if($line -match '^([A-Z_]+)=(.*)$'){$envVals[$Matches[1]]=$Matches[2]}}
    if(!$envVals.ContainsKey('UR_SHELL_ADAPTER_KEY') -or !$envVals.ContainsKey('UR_RUNTIME_PROXY_KEY')){throw 'MISSING_OWNER_BRIDGE_KEYS'}
    # Every new-user C5 snapshot receives only this exact user's Compose identity,
    # current pinned Docker image config identities, and the accepted Project route SHA.
    # No developer Production container or image may be used as a fallback.
    $containerNames=@{
        C5_BACKUP_UI_CONTAINER=([string]$Owner.compose_project+'-librechat')
        C5_BACKUP_ADAPTER_CONTAINER=([string]$Owner.compose_project+'-runtime-adapter')
        C5_BACKUP_MONGO_CONTAINER=([string]$Owner.compose_project+'-mongodb')
    }
    foreach($name in $containerNames.Keys) {
        if($containerNames[$name] -cnotmatch '^aidescore-[a-f0-9]{16}-(?:librechat|runtime-adapter|mongodb)$') {
            throw 'C5_NEW_USER_EXCLUSIVE_CONTAINER_IDENTITY_INVALID'
        }
        $psi.EnvironmentVariables[$name]=[string]$containerNames[$name]
    }
    $imageRoles=@{
        C5_BACKUP_UI_IMAGE='librechat'
        C5_BACKUP_ADAPTER_IMAGE='node-adapter-runtime'
        C5_BACKUP_MONGO_IMAGE='mongodb'
    }
    foreach($name in $imageRoles.Keys) {
        $role=$imageRoles[$name]
        $configId=(Invoke-Native $Docker @('image','inspect',[string]$Pins[$role],'--format','{{.Id}}') 'IMAGE_CONFIG_ID').Trim()
        if($configId -cnotmatch '^sha256:[a-f0-9]{64}$'){throw 'C5_CURRENT_IMAGE_CONFIG_DIGEST_INVALID'}
        $psi.EnvironmentVariables[$name]=$configId
    }
    # The currently accepted native Project route digest is an upper bound:
    # if the public upstream image differs, C5 snapshot must STOP, not delete.
    $psi.EnvironmentVariables['C5_BACKUP_PROJECT_ROUTE_SHA256']='e683caac23893e4eb316ee830546e449120456871b4c19dd04a6a4a3e9019a94'
    $psi.EnvironmentVariables['C5_PROTECTED_BACKUP_EVIDENCE_ROOT']=Join-Path $OwnerRoot 'runtime\artifacts\handoff\AIDES_P1_C5_PRODUCT_USER_CONSUMER_REBIND_R001'
    $sha=[Security.Cryptography.SHA256]::Create()
    try {$psi.EnvironmentVariables['UNIVERSAL_RUNTIME_BRIDGE_GUARD_SHA256']=([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($envVals['UR_SHELL_ADAPTER_KEY'])))).Replace('-','').ToLowerInvariant()}
    finally {$sha.Dispose()}
    $psi.EnvironmentVariables['UR_RUNTIME_PROXY_KEY']=$envVals['UR_RUNTIME_PROXY_KEY']
    $process=[Diagnostics.Process]::Start($psi)
    if(!$process){throw 'RUNTIME_START_FAILED'}
    for($i=0;$i -lt 100;$i++){if($process.HasExited){throw 'RUNTIME_EXITED'};if(Test-Health $url){return};Start-Sleep -Seconds 1}
    throw 'RUNTIME_HEALTH_TIMEOUT'
}
function Ensure-Core([psobject]$Owner,[string]$Docker,[hashtable]$Pins) {
    Ensure-Runtime $Owner $Docker $Pins
    $null=Invoke-Compose $Docker $Owner $Pins @('config','--quiet')
    $null=Invoke-Compose $Docker $Owner $Pins @('up','--detach','--no-build','--pull','never')
    $url='http://127.0.0.1:'+[string]$Owner.ui_port+'/api/config'
    for($i=0;$i -lt 150;$i++){if(Test-Health $url){return};Start-Sleep -Seconds 1}
    throw 'LIBRECHAT_UI_HEALTH_TIMEOUT'
}
function Open-Window([psobject]$Owner) {
    $exe=Get-Command msedge.exe -ErrorAction SilentlyContinue
    $paths=@();if($exe){$paths+= $exe.Source}
    foreach($q in @('ProgramFiles','ProgramFiles(x86)')){$d=[Environment]::GetEnvironmentVariable($q);if($d){$paths+=Join-Path $d 'Microsoft\Edge\Application\msedge.exe'}}
    $found=$paths|Where-Object{Test-Path -LiteralPath $_ -PathType Leaf}|Select-Object -First 1
    if(!$found){VendorLink 'Microsoft Edge' 'https://www.microsoft.com/edge'}
    Start-Process -FilePath $found -ArgumentList ('--app=http://127.0.0.1:'+[string]$Owner.ui_port) | Out-Null
}
function Get-ExclusiveUserCount([psobject]$Owner,[string]$Docker) {
    $mongoName=[string]$Owner.compose_project+'-mongodb'
    if($mongoName -cnotmatch '^aidescore-[a-f0-9]{16}-mongodb$'){throw 'FIRST_USER_MONGO_OWNER_INVALID'}
    $query='db.getSiblingDB("LibreChat").users.countDocuments({})'
    $raw=Invoke-Native $Docker @('exec',$mongoName,'mongosh','--quiet','--eval',$query) 'OWNER_USER_COUNT'
    $lines=@($raw -split '\r?\n' | Where-Object {$_ -match '^[0-9]+$'})
    if($lines.Count -ne 1){throw 'FIRST_USER_COUNT_NOT_UNAMBIGUOUS'}
    return [int]$lines[0]
}
function Seal-FirstUserRegistration([psobject]$Owner,[string]$Docker,[hashtable]$Pins) {
    $users=Get-ExclusiveUserCount $Owner $Docker
    if($users -eq 0){return $false}
    $extraAccountsBeforeSeal = ($users -gt 1)
    if($Owner.PSObject.Properties['first_user_registration_closed'] -and
       $Owner.first_user_registration_closed -eq $true){return $true}
    # Persist the single-user default through LibreChat's existing native env.
    $lines=@([IO.File]::ReadAllLines($EnvFile))
    $enabled=@($lines | Where-Object {$_ -ceq 'ALLOW_REGISTRATION=true'})
    $disabled=@($lines | Where-Object {$_ -ceq 'ALLOW_REGISTRATION=false'})
    if($enabled.Count -eq 1 -and $disabled.Count -eq 0) {
        $changed=@($lines | ForEach-Object {
            if($_ -ceq 'ALLOW_REGISTRATION=true') {'ALLOW_REGISTRATION=false'} else {$_}
        })
        $tmp=$EnvFile+'.first-user-lock.tmp'
        $backup=$EnvFile+'.first-user-lock.backup'
        if(Test-Path -LiteralPath $tmp){throw 'FIRST_USER_SECRET_TEMP_COLLISION'}
        [IO.File]::WriteAllLines($tmp,[string[]]$changed,[Text.UTF8Encoding]::new($false))
        [IO.File]::Replace($tmp,$EnvFile,$backup)
    } elseif($enabled.Count -ne 0 -or $disabled.Count -ne 1) {
        throw 'FIRST_USER_REGISTRATION_CONFIGURATION_DRIFT'
    }
    # Existing native Docker Compose only recreates the UI process;
    # MongoDB volumes, file uploads and Runtime artifacts stay untouched.
    $null=Invoke-Compose $Docker $Owner $Pins @('up','--detach','--no-deps','--force-recreate','--pull','never','librechat')
    $url='http://127.0.0.1:'+[string]$Owner.ui_port+'/api/config'
    $healthy=$false
    for($j=0;$j -lt 100;$j++){
        if(Test-Health $url){$healthy=$true;break}
        Start-Sleep -Milliseconds 900
    }
    if(!$healthy){throw 'FIRST_USER_LOCK_RESTART_NOT_HEALTHY'}
    $Owner.first_user_registration_closed=$true
    [IO.File]::WriteAllText($OwnerFile,($Owner|ConvertTo-Json -Depth 6),[Text.UTF8Encoding]::new($false))
    if($extraAccountsBeforeSeal){throw 'MORE_THAN_ONE_USER_CREATED_BEFORE_REGISTRATION_SEALED'}
    return $true
}
function Wait-ForFirstUserAndSeal([psobject]$Owner,[string]$Docker,[hashtable]$Pins) {
    if($Owner.PSObject.Properties['first_user_registration_closed'] -and
       $Owner.first_user_registration_closed -eq $true){return}
    # This is bounded first-use admission, not a daemon or second account backend.
    # The user creates an account in native LibreChat. Keep its one-user signup
    # route on Windows localhost only, then close it using native env+Compose.
    for($i=0;$i -lt 300;$i++){
        if(Seal-FirstUserRegistration $Owner $Docker $Pins){
            Notify '你的第一个 Inquiry Desk 账号已创建。已关闭后续公开注册；请重新登录并继续使用原 Project。' | Out-Null
            return
        }
        Start-Sleep -Seconds 2
    }
    # No silent claim of account security: re-run Desktop entry to resume admission.
    Notify '尚未完成第一个账号注册。本机注册安全收口仍未完成；请在界面中完成注册，然后重新点击桌面图标以验证并关闭注册。' | Out-Null
}
function Complete-SetupCore([psobject]$Owner,[string]$Docker,[hashtable]$Pins) {
    if([string]$Owner.state -notin @('INITIALIZING','SERVICE_STARTED_FIRST_USER_JOURNEY_NOT_PROVEN')){throw 'UNTRUSTED_OWNER_SETUP_STATE'}
    Assert-CodeOnlyManifest
    $python=Get-Python312
    $venv=Join-Path $OwnerRoot 'python\core'
    if(!(Test-Path -LiteralPath (Join-Path $venv 'Scripts\python.exe') -PathType Leaf)){
        $null=Invoke-Native $python @('-m','venv',$venv) 'CREATE_RUNTIME_VENV'
    }
    $py=Join-Path $venv 'Scripts\python.exe'
    $runtimeLock=Join-Path $Root 'product\requirements\requirements-runtime-complete-SHA256-R211.txt'
    $null=Invoke-Native $py @('-m','pip','install','--disable-pip-version-check','--no-input','--retries','0','--timeout','25','--require-hashes','--only-binary=:all:','-r',$runtimeLock) 'PYPI_RUNTIME_LOCK'
    $docling=Join-Path $OwnerRoot 'python\docling'
    if(!(Test-Path -LiteralPath (Join-Path $docling 'Scripts\python.exe') -PathType Leaf)){
        $null=Invoke-Native $python @('-m','venv',$docling) 'CREATE_DOCLING_VENV'
    }
    $docpy=Join-Path $docling 'Scripts\python.exe'
    $doclock=Join-Path $Root 'product\requirements\requirements-docling-complete-SHA256-R211.txt'
    $null=Invoke-Native $docpy @('-m','pip','install','--disable-pip-version-check','--no-input','--retries','0','--timeout','25','--require-hashes','--only-binary=:all:','-r',$doclock) 'PYPI_DOCLING_LOCK'
    foreach($role in @('mongodb','node-adapter-runtime','librechat','pgvector','rag-api')){
        $null=Invoke-Native $Docker @('image','pull',$Pins[$role]) ('DOCKER_PULL_'+$role)
    }
    $null=New-Item -ItemType Directory -Path (Join-Path $Root 'product\overlay\librechat\empty-native-skill') -Force
    Ensure-Core $Owner $Docker $Pins
    $Owner.state='SERVICE_STARTED_FIRST_USER_JOURNEY_NOT_PROVEN'
    [IO.File]::WriteAllText($OwnerFile,($Owner|ConvertTo-Json -Depth 6),[Text.UTF8Encoding]::new($false))
    Open-Window $Owner
    Wait-ForFirstUserAndSeal $Owner $Docker $Pins
}
function Setup-Core {
    Assert-CodeOnlyManifest
    $null=Assert-Windows
    if(Test-Path -LiteralPath $OwnerRoot){throw 'OWNER_ALREADY_PRESENT_USE_OPEN_OR_REPAIR'}
    $null=Get-Python312
    $docker=Ensure-Docker
    $pins=Get-Pins
    if((Notify 'Install Inquiry Desk Core for this Windows user? It downloads five digest-pinned official container images (including native Project File Search) and hash-locked Python packages, creates isolated private user data, and can require significant disk space. Vendor license consent remains separate.' -Ask) -ne [Windows.Forms.DialogResult]::Yes){throw 'USER_DECLINED_FIRST_RUN_EFFECT'}
    New-OwnerFolder
    $owner=[ordered]@{
        schema='INQUIRY_DESK_LOCAL_OWNER_R227'
        logical_product_id='inquiry-desk-project-first'
        compose_project='aidescore-'+(New-Hex 8)
        runtime_port=(New-Port)
        ui_port=(New-Port)
        bundle_anchor=(Get-Digest $SourceManifest)
        state='INITIALIZING'
        user_approved_install=$true
        first_user_registration_closed=$false
        product_pass=$false
    }
    if($owner.ui_port -eq $owner.runtime_port){throw 'DUPLICATE_PORT_ALLOCATOR'}
    $values=@('CREDS_KEY','JWT_SECRET','JWT_REFRESH_SECRET','SESSION_SECRET','UR_SHELL_ADAPTER_KEY','UR_RUNTIME_PROXY_KEY')|ForEach-Object{$_+'='+(New-Hex 32)}
    $values+=('CREDS_IV='+(New-Hex 16))
    $values+=@('ALLOW_EMAIL_LOGIN=true','ALLOW_REGISTRATION=true','ALLOW_SOCIAL_LOGIN=false','ALLOW_SOCIAL_REGISTRATION=false','OPENAI_API_KEY=user_provided','ANTHROPIC_API_KEY=user_provided','GOOGLE_KEY=user_provided')
    [IO.File]::WriteAllLines($EnvFile,[string[]]$values,[Text.UTF8Encoding]::new($false))
    # Private per-user vector storage credentials. RAG embeds require separately
    # authorized provider settings: no copying a user_provided chat/model key.
    $pgPassword=New-Hex 32
    $pgValues=@('POSTGRES_DB=librechat_vectors','POSTGRES_USER=librechat_local',
        ('POSTGRES_PASSWORD='+$pgPassword))
    [IO.File]::WriteAllLines($PgEnvFile,[string[]]$pgValues,[Text.UTF8Encoding]::new($false))
    $jwtLine=@($values | Where-Object {$_ -match '^JWT_SECRET=[a-f0-9]{64}$'})
    if($jwtLine.Count -ne 1){throw 'RAG_NATIVE_USER_JWT_OWNER_NOT_EXACT'}
    $ragValues=@($pgValues + @('DB_HOST=vectordb','DB_PORT=5432',
        [string]$jwtLine[0], 'EMBEDDINGS_PROVIDER=openai'))
    [IO.File]::WriteAllLines($RagEnvFile,[string[]]$ragValues,[Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllText($OwnerFile,($owner|ConvertTo-Json -Depth 6),[Text.UTF8Encoding]::new($false))
    Complete-SetupCore ([pscustomobject]$owner) $docker $pins
    Configure-FileSearch -DuringSetup
}
function Open-Core {
    if(!(Test-Path -LiteralPath $OwnerFile -PathType Leaf)){Setup-Core;return}
    $owner=Get-Owner
    $docker=Ensure-Docker
    $pins=Get-Pins
    if($owner.state -eq 'INITIALIZING') {
        if($owner.user_approved_install -ne $true){throw 'INITIAL_INSTALL_EFFECT_NOT_APPROVED'}
        if((Notify 'The previous online setup was interrupted. Resume its exact approved components without deleting any existing Project data?' -Ask) -ne [Windows.Forms.DialogResult]::Yes){throw 'USER_DECLINED_SETUP_RESUME'}
        Complete-SetupCore $owner $docker $pins
        return
    }
    if($owner.state -cne 'SERVICE_STARTED_FIRST_USER_JOURNEY_NOT_PROVEN'){throw 'OWNER_STATE_REPAIR_REQUIRED'}
    Ensure-Core $owner $docker $pins
    Open-Window $owner
    Wait-ForFirstUserAndSeal $owner $docker $pins
}

function Configure-FileSearch([switch]$DuringSetup) {
    # Explicit opt-in to a DIFFERENT paid embeddings API credential. Do not
    # borrow user_provided chat keys or log the entered value.
    Assert-CodeOnlyManifest
    $owner=Get-Owner
    if(!(Test-Path -LiteralPath $RagEnvFile -PathType Leaf)){throw 'FILE_SEARCH_PRIVATE_ENV_MISSING'}
    if((Notify 'Project 文件检索需要单独的 OpenAI Embeddings API Key，可能产生费用。ChatGPT 订阅不包含这项 API 额度。是否现在配置？取消不影响普通聊天。' -Ask) -ne [Windows.Forms.DialogResult]::Yes){return}
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $form=New-Object Windows.Forms.Form
    $form.Text='Inquiry Desk｜配置文件检索'
    $form.Size=[Drawing.Size]::new(490,205)
    $form.StartPosition=[Windows.Forms.FormStartPosition]::CenterScreen
    $form.FormBorderStyle=[Windows.Forms.FormBorderStyle]::FixedDialog
    $form.MaximizeBox=$false
    $form.MinimizeBox=$false
    $label=New-Object Windows.Forms.Label
    $label.Text='请输入用于文件检索的独立 OpenAI API Key（只保存到本机个人私有配置）：'
    $label.Location=[Drawing.Point]::new(16,18)
    $label.Size=[Drawing.Size]::new(445,38)
    $field=New-Object Windows.Forms.TextBox
    $field.Location=[Drawing.Point]::new(16,63)
    $field.Size=[Drawing.Size]::new(445,26)
    $field.MaxLength=256
    $field.UseSystemPasswordChar=$true
    $ok=New-Object Windows.Forms.Button
    $ok.Text='保存'
    $ok.Location=[Drawing.Point]::new(286,111)
    $ok.DialogResult=[Windows.Forms.DialogResult]::OK
    $cancel=New-Object Windows.Forms.Button
    $cancel.Text='取消'
    $cancel.Location=[Drawing.Point]::new(383,111)
    $cancel.DialogResult=[Windows.Forms.DialogResult]::Cancel
    $form.Controls.AddRange(@($label,$field,$ok,$cancel))
    $form.AcceptButton=$ok
    $form.CancelButton=$cancel
    $key=$null
    try {
        if($form.ShowDialog() -ne [Windows.Forms.DialogResult]::OK){return}
        $key=$field.Text.Trim()
    } finally {
        $field.Clear()
        $form.Dispose()
    }
    if($key -cnotmatch '^sk-[A-Za-z0-9_-]{20,250}$'){
        Notify '密钥格式无法验证，没有保存。请确认复制的是 OpenAI API Key，而不是 ChatGPT 登录密码。'|Out-Null
        return
    }
    $before=[IO.File]::ReadAllLines($RagEnvFile)
    if(@($before|Where-Object {$_ -cmatch '^RAG_OPENAI_API_KEY='}).Count -gt 1){
        throw 'FILE_SEARCH_DUPLICATED_PRIVATE_KEY_ENTRY'
    }
    $clean=@($before|Where-Object {$_ -cnotmatch '^RAG_OPENAI_API_KEY='})
    if(@($clean|Where-Object {$_ -ceq 'EMBEDDINGS_PROVIDER=openai'}).Count -ne 1){
        throw 'FILE_SEARCH_PROVIDER_IDENTITY_CHANGED'
    }
    $pending=$RagEnvFile+'.new'
    if(Test-Path -LiteralPath $pending){throw 'FILE_SEARCH_PENDING_SECRET_COLLISION'}
    try {
        [IO.File]::WriteAllLines($pending,[string[]]($clean+@('RAG_OPENAI_API_KEY='+$key)),[Text.UTF8Encoding]::new($false))
        [IO.File]::Replace($pending,$RagEnvFile,$null)
    } finally {
        if(Test-Path -LiteralPath $pending){Remove-Item -LiteralPath $pending -Force}
        $key=$null
    }
    # Both initial Setup and later explicit configuration must activate the
    # new RAG env. Setup already started rag_api before the user's optional
    # key entry; skipping recreation here silently left File Search disabled.
    # Scope the effect to this one user's named Compose RAG service only.
    $docker=Get-Command docker.exe -ErrorAction SilentlyContinue
    if($docker -and (Test-Path -LiteralPath $docker.Source) -and (Test-DockerEngine $docker.Source)){
        $null=Invoke-Compose $docker.Source $owner (Get-Pins) @('up','--detach','--no-deps','--force-recreate','--pull','never','rag_api')
    }
    Notify '文件检索密钥已保存到本机私有配置。重新打开 Inquiry Desk 后可测试 File Search。模型费用由你的 API 提供商另行计费。'|Out-Null
}

function Shutdown-Core {
    # Exact code integrity is mandatory even on the uninstaller's path.
    # Do not stop unrelated Docker containers or delete user-owned volumes.
    Assert-CodeOnlyManifest
    if(!(Test-Path -LiteralPath $OwnerFile)){return}
    $o=Get-Owner
    $docker=Get-Command docker.exe -ErrorAction SilentlyContinue
    if($docker -and (Test-Path -LiteralPath $docker.Source) -and (Test-DockerEngine $docker.Source)) {
        $null=Invoke-Compose $docker.Source $o (Get-Pins) @('down','--timeout','15')
    }
    # Stop only the exact owned Python process, never arbitrary Python/Windows applications.
    $ownedPython=(Join-Path $OwnerRoot 'python\core').TrimEnd('\')+'\'
    $portMarker='--port '+[string]$o.runtime_port
    $matches=@(Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object {
        [string]$_.ExecutablePath -and [string]$_.CommandLine -and
        ([string]$_.ExecutablePath).StartsWith($ownedPython,[StringComparison]::OrdinalIgnoreCase) -and
        ([string]$_.CommandLine).Contains('universal_runtime.webapp:app') -and
        ([string]$_.CommandLine).Contains($portMarker)
    })
    if($matches.Count -gt 1){throw 'MULTIPLE_OWNED_RUNTIME_PROCESSES_UNVERIFIED'}
    if($matches.Count -eq 1){Stop-Process -Id $matches[0].ProcessId -ErrorAction Stop}
    # Docker named Mongo/chat/file volumes and all protected user Project data remain intact.
}
try {
    if($Mode -eq 'Check') {
        Assert-CodeOnlyManifest;$os=Assert-Windows
        Write-Output ([pscustomobject]@{Stage='R227_THIN_PRODUCT_STATIC_SOURCE_CHECK';CodeSHA='PASS';WindowsBuild=$os.Build;ProductPASS=$false} | ConvertTo-Json -Compress)
    } elseif($Mode -eq 'Setup'){Setup-Core}
    elseif($Mode -eq 'Open'){Open-Core}
    elseif($Mode -eq 'ConfigureFileSearch'){Configure-FileSearch}
    else {Shutdown-Core}
} catch {
    if($Mode -ne 'Check') {
        # No raw exception text, home path, credential, API key or private Project name in normal UI.
        Notify ('Inquiry Desk did not complete safely. Your existing Project data has been retained. Stage: '+$Mode+'. Run the installer again or use product repair when available.') | Out-Null
    }
    Write-Output ([pscustomobject]@{Stage='R227_FAIL_CLOSED';ErrorClass=$_.Exception.GetType().Name;ProductPASS=$false} | ConvertTo-Json -Compress)
    exit 91
}
