$ErrorActionPreference = "Stop"
$resultPath = Join-Path $env:LOCALAPPDATA "XXZF\ui-click-result.txt"

try {
    Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;

public static class XXZFNative {
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern IntPtr FindWindow(string className, string windowName);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern IntPtr FindWindowEx(
        IntPtr parent, IntPtr childAfter, string className, string windowName);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int GetWindowText(IntPtr window, StringBuilder text, int maxCount);

    [DllImport("user32.dll")]
    public static extern IntPtr SendMessage(IntPtr window, uint message, IntPtr wParam, IntPtr lParam);
}
"@

    $windowName = -join @([char]0x8F6C, [char]0x53D1)
    $buttonName = -join @(
        [char]0x8FDE, [char]0x63A5, [char]0x53E6, [char]0x4E00,
        [char]0x53F0, [char]0x624B, [char]0x673A
    )
    $window = [XXZFNative]::FindWindow($null, $windowName)
    if ($window -eq [IntPtr]::Zero) { throw "Forwarder window was not found" }

    function Find-Button([IntPtr]$parent, [string]$expected) {
        $after = [IntPtr]::Zero
        while ($true) {
            $child = [XXZFNative]::FindWindowEx($parent, $after, $null, $null)
            if ($child -eq [IntPtr]::Zero) { break }
            $text = New-Object System.Text.StringBuilder 256
            $null = [XXZFNative]::GetWindowText($child, $text, $text.Capacity)
            if ($text.ToString() -eq $expected) { return $child }
            $nested = Find-Button $child $expected
            if ($nested -ne [IntPtr]::Zero) { return $nested }
            $after = $child
        }
        return [IntPtr]::Zero
    }

    $button = Find-Button $window $buttonName
    if ($button -eq [IntPtr]::Zero) { throw "Forwarder button was not found" }
    $null = [XXZFNative]::SendMessage($button, 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero)
    Set-Content -Path $resultPath -Value "OK" -Encoding UTF8
} catch {
    Set-Content -Path $resultPath -Value $_.Exception.ToString() -Encoding UTF8
    throw
}
