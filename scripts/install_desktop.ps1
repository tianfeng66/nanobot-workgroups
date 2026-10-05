param([string]$DesktopDirectory = [Environment]::GetFolderPath('Desktop'), [switch]$NoProtocol)
$ErrorActionPreference = 'Stop'
$desktopInstallRoot = Split-Path -Parent $PSScriptRoot
$desktopPython = Join-Path $desktopInstallRoot '.venv\Scripts\pythonw.exe'
$desktopLauncher = Join-Path $desktopInstallRoot 'scripts\desktop_launcher.py'
if (-not (Test-Path -LiteralPath $desktopPython)) { throw 'Run install.cmd before creating the desktop entry.' }
if (-not $DesktopDirectory -or -not [IO.Path]::IsPathRooted($DesktopDirectory)) { throw 'An absolute desktop directory is required.' }
New-Item -ItemType Directory -Path $DesktopDirectory -Force | Out-Null
if (-not ('NanobotDesktop.Shortcut' -as [type])) {
    Add-Type -Path (Join-Path $PSScriptRoot 'desktop_shortcut.cs')
}
[NanobotDesktop.Shortcut]::Save((Join-Path $DesktopDirectory 'nanobot 个人工作台.lnk'), $desktopPython,
    ('"' + $desktopLauncher + '"'), $desktopInstallRoot, (Join-Path $desktopInstallRoot 'nanobot\workgroups\icon-transparent.ico'))
if (-not $NoProtocol) {
    $desktopProtocol = 'HKCU:\Software\Classes\nanobot-workgroups'
    New-Item -Path ($desktopProtocol + '\shell\open\command') -Force | Out-Null
    Set-Item -LiteralPath $desktopProtocol -Value 'URL:nanobot Workgroups'
    New-ItemProperty -LiteralPath $desktopProtocol -Name 'URL Protocol' -Value '' -PropertyType String -Force | Out-Null
    Set-Item -LiteralPath ($desktopProtocol + '\shell\open\command') -Value ('"' + $desktopPython + '" "' + $desktopLauncher + '" "%1"')
}
Write-Host 'Desktop entry installed.'
