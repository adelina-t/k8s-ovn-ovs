param (
	[string]$sshKeyData,
	[string]$sshUser
)

# Variables
$cert = New-SelfSignedCertificate -DnsName (hostname) -CertStoreLocation Cert:\LocalMachine\My
$ssh_package = (Get-WindowsCapability -Online | ? Name -Like 'OpenSSH.Server*').Name
$ssh_config = "C:\ProgramData\ssh\sshd_config"

# Enable WinRM
winrm create winrm/config/Listener?Address=*+Transport=HTTPS "@{Hostname=`"$(hostname)`"; CertificateThumbprint=`"$($cert.Thumbprint)`"}"
winrm set winrm/config/service/auth "@{Basic=`"true`"}"

# Enable SSH
Add-WindowsCapability -Online -Name $ssh_package

# Start SSHD to create default config
Start-Service sshd
Set-Service -Name sshd -StartupType 'Automatic'

# Modify SSHD config
((Get-Content -path $ssh_config -Raw) -replace '#SyslogFacility AUTH','SyslogFacility LOCAL0') | Set-Content -Path $ssh_config
((Get-Content -path $ssh_config -Raw) -replace '#LogLevel INFO','LogLevel DEBUG3') | Set-Content -Path $ssh_config
((Get-Content -path $ssh_config -Raw) -replace 'Match Group administrators','') | Set-Content -Path $ssh_config
((Get-Content -path $ssh_config -Raw) -replace 'AuthorizedKeysFile __PROGRAMDATA__/ssh/administrators_authorized_keys','') | Set-Content -Path $ssh_config

# Set powershell as default ssh shell
New-ItemProperty -Path "HKLM:\SOFTWARE\OpenSSH" -Name DefaultShell -Value "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -PropertyType String -Force

# Restart SSHD to load new config
Restart-Service sshd

# Check under what user is this script running

function Register-NativeMethod
{
    [CmdletBinding()]
    [Alias()]
    [OutputType([int])]
    Param
    (
        # Param1 help description
        [Parameter(Mandatory=$true,
                   ValueFromPipelineByPropertyName=$true,
                   Position=0)]
        [string]$dll,
 
        # Param2 help description
        [Parameter(Mandatory=$true,
                   ValueFromPipelineByPropertyName=$true,
                   Position=1)]
        [string]
        $methodSignature
    )
 
    $script:nativeMethods += [PSCustomObject]@{ Dll = $dll; Signature = $methodSignature; }
}

function Add-NativeMethods
{
    [CmdletBinding()]
    [Alias()]
    [OutputType([int])]
    Param($typeName = 'NativeMethods')

    $nativeMethodsCode = $script:nativeMethods | ForEach-Object { "
        [DllImport(`"$($_.Dll)`")]
        public static extern $($_.Signature);
    " }

    Add-Type @"
        using System;
        using System.Text;
        using System.Runtime.InteropServices;
        public static class $typeName {
            $nativeMethodsCode
        }
"@
}

$methodName = 'UserEnvCP'
$script:nativeMethods = @();

Register-NativeMethod "userenv.dll" "int CreateProfile([MarshalAs(UnmanagedType.LPWStr)] string pszUserSid,`
  [MarshalAs(UnmanagedType.LPWStr)] string pszUserName,`
  [Out][MarshalAs(UnmanagedType.LPWStr)] StringBuilder pszProfilePath, uint cchProfilePath)";

Add-NativeMethods -typeName $MethodName;

$localUser = New-Object System.Security.Principal.NTAccount($sshUser);
$userSID = $localUser.Translate([System.Security.Principal.SecurityIdentifier]);
$sb = new-object System.Text.StringBuilder(260);
$pathLen = $sb.Capacity;

Write-Verbose "Creating user profile for $sshUser";
try
{
    [UserEnvCP]::CreateProfile($userSID.Value, $sshUser, $sb, $pathLen) | Out-Null;
}
catch
{
    Write-Error $_.Exception.Message;
    break;
}

#Copying ssh_key_data to user profile

mkdir "c:\Users\$sshUser\.ssh"
$sshKeyData | Out-File "c:\Users\$sshUser\.ssh\authorized_keys" -encoding utf8

# Add firewall rules
New-NetFirewallRule -Name winRM -Description "TCP traffic for WinRM" -Action Allow -LocalPort 5986 -Enabled True -DisplayName "WinRM Traffic" -Protocol TCP -ErrorAction SilentlyContinue
New-NetFirewallRule -Name SSH -Description "TCP traffic for SSH" -Action Allow -LocalPort 22 -Enabled True -DisplayName "SSH Traffic" -Protocol TCP -ErrorAction SilentlyContinue
