$ErrorActionPreference = "Stop"

$buildVariant = $env:XXZF_BUILD_VARIANT
if ([string]::IsNullOrWhiteSpace($buildVariant)) { $buildVariant = "Debug" }
if ($buildVariant -notin @("Debug", "Release")) {
    throw "XXZF_BUILD_VARIANT must be Debug or Release"
}

$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$output = Join-Path $project "Forwarder-Windows-0.3.0-Test-Setup.exe"
$sed = Join-Path $project "Forwarder-Setup.sed"
$payloadManifest = Join-Path $project "payload.sha256"
$iexpress = Join-Path $env:WINDIR "System32\iexpress.exe"

if (-not (Test-Path $iexpress)) {
    throw "IExpress is not available"
}

& (Join-Path $project "build.ps1")

$payloadLines = @()
foreach ($name in @("Forwarder.exe", "Forwarder.ico")) {
    $path = Join-Path $project $name
    $item = Get-Item -LiteralPath $path
    $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToUpperInvariant()
    $payloadLines += "$name|$($item.Length)|$hash"
}
[IO.File]::WriteAllLines($payloadManifest, $payloadLines, [Text.Encoding]::ASCII)

$source = $project
$target = $output
$content = @"
[Version]
Class=IEXPRESS
SEDVersion=3

[Options]
PackagePurpose=InstallApp
ShowInstallProgramWindow=0
HideExtractAnimation=1
UseLongFileName=1
InsideCompressed=0
CAB_FixedSize=0
CAB_ResvCodeSigning=0
RebootMode=N
InstallPrompt=%InstallPrompt%
DisplayLicense=%DisplayLicense%
FinishMessage=%FinishMessage%
TargetName=%TargetName%
FriendlyName=%FriendlyName%
AppLaunched=%AppLaunched%
PostInstallCmd=<None>
AdminQuietInstCmd=
UserQuietInstCmd=powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File install.ps1
SourceFiles=SourceFiles

[Strings]
InstallPrompt=
DisplayLicense=
FinishMessage=
TargetName=$target
FriendlyName=Forwarder Setup
AppLaunched=cmd.exe /c install.cmd
FILE0="Forwarder.exe"
FILE1="Forwarder.ico"
FILE2="install.ps1"
FILE3="install.cmd"
FILE4="payload.sha256"

[SourceFiles]
SourceFiles0=$source\

[SourceFiles0]
%FILE0%=
%FILE1%=
%FILE2%=
%FILE3%=
%FILE4%=
"@

try {
    [IO.File]::WriteAllText($sed, $content, [Text.Encoding]::Unicode)
    if (Test-Path $output) { Remove-Item $output -Force }
    $process = Start-Process -FilePath $iexpress -ArgumentList @("/N", "/Q", $sed) -Wait -PassThru
    if ($process.ExitCode -ne 0 -or -not (Test-Path $output)) {
        throw "Installer build failed"
    }
}
finally {
    Remove-Item -LiteralPath $payloadManifest -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $sed -Force -ErrorAction SilentlyContinue
}

if ($buildVariant -eq "Release") {
    & (Join-Path $project "sign-release.ps1") -Path $output
}

$item = Get-Item $output
$hash = (Get-FileHash $output -Algorithm SHA256).Hash
[IO.File]::WriteAllText("$output.sha256", "$hash  $($item.Name)`n", [Text.Encoding]::ASCII)
Write-Host "INSTALLER_OK PATH=$($item.FullName) SIZE=$($item.Length) SHA256=$hash"
