# YouTube Downloader

Téléchargeur de vidéos en ligne de commande, dans l'esprit d'Internet Download Manager :
on colle un lien, la vidéo descend avec une barre de progression (débit, taille, temps restant)
et se retrouve dans un dossier du Bureau.

## Installation

```bash
python -m pip install -r requirements.txt
```

`ffmpeg` est fortement recommandé : il permet de fusionner les flux vidéo et audio séparés
(YouTube les sert séparément au-delà de 360p) et d'extraire l'audio en MP3.
Le script le détecte tout seul dans le `PATH` ou dans les emplacements courants
(`C:\Program Files (x86)\FormatFactory`, `C:\ffmpeg\bin`, scoop, chocolatey...).

## Lancement

Double-cliquez sur `lancer.bat`, ou en console :

```bash
python youtube_downloader.py                 # mode interactif : on colle les liens
python youtube_downloader.py "URL"           # téléchargement direct
python youtube_downloader.py "URL" -q 720    # qualité imposée
python youtube_downloader.py "URL1" "URL2" -q mp3
```

Commandes disponibles dans le mode interactif : `q` quitter, `d` changer de dossier,
`f` changer de qualité.

## Qualités

| Code    | Contenu                                                     |
|---------|-------------------------------------------------------------|
| `h264`  | Meilleure en H.264/AAC — lisible partout (défaut)            |
| `best`  | Meilleure disponible, codec d'origine (souvent AV1/Opus)     |
| `1080`  | 1080p max, H.264 si possible                                 |
| `720`   | 720p max, H.264 si possible                                  |
| `480`   | 480p max                                                     |
| `360`   | 360p max                                                     |
| `mp3`   | Audio extrait en MP3 192 kbps                                |
| `m4a`   | Audio M4A dans son format d'origine                          |

## Destination

Par défaut : `C:\Users\<vous>\Desktop\YouTube Downloads` (créé automatiquement).
Modifiable avec `-d "D:\Vidéos"`.

Les playlists, chaînes et les autres sites gérés par `yt-dlp` (Vimeo, Dailymotion,
Facebook, TikTok...) fonctionnent de la même façon.

## Options

```
-d, --dest DOSSIER   dossier de destination
-q, --quality CODE   qualité (voir tableau ci-dessus)
-v, --verbose        affiche le détail des choix de yt-dlp
    --no-color       désactive les couleurs
```

## Notes

- Un fichier déjà téléchargé n'est pas rechargé : le script affiche « Déjà présent ».
- Le téléchargement est repris automatiquement après une coupure réseau.
- L'usage doit rester conforme aux conditions d'utilisation des sites concernés et au
  droit d'auteur : privilégiez les contenus libres ou dont vous détenez les droits.
