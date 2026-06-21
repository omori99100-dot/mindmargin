param(
    [switch]$Install,
    [switch]$Remove,
    [switch]$RunNow
)

$taskName = "MindMargin Daily Job"
$projectRoot = "C:\Users\ACENTE~1\OneDrive\AD0F~1\MINDMA~1"
$pythonExe = "C:\Users\A Center\AppData\Local\Programs\Python\Python311\python.exe"

if ($RunNow) {
    Write-Host "Running daily job now..."
    & $pythonExe -m mindmargin.main --run-daily-job
    Write-Host "Done."
    return
}

if ($Remove) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Task '$taskName' removed."
    return
}

if ($Install) {
    $action = New-ScheduledTaskAction -Execute $pythonExe -Argument "-m mindmargin.main --run-daily-job" -WorkingDirectory $projectRoot
    $trigger = New-ScheduledTaskTrigger -Daily -At 02:00AM
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Limited

    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force
    Write-Host "Task '$taskName' installed — runs daily at 2:00 AM."
    Write-Host "Run 'schedule_daily.ps1 -RunNow' to test immediately."
    return
}

Write-Host @"
Usage:
  .\schedule_daily.ps1 -Install    Register daily task (2:00 AM)
  .\schedule_daily.ps1 -Remove     Remove the task
  .\schedule_daily.ps1 -RunNow     Execute daily job immediately
"@
