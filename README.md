# ti-lex-ia-REA

Un **agent IA local** pour Ti-Lex : il tourne sur ton ordinateur avec un modèle Ollama et peut
**chercher sur le web**, **regarder des images**, **lire et écrire les fichiers d'un projet** et
**lancer des commandes** — avec ta confirmation pour les actions risquées.

Le projet contient aussi un script pour installer **Heretic officiel**
([p-e-w/heretic](https://github.com/p-e-w/heretic)), l'outil qui retire les refus d'un modèle.

## Comment ça marche

```
Toi ──► Agent (boucle) ──► Modèle Ollama (qwen3:8b)
              │                  │ choisit un outil
              ▼                  ▼
        Outils : web_search · fetch_page · describe_image ──► modèle de vision (qwen2.5vl:7b)
                 list_files · read_file · write_file · run_command
```

Le modèle décide quel outil appeler, l'agent l'exécute et lui redonne le résultat, jusqu'à ce que
la tâche soit finie (12 étapes maximum par demande).

## Installation

1. **Ollama** : https://ollama.com/download, puis télécharge les deux modèles :
   ```bash
   ollama pull qwen3:8b        # modèle principal (appels d'outils)
   ollama pull qwen2.5vl:7b    # modèle de vision (décrire les images)
   ```
2. **L'agent** :
   ```bash
   git clone https://github.com/alexmarceauprevost812-source/ti-lex-ia-REA-.git
   cd ti-lex-ia-REA-
   python3 -m venv .venv && source .venv/bin/activate
   pip install -e .
   ```

## Utilisation

```bash
python -m ti_lex_agent                       # mode conversation
python -m ti_lex_agent "résume https://exemple.com"
python -m ti_lex_agent --model qwen3:4b --workspace ~/mon-projet
```

Exemples de demandes :
- « Cherche la dernière version de Python et dis-moi ce qui a changé. »
- « Décris l'image `photo.png`. » (mets l'image dans le dossier de travail)
- « Crée un petit site avec une page d'accueil dans `site/`, puis teste-le. »

Réglages (variables d'environnement) : `OLLAMA_HOST`, `TILEX_MODEL`, `TILEX_VISION_MODEL`,
`TILEX_WORKSPACE`.

### Commandes du mode conversation

| Commande | Effet |
| --- | --- |
| `/params` | affiche les réglages de génération actuels |
| `/temp 0.9` | change la température (raccourci de `/param`) |
| `/param top_p 0.95` | change un autre réglage (`top_k`, `repeat_penalty`, `num_ctx`, `seed`) |
| `/model <nom>` | change le modèle principal utilisé pour la suite de la conversation |
| `/heretic <org/modele>` | lance Heretic officiel sur un modèle Hugging Face (demande confirmation) |
| `/importer <dossier> <nom>` | importe un modèle modifié dans Ollama sous ce nom |
| `/reset` | oublie la conversation |

La température et les autres réglages s'appliquent tout de suite, à chaque message. Modifier
les **poids** d'un modèle (avec Heretic) prend plusieurs minutes et crée un nouveau modèle à
part ; l'original n'est jamais touché.

## Sécurité

- L'agent ne peut lire et écrire **que dans son dossier de travail** (`workspace/` par défaut).
- Écraser un fichier existant et lancer une commande **demandent toujours ta confirmation**.
- Les pages web vers des adresses privées ou locales (`localhost`, `192.168.x.x`…) sont refusées.
- Une commande lancée par l'agent n'est **pas isolée** du reste de ton système : lis-la avant
  de répondre « o ». Garde l'agent sur un dossier de projet, pas sur ton dossier personnel.

## Heretic officiel (modèles sans refus)

```bash
bash scripts/install_heretic.sh
source ~/venvs/heretic/bin/activate
heretic Qwen/Qwen3-4B-Instruct-2507
```

Ou directement depuis l'agent, une fois Heretic installé : `/heretic Qwen/Qwen3-4B-Instruct-2507`
puis, quand c'est fini, `/importer <dossier-sauvegardé> mon-modele-libre`.

- Heretic charge le modèle **entier** en mémoire graphique. Avec une carte de 8 Go de VRAM,
  prends un petit modèle (4B) et active la quantification 4 bits dans la config
  (`quantization = "bnb_4bit"`, voir `config.default.toml` dans le dépôt de Heretic).
- À la fin, Heretic propose de **sauvegarder** le modèle dans un dossier. Ollama peut ensuite
  l'importer avec un `Modelfile` contenant `FROM /chemin/du/dossier`, puis
  `ollama create mon-modele -f Modelfile`. Les architectures courantes (Llama, Gemma, Qwen,
  Mistral) sont prises en charge ; sinon, convertis d'abord en GGUF avec llama.cpp.
- **Teste le modèle obtenu** avant de l'utiliser dans l'agent : un modèle modifié peut perdre
  une partie de sa capacité à faire des appels d'outils. Si c'est le cas, garde le modèle de
  base pour l'agent.
- Heretic retire des garde-fous de sécurité : à utiliser de façon responsable, et dans le
  respect de la licence du modèle de départ (Heretic lui-même est sous AGPL-3.0).

## Développement

```bash
pip install -e ".[dev]"
pytest
```

Les tests utilisent un faux modèle : ils n'ont besoin ni d'Ollama ni d'internet.

## Menu LexOS Pro (Chat, Codex, REA, Heretic)

```bash
python -m ti_lex_agent.launcher
# ou, après `pip install -e .` :
lexos-ia
```

(La commande s'appelle `lexos-ia`, pas `lexos-pro` — ce dernier nom est déjà pris par
l'application de Paramètres LexOS existante.)

Un seul menu, 4 modes, tous sur Ollama :

| # | Mode | Pour quoi | Modèle par défaut |
| --- | --- | --- | --- |
| 1 | Chat | conversation générale, rapide, sans outils | `qwen3-vl:4b` |
| 2 | Codex | assistant de code, sans outils | `qwen2.5-coder:7b` |
| 3 | REA | l'agent complet (web, vision, fichiers) | `heretic:latest` |
| 4 | Heretic | chat direct avec le modèle décensuré, sans outils | `heretic:latest` |

Change les noms avec `TILEX_CHAT_MODEL`, `TILEX_CODEX_MODEL`, `TILEX_REA_MODEL`,
`TILEX_HERETIC_MODEL`. Fonctionne pareil installé sur le disque ou lancé depuis une clé USB-C —
rien dans le code ne dépend d'un chemin fixe.

**PC moins puissant :** si le modèle par défaut n'est pas installé, le menu bascule tout seul
sur un plus petit (`TILEX_CHAT_FALLBACK`, `TILEX_CODEX_FALLBACK`, `TILEX_REA_FALLBACK`,
défauts : `llama3.2:1b`, `qwen2.5-coder:1.5b`, `qwen2.5:3b`) et te dit quoi faire si même celui-là
manque. Le repli du mode Heretic n'est **pas décensuré** — un petit modèle ne peut pas hériter
d'Heretic sans qu'Heretic tourne dessus, ce qui prend une vraie carte graphique.

## Mémoire partagée

Les 4 modes lisent et complètent le **même** fichier (`memoire-ia.md`, à côté du dossier de
travail ; change l'emplacement avec `TILEX_MEMORY` pour le garder sur la clé USB).

- `/retenir <texte>` — ajoute un fait que les 4 modes connaîtront, dans n'importe lequel d'entre eux.
- Rien n'est deviné automatiquement par le modèle : seul ce que tu demandes d'écrire y va.
- Les **erreurs d'outils** (fichier introuvable, commande refusée par le système…) sont par contre
  notées toutes seules dans REA, pour éviter de refaire la même erreur — sauf un refus volontaire
  de ta part, qui n'est pas une erreur. L'écriture s'arrête automatiquement s'il reste moins de
  20 Mo sur la clé, pour ne jamais la remplir.

## Cross-plateforme

- **Linux et Windows** : le code est en Python pur ; installe Python, Ollama, puis
  `pip install -e .` des deux côtés. Sous Windows, lance avec PowerShell ou CMD
  (`python -m ti_lex_agent.launcher`).
- **Android** : un téléphone ne peut pas faire tourner `heretic:latest` (18 Go, besoin d'une
  carte graphique). La seule façon réaliste est de se connecter **par le réseau** à Ollama lancé
  sur ton PC :
  1. Sur le PC : `OLLAMA_HOST=0.0.0.0 ollama serve` (ouvre Ollama au réseau local)
  2. Sur le téléphone : installe [Termux](https://termux.dev/), puis
     `pkg install python && pip install requests ddgs`
  3. Clone le dépôt et lance avec `OLLAMA_HOST=http://IP-DU-PC:11434 python -m ti_lex_agent.launcher`
  Le téléphone n'exécute pas le modèle : il envoie tes messages au PC et reçoit la réponse.

## Vider le PC — tout sur la clé USB-C seulement

**Toujours dans cet ordre : copier, tester, confirmer, SEULEMENT ENSUITE supprimer.**
Supprimer avant de confirmer que ça marche te laisse sans aucun modèle nulle part.

**1. Copie les modèles Ollama du disque interne vers la clé** (remplace le chemin par
l'endroit où ta clé est montée) :
```bash
mkdir -p /media/marceau/LEXOS/ollama-models
sudo rsync -av --progress /usr/share/ollama/.ollama/models/ /media/marceau/LEXOS/ollama-models/
```

**2. Copie aussi le projet sur la clé** (pour qu'il n'ait plus besoin du disque interne).
Une clé formatée exFAT/FAT ne supporte pas les liens symboliques — et `python3 -m venv`
en crée toujours un (`lib64`), **même avec `--copies`** sur Debian/LexOS Pro, donc un
`.venv` ne peut pas vivre sur la clé. On n'en a pas besoin : `pip install --target`
installe le projet et ses dépendances comme de simples fichiers, dans un dossier à
côté, sans aucun lien symbolique :
```bash
rsync -a --exclude='.venv' --exclude='deps' ~/ti-lex-ia-REA-/ /media/marceau/LEXOS/ti-lex-ia-REA-/
cd /media/marceau/LEXOS/ti-lex-ia-REA-
python3 -m pip install --target=deps --upgrade .
```

**3. Teste que tout marche DEPUIS LA CLÉ, sans toucher au disque interne** :
```bash
bash scripts/demarrer-lexos-usb.sh /media/marceau/LEXOS
```
Essaie les 4 modes (surtout Heretic). Si un modèle manque ou qu'une erreur apparaît, le
disque interne a encore tout — rien n'est perdu, tu peux corriger et réessayer.

**4. Seulement si l'étape 3 fonctionne bien**, libère le disque interne :
```bash
sudo systemctl stop ollama
sudo systemctl disable ollama   # pour qu'il ne redémarre plus tout seul au boot
sudo rm -rf /usr/share/ollama/.ollama/models
```

**À partir de maintenant**, pour utiliser l'IA : branche la clé, puis
`bash /media/marceau/LEXOS/ti-lex-ia-REA-/scripts/demarrer-lexos-usb.sh`. Sans la clé
branchée, le PC n'a plus aucun modèle — exactement ce que tu voulais.

## Tout lancer en un clic depuis la clé

Copie les deux fichiers du dossier `cle-usb/` du dépôt **à la racine de la clé**, à côté
(pas dedans) du dossier `ti-lex-ia-REA-` :
```bash
cp cle-usb/LANCER-LEXOS-PRO.sh cle-usb/LexOS-Pro.desktop /media/marceau/LEXOS/
chmod +x /media/marceau/LEXOS/LANCER-LEXOS-PRO.sh /media/marceau/LEXOS/LexOS-Pro.desktop
```

- **`LANCER-LEXOS-PRO.sh`** : le plus fiable. Double-clique dessus dans le gestionnaire de
  fichiers — la plupart proposent « Exécuter » ou « Lancer dans un terminal ». Il se trouve
  tout seul, peu importe où la clé est montée.
- **`LexOS-Pro.desktop`** : une icône d'application pour un bureau comme celui de LexOS Pro.
  La première fois, un clic droit → « Autoriser le lancement » (ou « Allow Launching ») est
  parfois nécessaire — c'est une protection normale de GNOME/XFCE contre les fichiers `.desktop`
  inconnus, pas un bug.

Les deux ouvrent un terminal, démarrent Ollama pointé sur les modèles de la clé, et affichent
le menu à 4 choix.

## Images dans Chat et Codex

Pas seulement REA : dans **Chat** et **Codex** aussi, `/image <fichier> [question]` fait
décrire une image par le modèle de vision et l'ajoute à la conversation — utile pour faire
coder Codex à partir d'une maquette, ou faire discuter Chat d'une capture d'écran. L'image
doit être dans le dossier de travail (`workspace/` par défaut). Exemple :
```
> /image maquette.png fais-moi le HTML de cet écran
```

## Idées pour la suite

- Interface web ou fenêtre graphique en plus du terminal
- Copier automatiquement les modèles Ollama sur la clé pour un vrai fonctionnement portable
  (aujourd'hui, `ollama list` lit le disque interne, pas la clé)
- Mémoire qui résume automatiquement une conversation, en plus de `/retenir`
