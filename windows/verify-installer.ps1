param(
    [string]$InstallerPath
)

$ErrorActionPreference = "Stop"
$expectedVersion = "0.3.0.0"

$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$installer = if ([string]::IsNullOrWhiteSpace($InstallerPath)) {
    Join-Path $project "Forwarder-Windows-0.3.0-Test-Setup.exe"
} else {
    [IO.Path]::GetFullPath($InstallerPath)
}
$built = Join-Path $project "Forwarder.exe"
$installed = Join-Path $env:LOCALAPPDATA "XXZF\Forwarder\Forwarder.exe"

foreach ($path in @($installer, $built)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Verification input is missing: $path"
    }
}

$process = Start-Process -FilePath $installer -ArgumentList "/Q" -Wait -PassThru
if ($process.ExitCode -ne 0) {
    throw "Installer exited with code $($process.ExitCode)"
}

Start-Sleep -Seconds 3
$receiver = Get-Process -Name "Forwarder" -ErrorAction SilentlyContinue | Where-Object {
    try { [IO.Path]::GetFullPath($_.Path) -eq [IO.Path]::GetFullPath($installed) }
    catch { $false }
} | Select-Object -First 1
$task = Get-ScheduledTask -TaskName "XXZF Forwarder" -ErrorAction SilentlyContinue
if (-not $receiver -or -not $task -or $task.State -ne "Running") {
    throw "Installed receiver is not running"
}

$builtHash = (Get-FileHash $built -Algorithm SHA256).Hash
$installedHash = (Get-FileHash $installed -Algorithm SHA256).Hash
if ($builtHash -ne $installedHash) {
    throw "Installed executable hash mismatch"
}
$installedVersion = [Diagnostics.FileVersionInfo]::GetVersionInfo($installed).FileVersion
if ($installedVersion -ne $expectedVersion) {
    throw "Installed executable version mismatch: $installedVersion"
}

@("XXZF Capture UI", "XXZF Invoke UI", "XXZF Click UI") | ForEach-Object {
    Unregister-ScheduledTask -TaskName $_ -Confirm:$false -ErrorAction SilentlyContinue
}

Write-Host "VERIFY_OK PID=$($receiver.Id) TASK=$($task.State) SHA256=$installedHash"
