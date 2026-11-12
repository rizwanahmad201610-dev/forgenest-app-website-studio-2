' Double-click this on Windows. Starts the local website without showing Command Prompt.
Option Explicit
Dim sh, fso, root, program, cmd
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
On Error Resume Next
cmd = "pyw -3 """ & root & "\server.py" & """"
sh.Run cmd, 0, False
If Err.Number <> 0 Then
    Err.Clear
    cmd = "pythonw """ & root & "\server.py" & """"
    sh.Run cmd, 0, False
End If
On Error GoTo 0
WScript.Sleep 1600
sh.Run "http://127.0.0.1:8765/", 1, False
