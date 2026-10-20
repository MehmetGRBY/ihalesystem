$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# WScript.Shell converts some Turkish characters to ANSI. IShellLinkW and
# IPersistFile preserve Unicode in the shortcut name, target and arguments.
# https://learn.microsoft.com/en-us/windows/win32/shell/links
Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Text;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;

[ComImport, Guid("00021401-0000-0000-C000-000000000046")]
internal class ShellLink { }

[ComImport, Guid("000214F9-0000-0000-C000-000000000046"),
 InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
internal interface IShellLinkW {
    void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder path, int size, IntPtr data, uint flags);
    void GetIDList(out IntPtr idList);
    void SetIDList(IntPtr idList);
    void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder text, int size);
    void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string text);
    void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder path, int size);
    void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string path);
    void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder text, int size);
    void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string text);
    void GetHotkey(out short key);
    void SetHotkey(short key);
    void GetShowCmd(out int command);
    void SetShowCmd(int command);
    void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder path, int size, out int index);
    void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string path, int index);
    void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string path, uint reserved);
    void Resolve(IntPtr window, uint flags);
    void SetPath([MarshalAs(UnmanagedType.LPWStr)] string path);
}

public static class IhaleDesktopShortcut {
    public static void Create(string path, string root, string arguments) {
        IShellLinkW link = (IShellLinkW)new ShellLink();
        try {
            IPersistFile file = (IPersistFile)link;
            if (File.Exists(path)) {
                file.Load(path, 0);
                StringBuilder directory = new StringBuilder(32768);
                StringBuilder description = new StringBuilder(1024);
                link.GetWorkingDirectory(directory, directory.Capacity);
                link.GetDescription(description, description.Capacity);
                if (!String.Equals(directory.ToString(), root, StringComparison.OrdinalIgnoreCase) &&
                    description.ToString() != "IhaleSystem masaustu baslaticisi") {
                    throw new IOException("Masaustunde ayni isimli baska bir kisayol var; korunuyor.");
                }
            }
            link.SetPath(Path.Combine(root, @".venv\Scripts\pythonw.exe"));
            link.SetArguments(arguments);
            link.SetWorkingDirectory(root);
            link.SetDescription("IhaleSystem masaustu baslaticisi");
            link.SetShowCmd(7);
            file.Save(path, true);
        }
        finally { Marshal.FinalReleaseComObject(link); }
    }
}
'@

$desktop = if ($env:IHALE_SHORTCUT_DESKTOP) { $env:IHALE_SHORTCUT_DESKTOP } else {
    [Environment]::GetFolderPath('Desktop')
}
$path = Join-Path $desktop 'İhale Bulucu.lnk'
[IhaleDesktopShortcut]::Create($path, $env:IHALE_SHORTCUT_ROOT, $env:IHALE_SHORTCUT_ARGUMENTS)
[Console]::Write($path)
