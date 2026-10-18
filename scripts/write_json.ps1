param(
    [Parameter(Mandatory = $true)][string]$InputPath,
    [Parameter(Mandatory = $true)][string]$OutputPath,
    [string]$WorkspaceRoot
)
$ErrorActionPreference = 'Stop'
if (-not $WorkspaceRoot) { throw 'Supply an explicit external WorkspaceRoot.' }
# Question contents never become PowerShell source or command arguments.
$sourceFile = (Resolve-Path -LiteralPath $InputPath).Path
$targetFile = [IO.Path]::GetFullPath($OutputPath)
$workspacePath = (Resolve-Path -LiteralPath $WorkspaceRoot).Path
if (-not (Test-Path -LiteralPath $workspacePath -PathType Container)) { throw 'WorkspaceRoot must be an existing directory.' }
$workspacePath = [IO.Path]::GetFullPath($workspacePath)
$runtimePath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')).TrimEnd([IO.Path]::DirectorySeparatorChar)
$runtimeBoundary = $runtimePath + [IO.Path]::DirectorySeparatorChar
if ($workspacePath.TrimEnd([IO.Path]::DirectorySeparatorChar) -eq $runtimePath -or $workspacePath.StartsWith($runtimeBoundary, [StringComparison]::OrdinalIgnoreCase) -or $targetFile.StartsWith($runtimeBoundary, [StringComparison]::OrdinalIgnoreCase)) { throw 'Transport output and workspace must be outside the skill installation.' }
if ($workspacePath.TrimEnd([IO.Path]::DirectorySeparatorChar) -eq [IO.Path]::GetPathRoot($workspacePath).TrimEnd([IO.Path]::DirectorySeparatorChar)) { throw 'A filesystem root cannot be a workspace.' }
$boundary = $workspacePath.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
if (-not $targetFile.StartsWith($boundary, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Transport output must be within the explicitly selected workspace.'
}
$cursorPath = $targetFile
while ($cursorPath -and $cursorPath -ne [IO.Path]::GetPathRoot($cursorPath)) {
    if (Test-Path -LiteralPath $cursorPath) {
        $item = Get-Item -LiteralPath $cursorPath -Force
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Linked output paths are forbidden.' }
    }
    $cursorPath = [IO.Path]::GetDirectoryName($cursorPath)
}
if (Test-Path -LiteralPath $targetFile) { throw 'Transport output already exists.' }
$bytes = [IO.File]::ReadAllBytes($sourceFile)
$strictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)
$text = $strictUtf8.GetString($bytes).TrimStart([char]0xFEFF)
$null = ConvertFrom-Json -InputObject $text -ErrorAction Stop
$parentPath = [IO.Path]::GetDirectoryName($targetFile)
if (-not (Test-Path -LiteralPath $parentPath)) { throw 'Create the output parent directory first.' }
$stagedPath = Join-Path $parentPath ('.json-transport-' + [Guid]::NewGuid().ToString('N') + '.tmp')
try {
    [IO.File]::WriteAllBytes($stagedPath, $bytes)
    [IO.File]::Move($stagedPath, $targetFile)
} finally {
    if (Test-Path -LiteralPath $stagedPath) { Remove-Item -LiteralPath $stagedPath }
}
Write-Output $targetFile
