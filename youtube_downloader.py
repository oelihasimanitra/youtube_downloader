#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YouTube Downloader - telechargeur de videos a la Internet Download Manager.

Fonctionnalites :
  - console interactive : on colle un lien, la video atterrit sur le Bureau
  - barre de progression avec pourcentage, debit, taille et temps restant
  - choix de la qualite (meilleure, 1080p, 720p, 480p, MP3, M4A)
  - playlists, chaines et tout autre site gere par yt-dlp
  - fusion video+audio via ffmpeg quand il est disponible

Usage :
  python youtube_downloader.py                      # mode interactif
  python youtube_downloader.py "URL"                # telechargement direct
  python youtube_downloader.py "URL" -q 720         # qualite imposee
  python youtube_downloader.py "URL1" "URL2" -q mp3
"""

from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import sys
import time
from pathlib import Path

try:
    import yt_dlp
    from yt_dlp.utils import DownloadError
except ImportError:  # pragma: no cover
    print("yt-dlp est absent. Installez-le avec :  python -m pip install -U yt-dlp")
    sys.exit(1)


# --------------------------------------------------------------------------
# Configuration generale
# --------------------------------------------------------------------------

APP_NAME = "YOUTUBE DOWNLOADER"
DEFAULT_DEST = Path.home() / "Desktop" / "YouTube Downloads"

# Emplacements ou l'on cherche ffmpeg / ffprobe si absent du PATH.
FFMPEG_CANDIDATES = [
    Path(r"C:\Program Files (x86)\FormatFactory"),
    Path(r"C:\Program Files\FormatFactory"),
    Path(r"C:\ffmpeg\bin"),
    Path.home() / "ffmpeg" / "bin",
    Path.home() / "scoop" / "shims",
    Path(r"C:\ProgramData\chocolatey\bin"),
]

QUALITIES = {
    "h264": "Meilleure en H.264/AAC (lisible partout)",
    "best": "Meilleure disponible (MP4, codec d'origine)",
    "1080": "1080p max (MP4)",
    "720": "720p max (MP4)",
    "480": "480p max (MP4)",
    "360": "360p max (MP4)",
    "mp3": "Audio MP3 192 kbps",
    "m4a": "Audio M4A (piste originale)",
}
QUALITY_ORDER = ["h264", "best", "1080", "720", "480", "360", "mp3", "m4a"]


class C:
    """Codes couleur ANSI (desactives automatiquement si --no-color)."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"

    @classmethod
    def off(cls) -> None:
        for name in ("RESET", "BOLD", "DIM", "RED", "GREEN", "YELLOW", "BLUE", "MAGENTA", "CYAN"):
            setattr(cls, name, "")


def setup_console() -> None:
    """Passe la console Windows en UTF-8 et active les sequences ANSI."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if os.name == "nt":
        try:
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleOutputCP(65001)
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass
    if os.environ.get("NO_COLOR") or "--no-color" in sys.argv:
        C.off()


# --------------------------------------------------------------------------
# Petits utilitaires d'affichage
# --------------------------------------------------------------------------

def human_bytes(value: float | None) -> str:
    if not value:
        return "--"
    units = ["o", "Ko", "Mo", "Go", "To"]
    index = 0
    value = float(value)
    while value >= 1024 and index < len(units) - 1:
        value /= 1024
        index += 1
    return f"{value:.0f} {units[index]}" if index == 0 else f"{value:.1f} {units[index]}"


def human_time(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def progress_bar(percent: float, width: int) -> str:
    percent = max(0.0, min(100.0, percent))
    filled = int(width * percent / 100)
    return "\u2588" * filled + "\u2591" * (width - filled)


def terminal_width() -> int:
    return max(60, min(110, shutil.get_terminal_size((90, 24)).columns))


def rule(char: str = "\u2500") -> str:
    return char * terminal_width()


def find_ffmpeg() -> str | None:
    """Retourne le dossier contenant ffmpeg, ou None."""
    found = shutil.which("ffmpeg")
    if found:
        return str(Path(found).parent)
    for folder in FFMPEG_CANDIDATES:
        if (folder / "ffmpeg.exe").exists():
            return str(folder)
    return None


# --------------------------------------------------------------------------
# Telechargeur
# --------------------------------------------------------------------------

class YouTubeDownloader:
    def __init__(self, destination: Path, quality: str = "h264", verbose: bool = False):
        self.destination = Path(destination).expanduser()
        self.destination.mkdir(parents=True, exist_ok=True)
        self.quality = quality
        self.verbose = verbose
        self.ffmpeg_dir = find_ffmpeg()
        self.stats = {"ok": [], "ko": []}
        self._reset_progress()

    # ---------------------------------------------------------------- options
    def _reset_progress(self) -> None:
        self._filenames: list[str] = []
        self._line_len = 0
        self._expected_streams = 0  # 0 = inconnu, deduit a la volee
        self._playlist_index = None

    def _format_selector(self) -> str:
        if self.quality in ("mp3", "m4a"):
            return "bestaudio/best"
        if self.quality == "h264":
            if self.ffmpeg_dir:
                # H.264 + AAC : le couple lu sans codec supplementaire sur Windows.
                return "bv*[vcodec^=avc1]+ba[ext=m4a]/bv*[vcodec^=avc1]+ba/b[ext=mp4]/b[ext=mp4]/b"
            return "b[ext=mp4]/b"
        if self.quality == "best":
            if self.ffmpeg_dir:
                return "bv*+ba/b"
            return "b[ext=mp4]/b"
        height = self.quality
        if self.ffmpeg_dir:
            # Priorite au H.264 (lisible partout), sinon on prend ce qui existe.
            return (
                f"bv*[height<={height}][vcodec^=avc1]+ba[ext=m4a]/"
                f"bv*[height<={height}]+ba/"
                f"b[height<={height}]/b"
            )
        return f"b[height<={height}][ext=mp4]/b[height<={height}]/b"

    def _build_options(self) -> dict:
        opts: dict = {
            "outtmpl": str(self.destination / "%(title)s.%(ext)s"),
            "format": self._format_selector(),
            "progress_hooks": [self._on_progress],
            "postprocessor_hooks": [self._on_postprocess],
            "quiet": True,
            "no_warnings": not self.verbose,
            "noprogress": True,
            "noplaylist": False,
            "ignoreerrors": False,
            "windowsfilenames": True,
            "trim_file_name": 180,
            "retries": 10,
            "fragment_retries": 10,
            "socket_timeout": 30,
            "concurrent_fragment_downloads": 4,
            "overwrites": False,
            "continuedl": True,
            "nopart": False,
            "restrictfilenames": False,
            "writeinfojson": False,
            "merge_output_format": "mp4",
        }
        if self.ffmpeg_dir:
            opts["ffmpeg_location"] = self.ffmpeg_dir
        if self.quality == "mp3":
            opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ]
        elif self.quality == "m4a":
            opts["postprocessors"] = [
                {"key": "FFmpegExtractAudio", "preferredcodec": "m4a", "preferredquality": "0"}
            ]
        return opts

    # ------------------------------------------------------------- affichages
    def _write_line(self, text: str) -> None:
        pad = max(0, self._line_len - len(text))
        sys.stdout.write("\r" + text + " " * pad)
        sys.stdout.flush()
        self._line_len = len(text)

    def _end_line(self) -> None:
        if self._line_len:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._line_len = 0

    def _reset_line(self) -> None:
        """Oublie la longueur de la ligne courante (le libelle change de largeur)."""
        self._line_len = 0

    def _on_progress(self, data: dict) -> None:
        status = data.get("status")
        filename = data.get("filename") or ""
        info = data.get("info_dict") or {}

        # Dans une playlist, on repart de zero pour chaque video.
        entry_index = info.get("playlist_index")
        if entry_index != self._playlist_index:
            self._playlist_index = entry_index
            self._filenames = []
            self._line_len = 0

        # yt-dlp telecharge souvent 2 flux distincts (video puis audio) : chaque
        # nouveau nom de fichier signale le flux suivant.
        if filename and filename not in self._filenames:
            self._filenames.append(filename)
            self._line_len = 0  # le libelle change de largeur, on efface la ligne

        if status == "downloading":
            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            done = data.get("downloaded_bytes") or 0
            speed = data.get("speed") or 0
            eta = data.get("eta")

            streams = max(self._expected_streams, len(self._filenames))
            index = self._filenames.index(filename) if filename in self._filenames else 0
            if streams > 1:
                label = "Vid\u00e9o" if index == 0 else "Audio"
            else:
                label = "Fichier"

            percent = (done / total * 100) if total else 0.0
            bar_width = max(20, terminal_width() - 58)
            line = (
                f"{C.CYAN}{label:>7}{C.RESET} "
                f"[{C.GREEN}{progress_bar(percent, bar_width)}{C.RESET}] "
                f"{C.BOLD}{percent:5.1f}%{C.RESET} "
                f"{human_bytes(done)}/{human_bytes(total)} "
                f"{C.YELLOW}{human_bytes(speed)}/s{C.RESET} "
                f"reste {human_time(eta)}"
            )
            self._write_line(line)

        elif status == "finished":
            self._end_line()
            if len(self._filenames) > 1:
                print(f"  {C.DIM}{Path(filename).name} \u2192 t\u00e9l\u00e9charg\u00e9{C.RESET}")

    def _on_postprocess(self, data: dict) -> None:
        if data.get("status") == "started":
            self._end_line()
            name = data.get("postprocessor", "")
            label = {
                "Merger": "Fusion vid\u00e9o + audio (ffmpeg)",
                "FFmpegExtractAudio": "Extraction de l'audio (ffmpeg)",
                "MoveFiles": "Rangement du fichier",
            }.get(name, name or "Post-traitement")
            print(f"  {C.MAGENTA}\u2192{C.RESET} {label}...")

    # ------------------------------------------------------------ operations
    def probe(self, url: str, quiet_fail: bool = False) -> dict | None:
        """
        Recupere les metadonnees sans telecharger (affichage facon IDM).
        Le selecteur de format est applique pour connaitre a l'avance le nombre
        de flux a recuperer (ex. video + audio separes).
        """
        opts = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "skip_download": True,
            "extract_flat": "in_playlist",
            "format": self._format_selector(),
        }
        if self.ffmpeg_dir:
            opts["ffmpeg_location"] = self.ffmpeg_dir
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=False)
        except Exception as exc:
            if not quiet_fail:
                message = str(exc).replace("ERROR: ", "").strip()
                print(f"  {C.RED}Impossible de lire le lien : {message}{C.RESET}")
            return None

    def show_info(self, info: dict) -> None:
        if info.get("_type") == "playlist":
            print(f"  {C.BOLD}Playlist{C.RESET}   : {info.get('title', '?')}")
            entries = [e for e in (info.get("entries") or []) if e]
            print(f"  {C.BOLD}Vid\u00e9os{C.RESET}    : {len(entries)}")
            return
        print(f"  {C.BOLD}Titre{C.RESET}     : {info.get('title', '?')}")
        if info.get("uploader"):
            print(f"  {C.BOLD}Cha\u00eene{C.RESET}    : {info['uploader']}")
        if info.get("duration"):
            print(f"  {C.BOLD}Dur\u00e9e{C.RESET}     : {human_time(info['duration'])}")
        if info.get("view_count"):
            print(f"  {C.BOLD}Vues{C.RESET}      : {info['view_count']:,}".replace(",", " "))

    def download(self, url: str, info: dict | None = None) -> bool:
        """Telecharge une URL. `info` evite une seconde requete s'il est deja connu."""
        self._reset_progress()
        if info is None:
            info = self.probe(url, quiet_fail=True)
        self._expected_streams = len((info or {}).get("requested_formats") or [])
        opts = self._build_options()
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info is None:
                    raise DownloadError("aucune information recuperee")
                self._end_line()

                if info.get("_type") == "playlist":
                    entries = [e for e in (info.get("entries") or []) if e]
                    print(f"  {C.GREEN}\u2713{C.RESET} Playlist trait\u00e9e : {len(entries)} vid\u00e9o(s)")
                    self.stats["ok"].append(info.get("title", url))
                elif not self._filenames:
                    # Aucun flux telecharge : le fichier etait deja sur le disque.
                    final = self._final_path(info)
                    print(f"  {C.YELLOW}={C.RESET} D\u00e9j\u00e0 pr\u00e9sent : {final.name}")
                    self.stats["ok"].append(str(final))
                else:
                    final = self._final_path(info)
                    print(f"  {C.GREEN}\u2713{C.RESET} Enregistr\u00e9 : {final.name}")
                    self.stats["ok"].append(str(final))
                return True

        except KeyboardInterrupt:
            self._end_line()
            print(f"\n  {C.YELLOW}Interrompu par l'utilisateur.{C.RESET}")
            raise
        except DownloadError as exc:
            self._end_line()
            message = str(exc).replace("ERROR: ", "").strip()
            print(f"  {C.RED}\u2717 \u00c9chec : {message}{C.RESET}")
            self.stats["ko"].append((url, message))
            return False
        except Exception as exc:  # noqa: BLE001 - on veut un message propre
            self._end_line()
            print(f"  {C.RED}\u2717 Erreur inattendue : {exc}{C.RESET}")
            self.stats["ko"].append((url, str(exc)))
            return False

    def _final_path(self, info: dict) -> Path:
        """Chemin reel du fichier apres post-traitement (extension eventuellement changee)."""
        base = Path(info.get("filepath") or "")
        if not base.name:
            base = self.destination / f"{info.get('title', 'video')}.{info.get('ext', 'mp4')}"
        if self.quality == "mp3":
            return base.with_suffix(".mp3")
        if self.quality == "m4a":
            return base.with_suffix(".m4a")
        if self.ffmpeg_dir and base.suffix.lower() not in (".mp4", ".mkv", ".webm"):
            return base.with_suffix(".mp4")
        return base


# --------------------------------------------------------------------------
# Interface console
# --------------------------------------------------------------------------

def banner(downloader: YouTubeDownloader) -> None:
    print()
    print(f"{C.BOLD}{C.CYAN}{rule('=')}{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}  {APP_NAME}{C.RESET}  {C.DIM}- t\u00e9l\u00e9chargement de vid\u00e9os{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}{rule('=')}{C.RESET}")
    print(f"  Dossier      : {C.BOLD}{downloader.destination}{C.RESET}")
    ffmpeg = downloader.ffmpeg_dir
    print(f"  ffmpeg       : {ffmpeg if ffmpeg else C.YELLOW + 'absent (qualit\u00e9 limit\u00e9e) ' + C.RESET}")
    print(f"  yt-dlp       : {yt_dlp.version.__version__}")
    print()


def choose_quality(current: str = "best") -> str:
    print(f"  {C.BOLD}Qualit\u00e9 souhait\u00e9e{C.RESET}")
    for index, key in enumerate(QUALITY_ORDER, start=1):
        mark = f"{C.GREEN}\u25cf{C.RESET}" if key == current else " "
        print(f"   {mark} {index}) {QUALITIES[key]}")
    answer = input(f"  Choix [1-{len(QUALITY_ORDER)}] (Entr\u00e9e = {QUALITIES[current]}) : ").strip()
    if not answer:
        return current
    if answer.isdigit() and 1 <= int(answer) <= len(QUALITY_ORDER):
        return QUALITY_ORDER[int(answer) - 1]
    if answer in QUALITIES:
        return answer
    print(f"  {C.YELLOW}Choix invalide, on garde {QUALITIES[current]}.{C.RESET}")
    return current


def interactive(downloader: YouTubeDownloader) -> None:
    banner(downloader)
    downloader.quality = choose_quality(downloader.quality)
    print()
    print(f"  {C.DIM}Collez un lien YouTube (ou une playlist). "
          f"Commandes : q = quitter, d = dossier, f = qualit\u00e9{C.RESET}")
    print()

    while True:
        try:
            raw = input(f"{C.BOLD}{C.CYAN}Lien >{C.RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not raw:
            continue
        if raw.lower() in ("q", "quit", "exit"):
            break
        if raw.lower() == "d":
            new_dir = input("  Nouveau dossier : ").strip().strip('"')
            if new_dir:
                downloader.destination = Path(new_dir).expanduser()
                downloader.destination.mkdir(parents=True, exist_ok=True)
                print(f"  {C.GREEN}Dossier : {downloader.destination}{C.RESET}")
            continue
        if raw.lower() == "f":
            downloader.quality = choose_quality(downloader.quality)
            continue
        if not raw.lower().startswith(("http://", "https://")):
            print(f"  {C.YELLOW}Ce n'est pas un lien valide.{C.RESET}")
            continue

        print()
        info = downloader.probe(raw)
        if info is not None:
            downloader.show_info(info)
            print()
        downloader.download(raw, info)
        print()

    summary(downloader)


def summary(downloader: YouTubeDownloader) -> None:
    ok, ko = len(downloader.stats["ok"]), len(downloader.stats["ko"])
    print(rule("="))
    print(f"  {C.GREEN}{ok} r\u00e9ussi(s){C.RESET}   {C.RED}{ko} \u00e9chec(s){C.RESET}")
    if ok:
        print(f"  Dossier : {C.BOLD}{downloader.destination}{C.RESET}")
        try:
            files = sorted(
                (f for f in downloader.destination.rglob("*") if f.is_file()),
                key=lambda f: f.stat().st_mtime,
                reverse=True,
            )[:5]
            if files:
                print(f"  {C.DIM}Derniers fichiers :{C.RESET}")
                for file in files:
                    print(f"    - {file.name}  {C.DIM}({human_bytes(file.stat().st_size)}){C.RESET}")
        except OSError:
            pass
    print(rule("="))
    print()


def main() -> int:
    setup_console()
    parser = argparse.ArgumentParser(
        description="Télécharge des vidéos (YouTube et autres) comme Internet Download Manager."
    )
    parser.add_argument("urls", nargs="*", help="liens a telecharger (sinon mode interactif)")
    parser.add_argument("-d", "--dest", default=str(DEFAULT_DEST), help="dossier de destination")
    parser.add_argument("-q", "--quality", default="h264", choices=QUALITY_ORDER, help="qualite")
    parser.add_argument("-v", "--verbose", action="store_true", help="affiche les details de yt-dlp")
    parser.add_argument("--no-color", action="store_true", help="desactive les couleurs")
    args = parser.parse_args()

    try:
        downloader = YouTubeDownloader(Path(args.dest), args.quality, args.verbose)
    except OSError as exc:
        print(f"{C.RED}Impossible de creer {args.dest} : {exc}{C.RESET}")
        return 2

    if not args.urls:
        interactive(downloader)
        return 0

    banner(downloader)
    start = time.time()
    for url in args.urls:
        print(f"{C.BOLD}Lien :{C.RESET} {url}")
        downloader.download(url)
        print()
    print(f"  {C.DIM}Termin\u00e9 en {human_time(time.time() - start)}{C.RESET}")
    print()
    summary(downloader)
    return 1 if downloader.stats["ko"] else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(f"\n{C.YELLOW}Arr\u00eat demand\u00e9.{C.RESET}")
        sys.exit(130)
