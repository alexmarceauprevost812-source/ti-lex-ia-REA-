# Installe l'IA sur la clé, en un clic : regarde la puissance de l'ordinateur,
# puis télécharge le moteur (llama.cpp) et le modèle qui lui conviennent.
# Tout va sur la clé : rien n'est installé dans Windows.
# Se relance sans danger : ce qui est déjà téléchargé n'est pas refait.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
# Windows PowerShell 5.1 utilise encore de vieux protocoles par défaut :
# GitHub et Hugging Face exigent TLS 1.2.
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$app = Split-Path -Parent $MyInvocation.MyCommand.Path
$moteurs = Join-Path $app 'moteur'
$modeles = Join-Path $app 'modele'
New-Item -ItemType Directory -Force $moteurs, $modeles | Out-Null

function Titre($t) { Write-Host ""; Write-Host "== $t ==" -ForegroundColor Cyan }
function Info($t) { Write-Host "   $t" }

Write-Host "Installation de l'assistante sur la clé" -ForegroundColor Yellow
Write-Host "Garde cette fenêtre ouverte. Il faut internet, et ça peut prendre de 10 à 40 minutes."

# ------------------------------------------------------------ la machine
Titre "1. J'examine l'ordinateur"
$ramGo = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
$vramGo = 0
$gpuNom = $null
$smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($smi) {
    try {
        $l = (& nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits | Select-Object -First 1)
        $gpuNom, $mio = $l -split ',\s*'
        $vramGo = [math]::Round([double]$mio / 1024, 1)
    } catch {}
}
if (-not $gpuNom) {
    # AMD / autres : AdapterRAM est plafonné à 4 Go par Windows, on s'en contente.
    $carte = Get-CimInstance Win32_VideoController | Where-Object { $_.Name -match 'Radeon RX|Arc A|Arc B' } | Select-Object -First 1
    if ($carte) { $gpuNom = $carte.Name; $vramGo = [math]::Round($carte.AdapterRAM / 1GB, 1) }
}
$espaceGo = [math]::Round((Get-PSDrive -Name (Split-Path -Qualifier $app).TrimEnd(':')).Free / 1GB, 1)

# Choix du modèle selon la puissance (Qwen3-VL : parle, écrit et voit les photos)
if ($vramGo -ge 8 -and $ramGo -ge 16) { $taille = '8B'; $niveau = 'fort' }
elseif ($ramGo -ge 8) { $taille = '4B'; $niveau = 'moyen' }
else { $taille = '2B'; $niveau = 'leger' }
$gpu = [bool]($gpuNom -and $vramGo -ge 4)

Info "Mémoire vive : $ramGo Go"
Info ("Carte graphique : " + $(if ($gpuNom) { "$gpuNom ($vramGo Go)" } else { "aucune carte dédiée" }))
Info "Espace libre sur la clé : $espaceGo Go"
Write-Host "   -> Modèle choisi : Qwen3-VL $taille (niveau $niveau)" -ForegroundColor Green

$besoin = @{ '2B' = 2.5; '4B' = 4; '8B' = 7 }[$taille]
if ($espaceGo -lt $besoin) { throw "Pas assez d'espace sur la clé : il faut environ $besoin Go libres." }

# --------------------------------------------------------- téléchargement
function Telecharger($url, $dest) {
    if (Test-Path $dest) { Info "Déjà là : $(Split-Path -Leaf $dest)"; return }
    Info "Téléchargement de $(Split-Path -Leaf $dest)..."
    $tmp = "$dest.partiel"
    # curl.exe est fourni avec Windows 10 et 11 ; -C - reprend un téléchargement coupé.
    & curl.exe -L --fail --retry 5 --retry-delay 3 -C - -o $tmp $url
    if ($LASTEXITCODE -ne 0) { throw "Téléchargement impossible : $url" }
    Move-Item -Force $tmp $dest
}

function Moteur($motif, $dossier) {
    $dest = Join-Path $moteurs $dossier
    if (Test-Path (Join-Path $dest 'llama-server.exe')) { Info "Moteur $dossier déjà installé."; return }
    $rel = Invoke-RestMethod 'https://api.github.com/repos/ggml-org/llama.cpp/releases/latest' -Headers @{ 'User-Agent' = 'assistante' }
    $asset = $rel.assets | Where-Object { $_.name -match $motif } | Select-Object -First 1
    if (-not $asset) { throw "Moteur introuvable dans la version $($rel.tag_name) ($motif)." }
    $zip = Join-Path $moteurs $asset.name
    Telecharger $asset.browser_download_url $zip
    Info "Décompression..."
    New-Item -ItemType Directory -Force $dest | Out-Null
    Expand-Archive -Force $zip $dest
    $exe = Get-ChildItem $dest -Recurse -Filter llama-server.exe | Select-Object -First 1
    if ($exe -and $exe.DirectoryName -ne $dest) { Get-ChildItem $exe.DirectoryName | Move-Item -Destination $dest -Force }
    Remove-Item $zip -Force
    Info "Moteur $dossier prêt (llama.cpp $($rel.tag_name))."
}

Titre "2. Le moteur IA"
Moteur 'bin-win-cpu-x64\.zip$' 'cpu'          # marche sur tous les PC
if ($gpu) { Moteur 'bin-win-vulkan-x64\.zip$' 'gpu' }   # plus rapide avec une carte graphique

Titre "3. Le modèle (le « cerveau »)"
$ordre = @{ '8B' = @('8B', '4B', '2B'); '4B' = @('4B', '2B'); '2B' = @('2B') }[$taille]
$fait = $false
foreach ($t in $ordre) {
    $depot = "Qwen/Qwen3-VL-$t-Instruct-GGUF"
    try { $infos = Invoke-RestMethod "https://huggingface.co/api/models/$depot" -Headers @{ 'User-Agent' = 'assistante' } }
    catch { Info "Modèle $t introuvable, j'essaie plus petit."; continue }
    $fichiers = $infos.siblings.rfilename
    $principal = $fichiers | Where-Object { $_ -match 'Q4_K_M\.gguf$' -and $_ -notmatch 'mmproj' } | Select-Object -First 1
    $vision = ($fichiers | Where-Object { $_ -match 'mmproj.*Q8_0\.gguf$' } | Select-Object -First 1)
    if (-not $vision) { $vision = $fichiers | Where-Object { $_ -match 'mmproj.*\.gguf$' } | Select-Object -First 1 }
    if (-not $principal) { Info "Pas de version légère pour $t, j'essaie plus petit."; continue }
    # On enlève un ancien modèle d'une autre taille pour ne pas remplir la clé.
    $garder = @(Split-Path -Leaf $principal)
    if ($vision) { $garder += Split-Path -Leaf $vision }
    Get-ChildItem $modeles -Filter *.gguf | Where-Object { $garder -notcontains $_.Name } | Remove-Item -Force
    Telecharger "https://huggingface.co/$depot/resolve/main/$principal" (Join-Path $modeles (Split-Path -Leaf $principal))
    if ($vision) { Telecharger "https://huggingface.co/$depot/resolve/main/$vision" (Join-Path $modeles (Split-Path -Leaf $vision)) }
    @{ taille = $t; niveau = $niveau; depot = $depot } | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $modeles 'choix.json')
    $fait = $true
    break
}
if (-not $fait) { throw "Aucun modèle n'a pu être téléchargé." }

# Raccourci « Mon assistante » avec le logo, à la racine de la clé, et clé
# reconnaissable dans « Ce PC » (autorun.inf : icône + nom, sans rien lancer).
function Mettre-A-Jour-Raccourci($racine, $app) {
    try {
        $sh = New-Object -ComObject WScript.Shell
        $lnk = $sh.CreateShortcut((Join-Path $racine 'Mon assistante.lnk'))
        $lnk.TargetPath = Join-Path $racine "▶️ Démarrer l'assistante.cmd"
        $lnk.WorkingDirectory = $racine
        $lnk.IconLocation = (Join-Path $app 'interface\icone.ico') + ',0'
        $lnk.WindowStyle = 7
        $lnk.Description = 'Ouvrir mon assistante'
        $lnk.Save()
        $inf = Join-Path $racine 'autorun.inf'
        if (Test-Path $inf) { (Get-Item $inf -Force).Attributes = 'Hidden' }
    } catch { }
}

# Clé bien rangée pour elle : on voit seulement « Démarrer l'assistante »,
# « Mes documents » et le mode d'emploi. Le dossier technique est caché.
$racine = Split-Path -Parent $app
New-Item -ItemType Directory -Force (Join-Path $racine 'Mes documents') | Out-Null
try { (Get-Item $app -Force).Attributes = 'Directory, Hidden' } catch {}
Mettre-A-Jour-Raccourci $racine $app

Titre "Terminé !"
Write-Host "   L'assistante est prête. Double-clique sur « Démarrer l'assistante »." -ForegroundColor Green
