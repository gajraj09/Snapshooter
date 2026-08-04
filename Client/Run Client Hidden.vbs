Set shell = CreateObject("WScript.Shell")
Set filesystem = CreateObject("Scripting.FileSystemObject")
folder = filesystem.GetParentFolderName(WScript.ScriptFullName)
script = folder & "\client_pc_background.pyw"
shell.Run "pythonw.exe """ & script & """", 0, False
