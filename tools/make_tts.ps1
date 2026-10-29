# Génère un audio de test en français (voix SAPI Hortense) + la position de chaque mot.
# Usage : powershell -File tools\make_tts.ps1 -Script tests\data\script_fr.txt -OutWav tests\data\tts_fr.wav -OutJson tests\data\tts_fr_words.json
param(
    [Parameter(Mandatory = $true)][string]$Script,
    [Parameter(Mandatory = $true)][string]$OutWav,
    [Parameter(Mandatory = $true)][string]$OutJson,
    [string]$Voice = "Microsoft Hortense Desktop",
    [int]$Rate = 1
)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Speech

$lines = Get-Content -Path $Script -Encoding UTF8 | Where-Object { $_.Trim() -ne "" }
$culture = [System.Globalization.CultureInfo]::GetCultureInfo("fr-FR")
$pb = New-Object System.Speech.Synthesis.PromptBuilder($culture)
$pb.AppendBreak([TimeSpan]::FromMilliseconds(600))
$pauses = @(900, 1300, 800, 1600, 1000, 1200, 900, 700)
for ($i = 0; $i -lt $lines.Count; $i++) {
    $pb.AppendText($lines[$i])
    $pb.AppendBreak([TimeSpan]::FromMilliseconds($pauses[$i % $pauses.Count]))
}

$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.SelectVoice($Voice)
$synth.Rate = $Rate
$format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$synth.SetOutputToWaveFile((Resolve-Path -Path (Split-Path $OutWav -Parent)).Path + "\" + (Split-Path $OutWav -Leaf), $format)

$script:words = New-Object System.Collections.ArrayList
$synth.add_SpeakProgress({
    param($sender, $e)
    [void]$script:words.Add([pscustomobject]@{ text = $e.Text; t = [math]::Round($e.AudioPosition.TotalSeconds, 3) })
})
$synth.Speak($pb)
$synth.SetOutputToNull()
$synth.Dispose()

$payload = [pscustomobject]@{ reference = ($lines -join " "); words = $script:words }
$payload | ConvertTo-Json -Depth 4 | Out-File -FilePath $OutJson -Encoding utf8
"mots horodatés : $($script:words.Count)"
