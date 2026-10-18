param(
    [string]$JsonInputPath,
    [string]$JsonOutputPath,
    [string]$WorkspaceRoot,
    [string]$PythonPath,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$ImporterArgs
)
$ErrorActionPreference = 'Stop'
if ($JsonInputPath -or $JsonOutputPath) {
    if (-not $JsonInputPath -or -not $JsonOutputPath -or $ImporterArgs.Count -gt 0) { throw 'Supply both JSON paths and no importer arguments.' }
    if (-not $WorkspaceRoot) { throw 'Supply an explicit external WorkspaceRoot for JSON transport.' }
    & (Join-Path $PSScriptRoot 'scripts/write_json.ps1') -InputPath $JsonInputPath -OutputPath $JsonOutputPath -WorkspaceRoot $WorkspaceRoot
    exit 0
}
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONUTF8 = '1'
if (-not $PythonPath) {
    $bootstrap = Get-Command python -ErrorAction Stop
    $PythonPath = & $bootstrap.Source -B (Join-Path $PSScriptRoot 'scripts/setup.py') --print-python
    if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve the external environment. Supply -PythonPath explicitly.' }
}
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) { throw 'Run python -B scripts/setup.py first, or supply -PythonPath with runtime requirements installed.' }
& $PythonPath -B (Join-Path $PSScriptRoot 'scripts/importer.py') @ImporterArgs
exit $LASTEXITCODE
