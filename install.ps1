param([switch]$Dev, [switch]$ToolsOnly)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64') {
    throw 'This installer supports Windows x64. Windows ARM64 is not supported yet.'
}
$installRoot = $PSScriptRoot
$installCache = Join-Path $installRoot '.uv-cache'
$installBin = Join-Path $installRoot 'bin'
$installPythonHome = Join-Path $installRoot '.python'
$installTemp = Join-Path $installRoot 'personal-data\tmp'
foreach ($installDirectory in @($installCache, $installBin, $installPythonHome, $installTemp)) {
    New-Item -ItemType Directory -Path $installDirectory -Force | Out-Null
}
$env:UV_CACHE_DIR = $installCache
$env:UV_PYTHON_INSTALL_DIR = $installPythonHome
$env:UV_PYTHON_BIN_DIR = $installBin
$env:UV_NO_MODIFY_PATH = '1'
$env:TEMP = $installTemp
$env:TMP = $installTemp
$env:PYTHONUTF8 = '1'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Add-Type -AssemblyName System.IO.Compression.FileSystem
$installManifest = Get-Content -LiteralPath (Join-Path $installRoot 'scripts\windows-tools.json') -Raw | ConvertFrom-Json
foreach ($installTool in $installManifest.tools) {
    $installArchive = Join-Path $installCache ($installTool.name + '-' + $installTool.version + '.zip')
    $installArchiveValid = (Test-Path -LiteralPath $installArchive) -and ((Get-FileHash -LiteralPath $installArchive -Algorithm SHA256).Hash.ToLowerInvariant() -eq $installTool.sha256)
    if (-not $installArchiveValid) {
        Write-Host "Downloading $($installTool.name) $($installTool.version)..."
        $installPartial = $installArchive + '.partial'
        $downloadParameters = @{ Uri=$installTool.url; OutFile=$installPartial; UseBasicParsing=$true; TimeoutSec=180 }
        if ($env:HTTPS_PROXY) { $downloadParameters.Proxy = $env:HTTPS_PROXY }
        Invoke-WebRequest @downloadParameters
        if ((Get-FileHash -LiteralPath $installPartial -Algorithm SHA256).Hash.ToLowerInvariant() -ne $installTool.sha256) {
            throw "Checksum mismatch: $installPartial. Run install.cmd again to download a fresh archive."
        }
        Move-Item -LiteralPath $installPartial -Destination $installArchive -Force
    }
    $installDestination = Join-Path $installBin $installTool.output
    $installZip = [IO.Compression.ZipFile]::OpenRead($installArchive)
    try {
        $installEntry = @($installZip.Entries | Where-Object { $_.Name -eq $installTool.entry })
        if ($installEntry.Count -ne 1) { throw "Expected executable missing: $($installTool.entry)" }
        # Extract only the explicitly named executable, never arbitrary ZIP paths.
        if (-not (Test-Path -LiteralPath $installDestination)) {
            [IO.Compression.ZipFileExtensions]::ExtractToFile($installEntry[0], $installDestination, $false)
        } else {
            $entryStream = $installEntry[0].Open()
            $entryHasher = [Security.Cryptography.SHA256]::Create()
            try { $expectedExecutableHash = [BitConverter]::ToString($entryHasher.ComputeHash($entryStream)).Replace('-', '').ToLowerInvariant() }
            finally { $entryStream.Dispose(); $entryHasher.Dispose() }
            if ((Get-FileHash -LiteralPath $installDestination -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedExecutableHash) {
                [IO.Compression.ZipFileExtensions]::ExtractToFile($installEntry[0], $installDestination, $true)
            }
        }
    } finally { $installZip.Dispose() }
}
if ($ToolsOnly) { Write-Host 'CLI installation complete.'; exit 0 }
$installUv = Join-Path $installBin 'uv.exe'
$installVenv = Join-Path $installRoot '.venv'
$installPython = Join-Path $installVenv 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $installPython)) {
    & $installUv python install $installManifest.python
    if ($LASTEXITCODE -ne 0) { throw 'Python download failed.' }
    & $installUv venv --python $installManifest.python $installVenv
    if ($LASTEXITCODE -ne 0) { throw 'Python environment creation failed.' }
}
$installArguments = @('pip', 'install', '--python', $installPython, '--constraint', (Join-Path $installRoot 'requirements-windows.txt'), '-e', $installRoot)
if ($Dev) { $installArguments += @('pytest', 'pytest-asyncio', 'ruff') }
& $installUv @installArguments
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
$env:NANOBOT_HOME = Join-Path $installRoot 'personal-data'
& $installPython (Join-Path $installRoot 'scripts\setup_personal.py')
if ($LASTEXITCODE -ne 0) { throw 'Configuration setup failed.' }
Write-Host 'Installed. Run login-codex.cmd or login-opencode.cmd, then start.cmd.'
