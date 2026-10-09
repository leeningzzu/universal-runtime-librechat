param(
    [Parameter(Mandatory=$true)][string]$ActionId,
    [Parameter(Mandatory=$true)][string]$ActionRevision,
    [Parameter(Mandatory=$true)][string]$ExecutionId,
    [Parameter(Mandatory=$true)][string]$TargetScriptPath,
    [Parameter(Mandatory=$true)][string]$ExpectedTargetScriptSha256,
    [Parameter(Mandatory=$true)][string]$ActionSpecPath,
    [Parameter(Mandatory=$true)][string]$ExpectedActionSpecSha256,
    [Parameter(Mandatory=$true)][string]$OutputPath
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version 2.0

function Get-Sha256([string]$Path) {
    (Get-FileHash -LiteralPath $Path -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
}

function Get-TextSha256([string]$Text) {
    $Bytes=[Text.Encoding]::UTF8.GetBytes($Text)
    $Hasher=[Security.Cryptography.SHA256]::Create()
    try { (($Hasher.ComputeHash($Bytes) | ForEach-Object { $_.ToString('x2') }) -join '') }
    finally { $Hasher.Dispose() }
}

if($PSVersionTable.PSEdition -ne 'Desktop' -or $PSVersionTable.PSVersion.Major -ne 5) {
    throw 'WINDOWS_POWERSHELL_5_DESKTOP_REQUIRED'
}
if((Get-ExecutionPolicy) -ne 'Bypass') { throw 'PROCESS_EXECUTION_POLICY_BYPASS_REQUIRED' }
if([string]$ExecutionContext.SessionState.LanguageMode -ne 'FullLanguage') { throw 'FULL_LANGUAGE_REQUIRED' }
foreach($Path in @($TargetScriptPath,$ActionSpecPath)) {
    if(-not(Test-Path -LiteralPath $Path -PathType Leaf)) { throw "BOUND_INPUT_MISSING=$Path" }
}
if((Get-Sha256 $TargetScriptPath) -ne $ExpectedTargetScriptSha256) { throw 'TARGET_SCRIPT_SHA_MISMATCH' }
if((Get-Sha256 $ActionSpecPath) -ne $ExpectedActionSpecSha256) { throw 'ACTION_SPEC_SHA_MISMATCH' }

$Tokens=$null
$ParseErrors=$null
$Ast=[System.Management.Automation.Language.Parser]::ParseFile(
    $TargetScriptPath,[ref]$Tokens,[ref]$ParseErrors
)
if(@($ParseErrors).Length -ne 0) { throw 'TARGET_SCRIPT_PARSE_FAILED' }

$CountMembers=@($Ast.FindAll({
    param($Node)
    $Node -is [System.Management.Automation.Language.MemberExpressionAst] -and
    [string]$Node.Member.Value -ieq 'Count'
},$true))
if($CountMembers.Length -ne 0) { throw 'PS51_MEMBER_COUNT_REJECTED' }

$Commands=@($Ast.FindAll({ param($Node) $Node -is [System.Management.Automation.Language.CommandAst] },$true))
$Prohibited=New-Object System.Collections.Generic.List[string]
foreach($Command in $Commands) {
    $Name=[string]$Command.GetCommandName()
    $Elements=@($Command.CommandElements | ForEach-Object { [string]$_.Extent.Text })
    if($Name -ieq 'Get-History') { [void]$Prohibited.Add('SESSION_HISTORY_DEPENDENCY_REJECTED') }
    if($Name -match '^(python|python\.exe)$' -and ($Elements -contains '-c')) {
        [void]$Prohibited.Add('COMPLEX_PYTHON_C_TRANSPORT_REJECTED')
    }
    if($Name -match '^(powershell|powershell\.exe)$' -and ($Elements -contains '-Command')) {
        [void]$Prohibited.Add('NESTED_CHILD_COMMAND_REJECTED')
    }
    if($Command.InvocationOperator -eq [System.Management.Automation.Language.TokenKind]::Ampersand) {
        $First=$Command.CommandElements[0]
        if($First -is [System.Management.Automation.Language.VariableExpressionAst]) {
            [void]$Prohibited.Add('DYNAMIC_PARENT_SESSION_SCRIPT_EXECUTION_REJECTED')
        }
    }
}
if(@($Prohibited | Select-Object -Unique).Length -ne 0) {
    throw ('PROHIBITED_EXECUTABLE_SURFACE=' + ((@($Prohibited | Select-Object -Unique)) -join ','))
}

$Zero=@().Length
$One=@([pscustomobject]@{value=1}).Length
$Many=@(1,2,3).Length
if($Zero -ne 0 -or $One -ne 1 -or $Many -ne 3) { throw 'ZERO_ONE_MANY_FIXTURE_FAILED' }
$StrictFailure=$false
try { $null=([pscustomobject]@{}).MissingProperty }
catch { $StrictFailure=$true }
if(-not $StrictFailure) { throw 'STRICTMODE_MISSING_PROPERTY_DID_NOT_FAIL' }

$Child="$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$PlannedActionArgv=@(
    $Child,'-NoLogo','-NoProfile','-ExecutionPolicy','Bypass','-File',$TargetScriptPath,
    '-ActionSpecPath',$ActionSpecPath,'-ExpectedActionSpecSha256',$ExpectedActionSpecSha256
)
$ProbeContract=@(
    $Child,'-NoLogo','-NoProfile','-ExecutionPolicy','Bypass','-File',$PSCommandPath,
    '-ActionId',$ActionId,'-ActionRevision',$ActionRevision,'-ExecutionId',$ExecutionId,
    '-TargetScriptPath',$TargetScriptPath,'-ExpectedTargetScriptSha256',$ExpectedTargetScriptSha256,
    '-ActionSpecPath',$ActionSpecPath,'-ExpectedActionSpecSha256',$ExpectedActionSpecSha256,
    '-OutputPath',$OutputPath
)

$CurrentnessLines=@(
    "action_id=$ActionId",
    "action_revision=$ActionRevision",
    "execution_id=$ExecutionId",
    "powershell_edition=$($PSVersionTable.PSEdition)",
    "powershell_major=$($PSVersionTable.PSVersion.Major)",
    "effective_execution_policy=$(Get-ExecutionPolicy)",
    "language_mode=$($ExecutionContext.SessionState.LanguageMode)",
    "target_script_path=$TargetScriptPath",
    "target_script_sha256=$ExpectedTargetScriptSha256",
    "action_spec_path=$ActionSpecPath",
    "action_spec_sha256=$ExpectedActionSpecSha256",
    "planned_action_argv=$($PlannedActionArgv -join [char]31)",
    "probe_invocation_contract=$($ProbeContract -join [char]31)"
)
$CurrentnessText=($CurrentnessLines -join "`n")+"`n"

$Receipt=[ordered]@{
    schema_revision='R002'
    receipt_id='UR_PS51_FINAL_BOUNDARY_RECEIPT_R002'
    producer_id='UR_PS51_FINAL_BOUNDARY_PROBE_R002'
    producer_contract_revision='R002'
    action_id=$ActionId
    action_revision=$ActionRevision
    execution_id=$ExecutionId
    transport_family='WINDOWS_POWERSHELL_5_1'
    profile_id='PS51_SAFE_EXECUTION_PROFILE_R001'
    validation_result='PASS'
    proof_class='VALIDATED'
    parser_result='PASS'
    ast_safe_subset_result='PASS'
    runtime_semantic_fixture_result='PASS'
    cardinality=[ordered]@{zero='PASS';one_pscustomobject='PASS';many='PASS'}
    strict_mode=[ordered]@{missing_property_expected_failure='PASS';member_count_ast_absent=$true}
    host_observation=[ordered]@{
        proof_class='OBSERVED'
        powershell_edition=[string]$PSVersionTable.PSEdition
        powershell_major=[int]$PSVersionTable.PSVersion.Major
        effective_execution_policy=[string](Get-ExecutionPolicy)
        language_mode=[string]$ExecutionContext.SessionState.LanguageMode
    }
    probe_invocation_contract=[ordered]@{proof_class='VALIDATED';argv=$ProbeContract}
    planned_action=[ordered]@{proof_class='DECLARED';argv=$PlannedActionArgv}
    entrypoint=[ordered]@{path=$TargetScriptPath;bytes=[int64](Get-Item -LiteralPath $TargetScriptPath).Length;sha256=$ExpectedTargetScriptSha256}
    action_spec=[ordered]@{path=$ActionSpecPath;bytes=[int64](Get-Item -LiteralPath $ActionSpecPath).Length;sha256=$ExpectedActionSpecSha256}
    prohibited_primary_transport=[ordered]@{
        browser_download_discovery=$false
        file_picker=$false
        complex_python_c=$false
        session_history=$false
        nested_child_command=$false
        long_multiline_paste=$false
    }
    currentness_ref='PS51_FINAL_BOUNDARY_CURRENTNESS_R002'
    currentness_lines=$CurrentnessLines
    currentness_sha256=(Get-TextSha256 $CurrentnessText)
}

$Json=($Receipt | ConvertTo-Json -Depth 20)
[IO.File]::WriteAllText($OutputPath,$Json+"`n",(New-Object Text.UTF8Encoding($false)))
