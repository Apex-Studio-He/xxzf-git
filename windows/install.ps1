$ErrorActionPreference = "Stop"
Set-StrictMode -Version 2.0

function Get-FullPath([string]$Path) {
    return [IO.Path]::GetFullPath($Path).TrimEnd([IO.Path]::DirectorySeparatorChar)
}

function Test-IsUnderPath([string]$Child, [string]$Parent) {
    $childPath = Get-FullPath $Child
    $parentPath = Get-FullPath $Parent
    $prefix = $parentPath + [IO.Path]::DirectorySeparatorChar
    return $childPath.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)
}

function Assert-NoReparsePoint([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $item = Get-Item -LiteralPath $Path -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "拒绝链接或重解析点路径: $Path"
    }
}

function Assert-NoReparsePath([string]$Base, [string]$Target) {
    $basePath = Get-FullPath $Base
    $targetPath = Get-FullPath $Target
    if ($targetPath -ne $basePath -and -not (Test-IsUnderPath $targetPath $basePath)) {
        throw "路径超出允许范围"
    }
    Assert-NoReparsePoint $basePath
    if ($targetPath -eq $basePath) { return }
    $relative = $targetPath.Substring($basePath.Length + 1)
    $current = $basePath
    foreach ($part in $relative.Split([IO.Path]::DirectorySeparatorChar)) {
        if ([string]::IsNullOrWhiteSpace($part)) { continue }
        $current = Join-Path $current $part
        Assert-NoReparsePoint $current
    }
}

function Set-PrivateAcl([string]$Path, [bool]$IsDirectory) {
    $userSid = [Security.Principal.WindowsIdentity]::GetCurrent().User
    $systemSid = New-Object Security.Principal.SecurityIdentifier("S-1-5-18")
    if ($null -eq $userSid) { throw "无法取得当前用户标识" }

    if ($IsDirectory) {
        $security = New-Object Security.AccessControl.DirectorySecurity
        $inheritance = [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor `
            [Security.AccessControl.InheritanceFlags]::ObjectInherit
    }
    else {
        $security = New-Object Security.AccessControl.FileSecurity
        $inheritance = [Security.AccessControl.InheritanceFlags]::None
    }
    $security.SetAccessRuleProtection($true, $false)
    $security.SetOwner($userSid)
    foreach ($sid in @($userSid, $systemSid)) {
        $rule = New-Object Security.AccessControl.FileSystemAccessRule(
            $sid,
            [Security.AccessControl.FileSystemRights]::FullControl,
            $inheritance,
            [Security.AccessControl.PropagationFlags]::None,
            [Security.AccessControl.AccessControlType]::Allow)
        [void]$security.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $Path -AclObject $security
}

function Ensure-PrivateDirectory([string]$Path, [string]$AllowedRoot) {
    $fullPath = Get-FullPath $Path
    $rootPath = Get-FullPath $AllowedRoot
    if ($fullPath -ne $rootPath -and -not (Test-IsUnderPath $fullPath $rootPath)) {
        throw "目标目录超出固定安装范围"
    }
    Assert-NoReparsePath $rootPath $fullPath
    if (-not (Test-Path -LiteralPath $fullPath)) {
        New-Item -Path $fullPath -ItemType Directory -Force | Out-Null
    }
    Assert-NoReparsePath $rootPath $fullPath
    Set-PrivateAcl $fullPath $true
}

function Get-ExpectedPayload([string]$ManifestPath) {
    Assert-NoReparsePoint $ManifestPath
    $manifestItem = Get-Item -LiteralPath $ManifestPath
    if ($manifestItem.Length -gt 1024) { throw "Payload 哈希清单过大" }
    $expected = @{}
    foreach ($line in [IO.File]::ReadAllLines($ManifestPath, [Text.Encoding]::ASCII)) {
        if ($line -notmatch '^(Forwarder\.exe|Forwarder\.ico)\|([0-9]{1,10})\|([A-F0-9]{64})$') {
            throw "Payload 哈希清单格式无效"
        }
        if ($expected.ContainsKey($Matches[1])) { throw "Payload 哈希清单包含重复项" }
        $expected[$Matches[1]] = @{
            Size = [Int64]::Parse($Matches[2], [Globalization.CultureInfo]::InvariantCulture)
            Hash = $Matches[3]
        }
    }
    if ($expected.Count -ne 2 -or -not $expected.ContainsKey("Forwarder.exe") `
        -or -not $expected.ContainsKey("Forwarder.ico")) {
        throw "Payload 哈希清单不完整"
    }
    return $expected
}

function Assert-PayloadFile([string]$Path, [hashtable]$Expected, [Int64]$MaximumSize) {
    Assert-NoReparsePoint $Path
    $item = Get-Item -LiteralPath $Path
    if ($item.PSIsContainer -or $item.Length -ne $Expected.Size `
        -or $item.Length -lt 1 -or $item.Length -gt $MaximumSize) {
        throw "安装来源文件大小校验失败: $($item.Name)"
    }
    $hash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToUpperInvariant()
    if ($hash -cne $Expected.Hash) { throw "安装来源文件 SHA-256 校验失败: $($item.Name)" }
}

function Stop-InstalledForwarder([string]$ExpectedExe) {
    Stop-ScheduledTask -TaskName "XXZF Forwarder" -ErrorAction SilentlyContinue
    foreach ($process in Get-Process -Name "Forwarder" -ErrorAction SilentlyContinue) {
        try {
            if ((Get-FullPath $process.Path) -eq (Get-FullPath $ExpectedExe)) {
                Stop-Process -Id $process.Id -Force
            }
        }
        catch { }
    }
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        $running = $false
        foreach ($process in Get-Process -Name "Forwarder" -ErrorAction SilentlyContinue) {
            try { if ((Get-FullPath $process.Path) -eq (Get-FullPath $ExpectedExe)) { $running = $true } }
            catch { }
        }
        if (-not $running) { return }
        Start-Sleep -Milliseconds 250
    }
    throw "固定安装位置中的旧进程未能停止"
}

$source = Get-FullPath (Split-Path -Parent $MyInvocation.MyCommand.Path)
$tempRoots = @($env:TEMP, $env:TMP) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | `
    ForEach-Object { Get-FullPath $_ } | Select-Object -Unique
$allowedSource = $false
foreach ($tempRoot in $tempRoots) {
    if (Test-IsUnderPath $source $tempRoot) {
        Assert-NoReparsePath $tempRoot $source
        $allowedSource = $true
        break
    }
}
if (-not $allowedSource) { throw "安装来源必须位于当前用户的临时解压目录" }

$payloadManifest = Join-Path $source "payload.sha256"
$sourceExe = Join-Path $source "Forwarder.exe"
$sourceIcon = Join-Path $source "Forwarder.ico"
foreach ($path in @($MyInvocation.MyCommand.Path, $payloadManifest, $sourceExe, $sourceIcon)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "安装来源缺少固定文件" }
    Assert-NoReparsePoint $path
}

$expected = Get-ExpectedPayload $payloadManifest
Assert-PayloadFile $sourceExe $expected["Forwarder.exe"] (32MB)
Assert-PayloadFile $sourceIcon $expected["Forwarder.ico"] (2MB)

$localAppData = Get-FullPath $env:LOCALAPPDATA
$xxzfRoot = Get-FullPath (Join-Path $localAppData "XXZF")
$installDir = Get-FullPath (Join-Path $xxzfRoot "Forwarder")
$fixedInstallDir = Get-FullPath (Join-Path $env:LOCALAPPDATA "XXZF\Forwarder")
if ($installDir -ne $fixedInstallDir -or -not (Test-IsUnderPath $installDir $localAppData)) {
    throw "固定安装路径校验失败"
}

if (-not (Test-Path -LiteralPath $xxzfRoot)) {
    New-Item -Path $xxzfRoot -ItemType Directory -Force | Out-Null
}
Assert-NoReparsePath $localAppData $xxzfRoot
Set-PrivateAcl $xxzfRoot $true
Ensure-PrivateDirectory $installDir $xxzfRoot

$exe = Join-Path $installDir "Forwarder.exe"
$icon = Join-Path $installDir "Forwarder.ico"
$staging = Join-Path $installDir (".staging-" + [Guid]::NewGuid().ToString("N"))
$backupExe = Join-Path $installDir ".Forwarder.exe.previous"
$backupIcon = Join-Path $installDir ".Forwarder.ico.previous"
$taskName = "XXZF Forwarder"
$displayName = ([string][char]0x8F6C) + [char]0x53D1
$installed = $false

try {
    foreach ($path in @($installDir, $exe, $icon, $backupExe, $backupIcon)) {
        Assert-NoReparsePoint $path
    }
    Stop-InstalledForwarder $exe
    Ensure-PrivateDirectory $staging $installDir
    $stagedExe = Join-Path $staging "Forwarder.exe"
    $stagedIcon = Join-Path $staging "Forwarder.ico"
    Copy-Item -LiteralPath $sourceExe -Destination $stagedExe
    Copy-Item -LiteralPath $sourceIcon -Destination $stagedIcon
    Set-PrivateAcl $stagedExe $false
    Set-PrivateAcl $stagedIcon $false
    Assert-PayloadFile $stagedExe $expected["Forwarder.exe"] (32MB)
    Assert-PayloadFile $stagedIcon $expected["Forwarder.ico"] (2MB)

    Remove-Item -LiteralPath $backupExe, $backupIcon -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $exe) { Move-Item -LiteralPath $exe -Destination $backupExe }
    if (Test-Path -LiteralPath $icon) { Move-Item -LiteralPath $icon -Destination $backupIcon }
    Move-Item -LiteralPath $stagedExe -Destination $exe
    Move-Item -LiteralPath $stagedIcon -Destination $icon
    Set-PrivateAcl $exe $false
    Set-PrivateAcl $icon $false
    Assert-PayloadFile $exe $expected["Forwarder.exe"] (32MB)
    Assert-PayloadFile $icon $expected["Forwarder.ico"] (2MB)

    $shell = New-Object -ComObject WScript.Shell
    $startMenu = Join-Path $env:APPDATA ("Microsoft\Windows\Start Menu\Programs\" + $displayName + ".lnk")
    $shortcut = $shell.CreateShortcut($startMenu)
    $shortcut.TargetPath = $exe
    $shortcut.WorkingDirectory = $installDir
    $shortcut.IconLocation = "$icon,0"
    $shortcut.Description = "多设备通知接收端"
    $shortcut.Save()

    $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $action = New-ScheduledTaskAction -Execute $exe -WorkingDirectory $installDir
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity
    $principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
        -Principal $principal -Settings $settings -Force | Out-Null
    Start-ScheduledTask -TaskName $taskName

    Start-Sleep -Seconds 2
    $process = Get-Process -Name "Forwarder" -ErrorAction SilentlyContinue | Where-Object {
        try { (Get-FullPath $_.Path) -eq (Get-FullPath $exe) } catch { $false }
    } | Select-Object -First 1
    if ($null -eq $process) { throw "更新后的转发未能从固定路径启动" }
    $installed = $true
    Write-Host "INSTALL_OK PID=$($process.Id) PATH=$exe"
}
catch {
    try { Stop-InstalledForwarder $exe } catch { }
    Remove-Item -LiteralPath $exe, $icon -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $backupExe) { Move-Item -LiteralPath $backupExe -Destination $exe }
    if (Test-Path -LiteralPath $backupIcon) { Move-Item -LiteralPath $backupIcon -Destination $icon }
    if (Test-Path -LiteralPath $exe) {
        Set-PrivateAcl $exe $false
        if (Test-Path -LiteralPath $icon) { Set-PrivateAcl $icon $false }
        try { Start-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue } catch { }
    }
    throw
}
finally {
    Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
    if ($installed) {
        Remove-Item -LiteralPath $backupExe, $backupIcon -Force -ErrorAction SilentlyContinue
    }
}
