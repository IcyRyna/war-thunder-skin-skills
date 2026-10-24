param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$runtime = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $runtime)) {
    & $Python -B -m venv (Join-Path $projectRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create Python environment' }
}
& $runtime -B -m pip install --timeout 120 -r (Join-Path $projectRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Failed to install project dependencies' }
$vendorRoot = Join-Path $projectRoot 'vendor\dagor-asset-explorer'
if (-not (Test-Path -LiteralPath (Join-Path $vendorRoot '.git'))) {
    & git clone 'https://github.com/quentin-dh/Dagor-Asset-Explorer.git' $vendorRoot
    if ($LASTEXITCODE -ne 0) { throw 'Failed to fetch Dagor decoder' }
}
& git -C $vendorRoot checkout '1f0d1e04ded04bf9b28e8d5be93cb79714f505d3'
if ($LASTEXITCODE -ne 0) { throw 'Failed to select the verified Dagor decoder revision' }
Write-Output "Ready: $runtime wt_assets.py --help"
