param(
    [ValidateSet('Groups', 'Nanobot', 'CodexLogin', 'OpenCodeLogin', 'Doctor')]
    [string]$Mode = 'Groups',
    [int]$Port = 8877
)
$ErrorActionPreference = 'Stop'
$personalRoot = $PSScriptRoot
$personalData = Join-Path $personalRoot 'personal-data'
$personalPython = Join-Path $personalRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $personalPython)) { throw 'Run install.cmd before starting this application.' }
$env:NANOBOT_HOME = $personalData
$env:PYTHONUTF8 = '1'
$env:UV_CACHE_DIR = Join-Path $personalRoot '.uv-cache'
$env:TEMP = Join-Path $personalData 'tmp'
$env:TMP = $env:TEMP
$env:PIP_CACHE_DIR = Join-Path $personalData 'cache\pip'
$env:TIKTOKEN_CACHE_DIR = Join-Path $personalData 'cache\tiktoken'
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
& $personalPython (Join-Path $personalRoot 'scripts\setup_personal.py')
if ($LASTEXITCODE -ne 0) { throw 'Personal configuration initialization failed.' }
$personalConfig = Join-Path $personalData 'config.json'
if ($Mode -eq 'Nanobot') {
    & $personalPython -m nanobot agent --config $personalConfig
} else {
    $personalAction = @{ Groups = 'serve'; CodexLogin = 'codex-login'; OpenCodeLogin = 'opencode-login'; Doctor = 'doctor' }[$Mode]
    $personalArguments = @('-m', 'nanobot.workgroups', '--config', $personalConfig, $personalAction, '--port', $Port)
    if ($Mode -eq 'Groups') { $personalArguments += '--open-browser' }
    & $personalPython @personalArguments
}
exit $LASTEXITCODE
