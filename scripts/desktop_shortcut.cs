// Use the Unicode Shell interfaces so Chinese names work on English Windows too.
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Text;

namespace NanobotDesktop {
    [ComImport, Guid("00021401-0000-0000-C000-000000000046")]
    class ShellLink { }

    [ComImport, Guid("000214F9-0000-0000-C000-000000000046"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IShellLinkW {
        void GetPath([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder path, int count, IntPtr data, uint flags);
        void GetIDList(out IntPtr list);
        void SetIDList(IntPtr list);
        void GetDescription([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder value, int count);
        void SetDescription([MarshalAs(UnmanagedType.LPWStr)] string value);
        void GetWorkingDirectory([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder value, int count);
        void SetWorkingDirectory([MarshalAs(UnmanagedType.LPWStr)] string value);
        void GetArguments([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder value, int count);
        void SetArguments([MarshalAs(UnmanagedType.LPWStr)] string value);
        void GetHotkey(out short value);
        void SetHotkey(short value);
        void GetShowCmd(out int value);
        void SetShowCmd(int value);
        void GetIconLocation([Out, MarshalAs(UnmanagedType.LPWStr)] StringBuilder path, int count, out int index);
        void SetIconLocation([MarshalAs(UnmanagedType.LPWStr)] string path, int index);
        void SetRelativePath([MarshalAs(UnmanagedType.LPWStr)] string path, uint reserved);
        void Resolve(IntPtr window, uint flags);
        void SetPath([MarshalAs(UnmanagedType.LPWStr)] string path);
    }

    public static class Shortcut {
        public static void Save(string file, string target, string arguments, string directory, string icon) {
            IShellLinkW link = (IShellLinkW)new ShellLink();
            try {
                link.SetPath(target);
                link.SetArguments(arguments);
                link.SetWorkingDirectory(directory);
                link.SetDescription("nanobot personal workspace");
                link.SetIconLocation(icon, 0);
                ((IPersistFile)link).Save(file, true);
            } finally { Marshal.FinalReleaseComObject(link); }
        }

        public static Dictionary<string, string> Read(string file) {
            IShellLinkW link = (IShellLinkW)new ShellLink();
            try {
                ((IPersistFile)link).Load(file, 0);
                StringBuilder target = new StringBuilder(32768);
                StringBuilder arguments = new StringBuilder(32768);
                StringBuilder directory = new StringBuilder(32768);
                StringBuilder icon = new StringBuilder(32768);
                int iconIndex;
                link.GetPath(target, target.Capacity, IntPtr.Zero, 4);
                link.GetArguments(arguments, arguments.Capacity);
                link.GetWorkingDirectory(directory, directory.Capacity);
                link.GetIconLocation(icon, icon.Capacity, out iconIndex);
                return new Dictionary<string, string> {
                    {"target", target.ToString()}, {"arguments", arguments.ToString()}, {"directory", directory.ToString()}, {"icon", icon.ToString()}
                };
            } finally { Marshal.FinalReleaseComObject(link); }
        }
    }
}
