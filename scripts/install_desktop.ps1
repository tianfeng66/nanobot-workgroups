param([string]$DesktopDirectory = [Environment]::GetFolderPath('Desktop'), [switch]$NoProtocol)
$ErrorActionPreference = 'Stop'
$desktopInstallRoot = Split-Path -Parent $PSScriptRoot
$desktopPython = Join-Path $desktopInstallRoot '.venv\Scripts\pythonw.exe'
$desktopLauncher = Join-Path $desktopInstallRoot 'scripts\desktop_launcher.py'
if (-not (Test-Path -LiteralPath $desktopPython)) { throw 'Run install.cmd before creating the desktop entry.' }
$desktopShell = New-Object -ComObject WScript.Shell
$desktopShortcut = $desktopShell.CreateShortcut((Join-Path $DesktopDirectory 'nanobot 个人工作台.lnk'))
$desktopShortcut.TargetPath = $desktopPython
$desktopShortcut.Arguments = '"' + $desktopLauncher + '"'
$desktopShortcut.WorkingDirectory = $desktopInstallRoot
$desktopShortcut.Description = 'nanobot personal workspace'
$desktopShortcut.IconLocation = (Join-Path $env:SystemRoot 'System32\shell32.dll') + ',20'
$desktopShortcut.Save()
if (-not $NoProtocol) {
    $desktopProtocol = 'HKCU:\Software\Classes\nanobot-workgroups'
    New-Item -Path ($desktopProtocol + '\shell\open\command') -Force | Out-Null
    Set-Item -LiteralPath $desktopProtocol -Value 'URL:nanobot Workgroups'
    New-ItemProperty -LiteralPath $desktopProtocol -Name 'URL Protocol' -Value '' -PropertyType String -Force | Out-Null
    Set-Item -LiteralPath ($desktopProtocol + '\shell\open\command') -Value ('"' + $desktopPython + '" "' + $desktopLauncher + '" "%1"')
}
Write-Host 'Desktop entry installed.'
