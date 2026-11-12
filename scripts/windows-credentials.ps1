# Native Windows Credential Manager. This file contains code only, never secrets.
if ($env:OS -ne 'Windows_NT') {
    throw 'O armazenamento de credenciais do M Vision requer Windows.'
}

if (-not ('MVision.Security.WindowsCredentialStore' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Security;

namespace MVision.Security {
    public static class WindowsCredentialStore {
        private const UInt32 Generic = 1;
        private const UInt32 LocalMachine = 2; // Current user, this computer only.
        private const int NotFound = 1168;
        private const int MaxBlobBytes = 2560;

        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        private struct Credential {
            public UInt32 Flags;
            public UInt32 Type;
            [MarshalAs(UnmanagedType.LPWStr)] public string TargetName;
            [MarshalAs(UnmanagedType.LPWStr)] public string Comment;
            public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
            public UInt32 CredentialBlobSize;
            public IntPtr CredentialBlob;
            public UInt32 Persist;
            public UInt32 AttributeCount;
            public IntPtr Attributes;
            [MarshalAs(UnmanagedType.LPWStr)] public string TargetAlias;
            [MarshalAs(UnmanagedType.LPWStr)] public string UserName;
        }

        [DllImport("advapi32.dll", EntryPoint="CredWriteW", CharSet=CharSet.Unicode, ExactSpelling=true, SetLastError=true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool CredWrite(ref Credential credential, UInt32 flags);

        [DllImport("advapi32.dll", EntryPoint="CredReadW", CharSet=CharSet.Unicode, ExactSpelling=true, SetLastError=true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool CredRead(string target, UInt32 type, UInt32 flags, out IntPtr credential);

        [DllImport("advapi32.dll", EntryPoint="CredDeleteW", CharSet=CharSet.Unicode, ExactSpelling=true, SetLastError=true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool CredDelete(string target, UInt32 type, UInt32 flags);

        [DllImport("advapi32.dll", ExactSpelling=true)]
        private static extern void CredFree(IntPtr buffer);

        private static void ValidateTarget(string target) {
            if (target != "M_Vision/AISStream" &&
                !System.Text.RegularExpressions.Regex.IsMatch(target ?? "", "^M_Vision/CredentialTest-[a-f0-9]{32}$"))
                throw new ArgumentException("Destino de credencial invalido para o M Vision.");
        }

        public static void Write(string target, SecureString secret) {
            ValidateTarget(target);
            if (secret == null || secret.Length == 0)
                throw new ArgumentException("Informe uma chave de 1 a 1280 caracteres.");
            IntPtr blob = Marshal.SecureStringToBSTR(secret);
            try {
                int start = 0;
                int end = secret.Length;
                while (start < end && char.IsWhiteSpace((char)(ushort)Marshal.ReadInt16(blob, start * 2))) start++;
                while (end > start && char.IsWhiteSpace((char)(ushort)Marshal.ReadInt16(blob, (end - 1) * 2))) end--;
                int length = end - start;
                if (length == 0 || length * 2 > MaxBlobBytes)
                    throw new ArgumentException("Informe uma chave de 1 a 1280 caracteres. Cole somente o valor da chave.");
                for (int i = start; i < end; i++) {
                    char c = (char)(ushort)Marshal.ReadInt16(blob, i * 2);
                    if (c == '\u0016')
                        throw new ArgumentException("O terminal recebeu Ctrl+V como caractere, em vez de colar a chave. Copie a chave e execute .\\save-aisstream-key.ps1 -Clipboard.");
                    if (char.IsWhiteSpace(c) || char.IsControl(c))
                        throw new ArgumentException("A chave contem espacos internos ou caracteres de controle. Copie somente o valor da chave, sem rotulos ou comandos.");
                }
                Credential credential = new Credential();
                credential.Type = Generic;
                credential.TargetName = target;
                credential.Comment = "M Vision - AISStream API key";
                credential.CredentialBlobSize = (UInt32)(length * 2);
                credential.CredentialBlob = IntPtr.Add(blob, start * 2);
                credential.Persist = LocalMachine;
                credential.UserName = "AISStream";
                if (!CredWrite(ref credential, 0))
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "Nao foi possivel salvar a credencial do M Vision no Windows.");
            } finally {
                Marshal.ZeroFreeBSTR(blob);
            }
        }

        public static SecureString Read(string target) {
            ValidateTarget(target);
            IntPtr pointer;
            if (!CredRead(target, Generic, 0, out pointer)) {
                int error = Marshal.GetLastWin32Error();
                if (error == NotFound) return null;
                throw new Win32Exception(error, "Nao foi possivel ler a credencial do M Vision no Windows.");
            }
            Credential credential = new Credential();
            SecureString secret = new SecureString();
            try {
                credential = (Credential)Marshal.PtrToStructure(pointer, typeof(Credential));
                int size = (int)credential.CredentialBlobSize;
                if (size == 0 || size > MaxBlobBytes || size % 2 != 0 || credential.CredentialBlob == IntPtr.Zero)
                    throw new InvalidOperationException("Credencial do M Vision invalida; salve uma nova chave.");
                for (int i = 0; i < size; i += 2)
                    secret.AppendChar((char)(ushort)Marshal.ReadInt16(credential.CredentialBlob, i));
                secret.MakeReadOnly();
                return secret;
            } catch {
                secret.Dispose();
                throw;
            } finally {
                if (credential.CredentialBlob != IntPtr.Zero && credential.CredentialBlobSize <= MaxBlobBytes)
                    for (int i = 0; i < credential.CredentialBlobSize; i++)
                        Marshal.WriteByte(credential.CredentialBlob, i, 0);
                CredFree(pointer);
            }
        }

        public static bool Delete(string target) {
            ValidateTarget(target);
            if (CredDelete(target, Generic, 0)) return true;
            int error = Marshal.GetLastWin32Error();
            if (error == NotFound) return false;
            throw new Win32Exception(error, "Nao foi possivel remover a credencial do M Vision no Windows.");
        }
    }
}
'@
}

function Read-MVisionApiKey {
    param([string]$Prompt = 'Chave AISStream (entrada oculta)', [switch]$FromClipboard)
    if ($FromClipboard) {
        $clipboardText = $null
        try {
            $clipboardText = Get-Clipboard -Raw -ErrorAction Stop
            if ([string]::IsNullOrWhiteSpace($clipboardText)) {
                throw 'A area de transferencia esta vazia. Copie somente o valor da chave e tente novamente.'
            }
            return ConvertTo-SecureString -String $clipboardText -AsPlainText -Force
        } finally {
            $clipboardText = $null
        }
    }
    $secret = Read-Host $Prompt -AsSecureString
    $pointer = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
    try {
        for ($i = 0; $i -lt $secret.Length; $i++) {
            if ([System.Runtime.InteropServices.Marshal]::ReadInt16($pointer, $i * 2) -eq 22) {
                $secret.Dispose()
                throw 'O terminal recebeu Ctrl+V como caractere, em vez de colar a chave. Copie a chave e execute .\save-aisstream-key.ps1 -Clipboard.'
            }
        }
    } finally {
        [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
    return $secret
}
