[CmdletBinding(PositionalBinding=$false)]
param(
    [switch]$Gateway,
    [string]$ConfigPath,
    [Parameter(Position=0,ValueFromRemainingArguments=$true)][string[]]$Arguments
)
$ErrorActionPreference = 'Stop'
$record = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'current.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$env:MULTI_CAD_HOME = $PSScriptRoot
$env:MULTI_CAD_WHEEL = $record.wheel
$env:PYTHONUTF8 = '1'
if (-not $ConfigPath) { $ConfigPath = Join-Path $PSScriptRoot 'config.json' }
if ($Gateway) {
    & $record.python -I -X utf8 -m multi_cad.gateway --config $ConfigPath
} else {
    & $record.python -I -X utf8 -m multi_cad --config $ConfigPath @Arguments
}
exit $LASTEXITCODE
