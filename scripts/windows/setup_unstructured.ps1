if (-not (Test-Path $VenvPath)) {
    Invoke-NativeChecked py @('-3.12', '-m', 'venv', $VenvPath)
}

# ------------------------------------------------------------
# Dependency provisioning
# Network access is allowed only in this phase.
# ------------------------------------------------------------

Remove-Item Env:HF_HUB_OFFLINE -ErrorAction SilentlyContinue
Remove-Item Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue

Invoke-NativeChecked "$VenvPath\Scripts\python.exe" @(
    '-m', 'pip', 'install',
    '-r', $ReqFile
)

Write-Host "[unstructured] Running pip check..."
Invoke-NativeChecked "$VenvPath\Scripts\python.exe" @(
    '-m', 'pip', 'check'
)

# ------------------------------------------------------------
# Everything below this point must run offline.
# ------------------------------------------------------------

$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:HF_HUB_DISABLE_TELEMETRY = '1'
$env:DO_NOT_TRACK = '1'
$env:SCARF_NO_ANALYTICS = '1'

Write-Host "[unstructured] Validating imports..."

$smoke = @'
import unstructured
from unstructured.partition.pdf import partition_pdf
import unstructured_inference

print("unstructured OK:", unstructured.__version__)
'@

Invoke-PythonScriptChecked `
    -Python "$VenvPath\Scripts\python.exe" `
    -ScriptText $smoke

Write-Host "[unstructured] Done."
