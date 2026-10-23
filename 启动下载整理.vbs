' Start DownloadMover.ps1 without a console window. Any argument = start hidden in tray.
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
extra = ""
If WScript.Arguments.Count > 0 Then extra = " -Tray"
cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -STA -WindowStyle Hidden -File """ & dir & "\DownloadMover.ps1""" & extra
CreateObject("WScript.Shell").Run cmd, 0, False
