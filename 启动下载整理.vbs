' Start mover.py without a console window. Any argument = start hidden in tray.
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
extra = ""
If WScript.Arguments.Count > 0 Then extra = " --tray"
CreateObject("WScript.Shell").Run """" & dir & "\.venv\Scripts\pythonw.exe"" """ & dir & "\mover.py""" & extra, 0, False
