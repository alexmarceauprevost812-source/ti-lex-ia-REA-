# Démarre l'assistante : le moteur IA tourne caché en arrière-plan, puis une
# fenêtre Windows s'ouvre (Edge en mode application, sans barre d'adresse).
# Quand on ferme la fenêtre, le moteur s'arrête tout seul.
# Confidentialité : le moteur écoute seulement 127.0.0.1 (cet ordinateur) ;
# rien n'est envoyé sur internet pendant qu'elle travaille.

$ErrorActionPreference = 'Stop'
$app = Split-Path -Parent $MyInvocation.MyCommand.Path
$racine = Split-Path -Parent $app
$modeles = Join-Path $app 'modele'
$port = 8765
$url = "http://127.0.0.1:$port/"
$journal = Join-Path $env:TEMP 'assistante-moteur.log'
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

function Avertir($texte) { [System.Windows.Forms.MessageBox]::Show($texte, 'Mon assistante', 'OK', 'Warning') | Out-Null }
function Pret {
    try { return (Invoke-WebRequest "${url}health" -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 } catch { return $false }
}

function Trouver-Edge {
    $chemins = @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe", "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe", "$env:LOCALAPPDATA\Microsoft\Edge\Application\msedge.exe")
    return $chemins | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
}

# Tout ce que l'assistante crée va directement dans « Mes documents » sur la
# clé (et pas dans Téléchargements de l'ordi) : elle le retrouve dans
# l'Explorateur Windows comme n'importe quel dossier. La lettre de la clé
# change d'un PC à l'autre, donc on le règle à chaque démarrage.
function Regler-Telechargements($profil) {
    $docs = Join-Path $racine 'Mes documents'
    New-Item -ItemType Directory -Force $docs | Out-Null
    $defaut = Join-Path $profil 'Default'
    New-Item -ItemType Directory -Force $defaut | Out-Null
    $fichier = Join-Path $defaut 'Preferences'
    $prefs = $null
    if (Test-Path $fichier) { try { $prefs = Get-Content $fichier -Raw -Encoding UTF8 | ConvertFrom-Json } catch { $prefs = $null } }
    if (-not $prefs) { $prefs = [pscustomobject]@{} }
    foreach ($cle in 'download', 'savefile') {
        if (-not $prefs.PSObject.Properties[$cle]) { $prefs | Add-Member -NotePropertyName $cle -NotePropertyValue ([pscustomobject]@{}) }
    }
    $prefs.download | Add-Member -Force -NotePropertyName default_directory -NotePropertyValue $docs
    $prefs.download | Add-Member -Force -NotePropertyName prompt_for_download -NotePropertyValue $false
    $prefs.download | Add-Member -Force -NotePropertyName directory_upgrade -NotePropertyValue $true
    $prefs.savefile | Add-Member -Force -NotePropertyName default_directory -NotePropertyValue $docs
    $json = $prefs | ConvertTo-Json -Depth 100 -Compress
    [System.IO.File]::WriteAllText($fichier, $json, (New-Object System.Text.UTF8Encoding($false)))
}

function Ouvrir-Fenetre {
    $edge = Trouver-Edge
    if (-not $edge) { Start-Process $url; return $null }
    # Profil séparé gardé sur la clé : ses conversations et réglages la suivent.
    $profil = Join-Path $app 'profil'
    try { Regler-Telechargements $profil } catch { }
    $arg = "--app=$url --user-data-dir=`"$profil`" --no-first-run --no-default-browser-check --disable-sync --window-size=1280,860"
    return Start-Process $edge -ArgumentList $arg -PassThru
}

# Raccourci « Mon assistante » avec le logo, à la racine de la clé, et clé
# reconnaissable dans « Ce PC » (autorun.inf : icône + nom, sans rien lancer).
function Mettre-A-Jour-Raccourci($racine, $app) {
    try {
        $sh = New-Object -ComObject WScript.Shell
        $lnk = $sh.CreateShortcut((Join-Path $racine 'Mon assistante.lnk'))
        $lnk.TargetPath = Join-Path $racine "Démarrer l'assistante.cmd"
        $lnk.WorkingDirectory = $racine
        $lnk.IconLocation = (Join-Path $app 'interface\icone.ico') + ',0'
        $lnk.WindowStyle = 7
        $lnk.Description = 'Ouvrir mon assistante'
        $lnk.Save()
        $inf = Join-Path $racine 'autorun.inf'
        if (Test-Path $inf) { (Get-Item $inf -Force).Attributes = 'Hidden' }
    } catch { }
}

# Déjà démarrée (double-clic une 2e fois) : on rouvre juste la fenêtre.
Mettre-A-Jour-Raccourci $racine $app
if (Pret) { Ouvrir-Fenetre | Out-Null; exit 0 }

# --------------------------------------------- IA pas encore téléchargée
$modele = Get-ChildItem $modeles -Filter *.gguf -ErrorAction SilentlyContinue | Where-Object { $_.Name -notmatch 'mmproj' } | Select-Object -First 1
$cpu = Join-Path $app 'moteur\cpu\llama-server.exe'
if (-not $modele -or -not (Test-Path $cpu)) {
    $r = [System.Windows.Forms.MessageBox]::Show(
        "L'intelligence artificielle n'est pas encore sur la clé.`n`nLa télécharger maintenant ? Il faut internet (de 2 à 7 Go, selon l'ordinateur).",
        'Mon assistante', 'YesNo', 'Question')
    if ($r -ne 'Yes') { exit 0 }
    $p = Start-Process cmd.exe -ArgumentList "/c `"`"$racine\Installer l'IA (un clic).cmd`"`"" -PassThru -Wait
    $modele = Get-ChildItem $modeles -Filter *.gguf -ErrorAction SilentlyContinue | Where-Object { $_.Name -notmatch 'mmproj' } | Select-Object -First 1
    if (-not $modele -or -not (Test-Path $cpu)) { exit 1 }
}
$vision = Get-ChildItem $modeles -Filter *mmproj*.gguf -ErrorAction SilentlyContinue | Select-Object -First 1

# ------------------------------------------------------- choix du moteur
# Carte graphique dédiée sur CET ordinateur ? (la clé peut changer de PC)
$carte = Get-CimInstance Win32_VideoController | Where-Object { $_.Name -match 'NVIDIA|Radeon RX|Arc A|Arc B' } | Select-Object -First 1
$gpuExe = Join-Path $app 'moteur\gpu\llama-server.exe'
$coeurs = (Get-CimInstance Win32_Processor | Measure-Object NumberOfCores -Sum).Sum
if (-not $coeurs) { $coeurs = [math]::Max(1, [int]($env:NUMBER_OF_PROCESSORS / 2)) }

function Lancer-Moteur($exe, $couches) {
    # Un journal par moteur : celui de la carte graphique peut rester verrouillé
    # un instant après son arrêt, quand on bascule sur le processeur.
    $log = if ($couches -gt 0) { "$journal-gpu" } else { $journal }
    $a = @('-m', "`"$($modele.FullName)`"", '--host', '127.0.0.1', '--port', $port, '-c', '8192', '-np', '1',
           '-t', $coeurs, '-ngl', $couches, '--jinja', '--path', "`"$(Join-Path $app 'interface')`"")
    if ($vision) { $a += @('--mmproj', "`"$($vision.FullName)`"") }
    return Start-Process $exe -ArgumentList $a -NoNewWindow -PassThru -RedirectStandardError $log -RedirectStandardOutput "$log.out"
}

# ------------------------------------------------- écran « je me réveille »
$form = New-Object System.Windows.Forms.Form
$form.Text = 'Mon assistante'
$form.Size = New-Object System.Drawing.Size(460, 190)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false; $form.MinimizeBox = $false
$form.BackColor = [System.Drawing.Color]::White
$etiq = New-Object System.Windows.Forms.Label
$etiq.Text = "Votre assistante se réveille…`nÇa prend de 20 secondes à une minute."
$etiq.Font = New-Object System.Drawing.Font('Segoe UI', 12)
$etiq.AutoSize = $false; $etiq.TextAlign = 'MiddleCenter'
$etiq.Size = New-Object System.Drawing.Size(420, 70); $etiq.Location = New-Object System.Drawing.Point(12, 18)
$barre = New-Object System.Windows.Forms.ProgressBar
$barre.Style = 'Marquee'; $barre.MarqueeAnimationSpeed = 30
$barre.Size = New-Object System.Drawing.Size(400, 18); $barre.Location = New-Object System.Drawing.Point(22, 104)
$form.Controls.AddRange(@($etiq, $barre))

$script:serveur = $null
$script:essaiGpu = [bool]($carte -and (Test-Path $gpuExe))
$script:serveur = if ($script:essaiGpu) { Lancer-Moteur $gpuExe 99 } else { Lancer-Moteur $cpu 0 }
$script:debut = Get-Date
$script:ok = $false

$minuterie = New-Object System.Windows.Forms.Timer
$minuterie.Interval = 1000
$minuterie.Add_Tick({
    if (Pret) { $script:ok = $true; $minuterie.Stop(); $form.Close(); return }
    $ecoule = ((Get-Date) - $script:debut).TotalSeconds
    $mort = $script:serveur.HasExited
    # La carte graphique ne coopère pas : on repasse sur le processeur.
    if ($script:essaiGpu -and ($mort -or $ecoule -gt 90)) {
        if (-not $mort) { Stop-Process -Id $script:serveur.Id -Force -ErrorAction SilentlyContinue }
        $script:essaiGpu = $false
        try { $script:serveur = Lancer-Moteur $cpu 0 } catch { $minuterie.Stop(); $form.Close(); return }
        $script:debut = Get-Date
        return
    }
    if ($mort -or $ecoule -gt 240) { $minuterie.Stop(); $form.Close() }
})
$minuterie.Start()
[void]$form.ShowDialog()

if (-not $script:ok) {
    if (-not $script:serveur.HasExited) { Stop-Process -Id $script:serveur.Id -Force -ErrorAction SilentlyContinue }
    Avertir "L'assistante n'a pas pu démarrer.`n`nRedémarre l'ordinateur et réessaie. Si ça continue, montre ce fichier à Alex :`n$journal"
    exit 1
}

# --------------------------------------------- fenêtre + arrêt à la fermeture
$fenetre = Ouvrir-Fenetre
if ($fenetre) {
    $fenetre.WaitForExit()
    # Edge peut garder un processus d'arrière-plan : on attend la fin de tous
    # ceux qui utilisent le profil de la clé avant d'arrêter le moteur.
    do {
        Start-Sleep -Seconds 2
        $restants = Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" | Where-Object { $_.CommandLine -like "*$app\profil*" }
    } while ($restants)
    if (-not $script:serveur.HasExited) { Stop-Process -Id $script:serveur.Id -Force -ErrorAction SilentlyContinue }
}
