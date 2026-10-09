param([Parameter(Mandatory=$true)][string[]]$Args)
$env:PYTHONPATH = "$PSScriptRoot\..\src" + ($(if ($env:PYTHONPATH) { ";$env:PYTHONPATH" } else { "" }))
python -m universal_runtime.devtools.acceptance_cli @Args
