[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $ManagerArguments
)

$ErrorActionPreference = 'Stop'
$manager = Join-Path $PSScriptRoot 'scripts/manage.py'
$requirements = Join-Path $PSScriptRoot 'requirements.txt'
$venv = Join-Path $PSScriptRoot '.venv'
$venvPython = Join-Path $venv 'Scripts/python.exe'

if ($PSVersionTable.PSEdition -ne 'Core' -or $PSVersionTable.PSVersion.Major -lt 7) {
    throw 'codex-config requires PowerShell 7 or newer.'
}

$python = Get-Command python -ErrorAction SilentlyContinue
$launcher = Get-Command py -ErrorAction SilentlyContinue
if (-not $python -and -not $launcher) {
    throw 'Python 3.11 or newer is required and was not found on PATH.'
}

$needsCrypto = $ManagerArguments.Count -gt 0 -and
    $ManagerArguments[0] -in @('install', 'capture', 'update') -and
    '-DryRun' -notin $ManagerArguments -and '--dry-run' -notin $ManagerArguments

if ($needsCrypto) {
    if (-not (Test-Path -LiteralPath $venvPython)) {
        if ($python) {
            & $python.Source -m venv $venv
        } else {
            & $launcher.Source -3 -m venv $venv
        }
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the project Python environment.' }
    }
    $installedVersion = & $venvPython -c 'import importlib.metadata; print(importlib.metadata.version("pyrage"))' 2>$null
    if ($LASTEXITCODE -ne 0 -or $installedVersion -ne '1.4.0') {
        & $venvPython -m pip install --disable-pip-version-check -r $requirements
        if ($LASTEXITCODE -ne 0) { throw 'Could not install the project Python dependency.' }
    }
}

if (Test-Path -LiteralPath $venvPython) {
    & $venvPython $manager @ManagerArguments
} elseif ($python) {
    & $python.Source $manager @ManagerArguments
} else {
    & $launcher.Source -3 $manager @ManagerArguments
}
exit $LASTEXITCODE
