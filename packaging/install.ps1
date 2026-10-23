param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'MultiCAD'),
    [string]$Python = 'python'
)
$ErrorActionPreference = 'Stop'
try {
    & $Python -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) and sys.maxsize > 2**32 else 1)'
    if ($LASTEXITCODE -ne 0) { throw 'Unsupported Python' }
} catch {
    throw 'Install 64-bit Python 3.11 or newer, then rerun with -Python C:\path\python.exe. See https://www.python.org/downloads/windows/'
}
$env:PYTHONUTF8 = '1'
& $Python (Join-Path $PSScriptRoot 'bootstrap.py') --root $InstallDir
if ($LASTEXITCODE -ne 0) { throw 'Installation failed. The existing active version is retained; inspect the reported local log.' }
Write-Host 'Next: run launch.ps1 setup in your installation directory. CAD is not started by this installer.'
