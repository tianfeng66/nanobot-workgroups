Option Explicit
Dim appShell, appFiles, appRoot, appPython, appLauncher
Set appShell = CreateObject("WScript.Shell")
Set appFiles = CreateObject("Scripting.FileSystemObject")
appRoot = appFiles.GetParentFolderName(WScript.ScriptFullName)
appPython = appRoot & "\.venv\Scripts\pythonw.exe"
appLauncher = appRoot & "\scripts\desktop_launcher.py"
If Not appFiles.FileExists(appPython) Then
  MsgBox "Please run install.cmd once before opening this application.", 48, "nanobot"
  WScript.Quit 1
End If
appShell.Run Chr(34) & appPython & Chr(34) & " " & Chr(34) & appLauncher & Chr(34), 0, False
