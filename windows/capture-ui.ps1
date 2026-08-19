$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;

public static class XXZFMouse {
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }

    [DllImport("user32.dll")]
    public static extern bool SetCursorPos(int x, int y);

    [DllImport("user32.dll")]
    public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extraInfo);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern IntPtr FindWindow(string className, string windowName);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern IntPtr FindWindowEx(
        IntPtr parent, IntPtr childAfter, string className, string windowName);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int GetWindowText(IntPtr window, StringBuilder text, int maxCount);

    [DllImport("user32.dll")]
    public static extern IntPtr SendMessage(IntPtr window, uint message, IntPtr wParam, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr window, out RECT rect);
}
"@

$executable = Join-Path $env:LOCALAPPDATA "XXZF\Forwarder\Forwarder.exe"
Start-Process $executable
Start-Sleep -Seconds 2

$process = Get-Process Forwarder -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowHandle -ne 0 } |
    Select-Object -First 1
if ($process) {
    $shell = New-Object -ComObject WScript.Shell
    $null = $shell.AppActivate($process.Id)
    Start-Sleep -Seconds 1
}

$clickPairFlag = Join-Path $env:LOCALAPPDATA "XXZF\click-pair-next"
if (Test-Path $clickPairFlag) {
    Remove-Item $clickPairFlag -Force
    $windowName = -join @([char]0x8F6C, [char]0x53D1)
    $buttonName = -join @(
        [char]0x8FDE, [char]0x63A5, [char]0x53E6, [char]0x4E00,
        [char]0x53F0, [char]0x624B, [char]0x673A
    )
    $window = [XXZFMouse]::FindWindow($null, $windowName)

    function Find-Button([IntPtr]$parent, [string]$expected) {
        $after = [IntPtr]::Zero
        while ($true) {
            $child = [XXZFMouse]::FindWindowEx($parent, $after, $null, $null)
            if ($child -eq [IntPtr]::Zero) { break }
            $text = New-Object System.Text.StringBuilder 256
            $null = [XXZFMouse]::GetWindowText($child, $text, $text.Capacity)
            if ($text.ToString() -eq $expected) { return $child }
            $nested = Find-Button $child $expected
            if ($nested -ne [IntPtr]::Zero) { return $nested }
            $after = $child
        }
        return [IntPtr]::Zero
    }

    $button = if ($window -ne [IntPtr]::Zero) { Find-Button $window $buttonName } else { [IntPtr]::Zero }
    if ($button -ne [IntPtr]::Zero) {
        $null = [XXZFMouse]::SendMessage($button, 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero)
    }
    Start-Sleep -Seconds 5
}

$clickDiagnosticFlag = Join-Path $env:LOCALAPPDATA "XXZF\click-diagnostic-next"
if (Test-Path $clickDiagnosticFlag) {
    Remove-Item $clickDiagnosticFlag -Force
    $workArea = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
    $left = $workArea.Left + [int](($workArea.Width - 462) / 2)
    $top = $workArea.Top + [int](($workArea.Height - 748) / 2)
    $null = [XXZFMouse]::SetCursorPos($left + 334, $top + 608)
    [XXZFMouse]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
    [XXZFMouse]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
    Start-Sleep -Seconds 6
}

$process = Get-Process Forwarder -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowHandle -ne 0 } |
    Select-Object -First 1
if (-not $process) { throw "Forwarder window was not found" }

$rect = New-Object XXZFMouse+RECT
if (-not [XXZFMouse]::GetWindowRect($process.MainWindowHandle, [ref]$rect)) {
    throw "Forwarder window bounds were not available"
}
$bounds = New-Object System.Drawing.Rectangle(
    $rect.Left,
    $rect.Top,
    ($rect.Right - $rect.Left),
    ($rect.Bottom - $rect.Top))
$bitmap = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
try {
    $graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
    $output = Join-Path $env:LOCALAPPDATA "XXZF\windows-ui-current.png"
    $bitmap.Save($output, [System.Drawing.Imaging.ImageFormat]::Png)
} finally {
    $graphics.Dispose()
    $bitmap.Dispose()
}
