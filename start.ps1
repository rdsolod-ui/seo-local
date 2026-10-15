$ErrorActionPreference = 'Stop'
& python (Join-Path $PSScriptRoot 'launch.py')
exit $LASTEXITCODE
