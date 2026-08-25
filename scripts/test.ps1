$ErrorActionPreference = 'Stop'
$v2RepositoryRoot = Split-Path -Parent $PSScriptRoot
$v2Python = if ($env:PYTHON) { $env:PYTHON } else { 'python' }
$v2BundledGitBash = 'C:\Program Files\Git\bin\bash.exe'
$v2Bash = if ($env:BASH) {
    $env:BASH
}
elseif (Test-Path -LiteralPath $v2BundledGitBash) {
    $v2BundledGitBash
}
else {
    (Get-Command bash -ErrorAction Stop).Source
}

Push-Location (Join-Path $v2RepositoryRoot 'backend')
try {
    $env:PYTHONPATH = '.'
    & $v2Python -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed' }
    & $v2Python -m compileall -q app tests
    if ($LASTEXITCODE -ne 0) { throw 'Python compile check failed' }
}
finally {
    Pop-Location
}

Push-Location (Join-Path $v2RepositoryRoot 'frontend')
try {
    npm run check
    if ($LASTEXITCODE -ne 0) { throw 'Frontend type check failed' }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
}
finally {
    Pop-Location
}

Push-Location (Join-Path $v2RepositoryRoot 'skills')
try {
    $env:PYTHON = $v2Python
    & $v2Bash ./tests/run_smoke_tests.sh
    if ($LASTEXITCODE -ne 0) { throw 'Skill smoke tests failed' }
}
finally {
    Pop-Location
}

Write-Host 'All Hoosland-real-estate-research-toolset checks passed'
