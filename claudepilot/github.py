"""Accès aux releases GitHub (sans dépendance Qt : sert aussi à l'installateur).

Dépôt public : accès anonyme. Dépôt privé : jeton pris dans CLAUDEPILOT_GITHUB_TOKEN /
GITHUB_TOKEN, ou celui de GitHub CLI (`gh auth token`) s'il est installé et connecté.
"""
import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

API = "https://api.github.com"
APP_ZIP_ASSET = "Claude-Pilot-app.zip"
SETUP_ASSET = "Claude-Pilot-Setup.exe"
USER_AGENT = "Claude-Pilot-updater"


class GitHubError(RuntimeError):
    pass


def parse_version(text: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", text or "")
    return tuple(int(n) for n in nums[:3]) or (0,)


def is_newer(remote: str, local: str) -> bool:
    return parse_version(remote) > parse_version(local)


def _token() -> str | None:
    for var in ("CLAUDEPILOT_GITHUB_TOKEN", "GITHUB_TOKEN"):
        if os.environ.get(var):
            return os.environ[var]
    gh = shutil.which("gh")
    if gh:
        try:
            out = subprocess.run([gh, "auth", "token"], capture_output=True, text=True, timeout=8,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open(url: str, token: str | None, accept: str, follow: bool = True, timeout: int = 20):
    headers = {"User-Agent": USER_AGENT, "Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    opener = urllib.request.build_opener() if follow else urllib.request.build_opener(_NoRedirect)
    return opener.open(req, timeout=timeout)


def latest_release(repo: str) -> dict:
    """Dernière release publiée (hors brouillons / pré-versions)."""
    url = f"{API}/repos/{repo}/releases/latest"
    last_error = None
    for token in (None, "auth"):
        tok = _token() if token else None
        if token and not tok:
            break
        try:
            with _open(url, tok, "application/vnd.github+json") as r:
                data = json.loads(r.read().decode("utf-8"))
                data["_token_used"] = bool(tok)
                return data
        except urllib.error.HTTPError as e:
            last_error = e
            if e.code not in (401, 403, 404):
                break
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise GitHubError(f"Pas de connexion à GitHub ({e})") from e
    if isinstance(last_error, urllib.error.HTTPError) and last_error.code == 404:
        raise GitHubError("Aucune version publiée trouvée sur GitHub.")
    raise GitHubError(f"GitHub a refusé la demande ({last_error})")


def find_asset(release: dict, name: str) -> dict | None:
    return next((a for a in release.get("assets") or [] if a.get("name") == name), None)


def download_asset(asset: dict, dest: Path, progress: Callable[[int, int], None] | None = None,
                   private: bool = False) -> Path:
    """Télécharge un fichier de release (avec progression) puis le met en place d'un coup."""
    tmp = dest.with_name(dest.name + ".part")
    token = _token() if private else None
    if token:
        # Dépôt privé : l'API renvoie vers un lien signé, qu'on suit SANS le jeton.
        try:
            with _open(asset["url"], token, "application/octet-stream", follow=False) as r:
                location = r.headers.get("Location")
                if not location:  # contenu servi directement
                    _stream(r, tmp, int(asset.get("size") or 0), progress)
                    tmp.replace(dest)
                    return dest
        except urllib.error.HTTPError as e:
            if e.code not in (301, 302, 303, 307, 308):
                raise GitHubError(f"Téléchargement refusé ({e})") from e
            location = e.headers.get("Location")
        url = location
    else:
        url = asset["browser_download_url"]
    try:
        with _open(url, None, "application/octet-stream", timeout=60) as r:
            _stream(r, tmp, int(r.headers.get("Content-Length") or asset.get("size") or 0), progress)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        tmp.unlink(missing_ok=True)
        raise GitHubError(f"Téléchargement interrompu ({e})") from e
    if asset.get("size") and tmp.stat().st_size != int(asset["size"]):
        tmp.unlink(missing_ok=True)
        raise GitHubError("Fichier téléchargé incomplet.")
    tmp.replace(dest)
    return dest


def _stream(response, path: Path, total: int, progress) -> None:
    done = 0
    with open(path, "wb") as f:
        while True:
            chunk = response.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
