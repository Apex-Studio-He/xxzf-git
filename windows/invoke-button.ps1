param(
    [string]$Name = ""
)

$ErrorActionPreference = "Stop"
$resultPath = Join-Path $env:LOCALAPPDATA "XXZF\ui-invoke-result.txt"
try {
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

if ([string]::IsNullOrWhiteSpace($Name)) {
    $Name = -join @(
        [char]0x8FDE, [char]0x63A5, [char]0x53E6, [char]0x4E00,
        [char]0x53F0, [char]0x624B, [char]0x673A
    )
}
$windowName = -join @([char]0x8F6C, [char]0x53D1)

$root = [System.Windows.Automation.AutomationElement]::RootElement
$windowCondition = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::NameProperty,
    $windowName)
$windows = $root.FindAll(
    [System.Windows.Automation.TreeScope]::Children,
    $windowCondition)
$window = $null
foreach ($candidate in $windows) {
    if ($candidate.Current.ControlType -eq [System.Windows.Automation.ControlType]::Window) {
        $window = $candidate
        break
    }
}
if (-not $window) {
    throw "Forwarder window was not found"
}

$buttonCondition = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::NameProperty,
    $Name)
$matches = $window.FindAll(
    [System.Windows.Automation.TreeScope]::Descendants,
    $buttonCondition)
$button = $null
foreach ($match in $matches) {
    if ($match.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button) {
        $button = $match
        break
    }
}
if (-not $button) {
    $all = $window.FindAll(
        [System.Windows.Automation.TreeScope]::Descendants,
        [System.Windows.Automation.Condition]::TrueCondition)
    $buttonNames = @()
    foreach ($element in $all) {
        if ($element.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button) {
            $points = @()
            foreach ($character in $element.Current.Name.ToCharArray()) {
                $points += ('{0:X4}' -f [int]$character)
            }
            $buttonNames += ($points -join '-')
        }
    }
    throw ("Button was not found. Expected={0}; Available={1}" -f
        (($Name.ToCharArray() | ForEach-Object { '{0:X4}' -f [int]$_ }) -join '-'),
        ($buttonNames -join ','))
}

$pattern = $button.GetCurrentPattern(
    [System.Windows.Automation.InvokePattern]::Pattern)
$pattern.Invoke()
Set-Content -Path $resultPath -Value "OK" -Encoding UTF8
} catch {
    Set-Content -Path $resultPath -Value $_.Exception.ToString() -Encoding UTF8
    throw
}
