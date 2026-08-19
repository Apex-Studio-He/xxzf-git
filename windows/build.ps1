$ErrorActionPreference = "Stop"

$buildVariant = $env:XXZF_BUILD_VARIANT
if ([string]::IsNullOrWhiteSpace($buildVariant)) { $buildVariant = "Debug" }
if ($buildVariant -notin @("Debug", "Release")) {
    throw "XXZF_BUILD_VARIANT must be Debug or Release"
}

$project = Split-Path -Parent $MyInvocation.MyCommand.Path
$compiler = "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if (-not (Test-Path $compiler)) {
    throw "C# compiler not found"
}

& $compiler `
    /nologo `
    /target:winexe `
    /platform:anycpu `
    /optimize+ `
    /codepage:65001 `
    "/win32manifest:$project\app.manifest" `
    "/out:$project\Forwarder.exe" `
    "/win32icon:$project\Forwarder.ico" `
    /reference:System.dll `
    /reference:System.Core.dll `
    /reference:System.Drawing.dll `
    /reference:System.Net.Http.dll `
    /reference:System.Security.dll `
    /reference:System.Web.Extensions.dll `
    /reference:System.Windows.Forms.dll `
    "$project\Forwarder.cs" `
    "$project\Updater.cs"

if ($LASTEXITCODE -ne 0) {
    throw "Build failed with exit code $LASTEXITCODE"
}

if ($buildVariant -eq "Release") {
    & (Join-Path $project "sign-release.ps1") -Path (Join-Path $project "Forwarder.exe")
}

Write-Host "BUILD_OK $project\Forwarder.exe"
