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

## Idées pour la suite

- Interface web ou fenêtre simple en plus du terminal
- Mémoire entre les sessions
- Brancher l'agent sur LexOS-Pro (commande `lexos agent`)
