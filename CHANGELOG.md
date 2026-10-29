# Changelog

Chaque version publiée avec `uv run python release.py X.Y.Z` reprend la section correspondante :
c'est ce texte que Claude Pilot affiche quand il propose la mise à jour.

## 1.0.0

Première version publique.

- **Retours vocaux pour Claude Code** : tu parles en montrant ton écran, la transcription arrive phrase par
  phrase, et chaque capture est placée au mot près (`[C2 · 0:31]`). À l'arrêt, le message est copié :
  `Ctrl+V` dans Claude Code, et il lit le texte puis chaque capture.
- **Captures** au raccourci (`F8`), au bouton ou à la voix (« capture », « screen », « regarde » à
  l'impératif). Une « boîte noire » garde les dernières secondes d'écran : la capture vocale prend l'image
  du moment exact du mot. Seul l'écran sous la souris est capturé, avec la souris entourée en rouge.
- **Commandes vocales** : « annule la capture », « point suivant ».
- **Transcription locale** avec trois moteurs au choix : Parakeet TDT v3 (par défaut), Whisper large-v3 et
  Whisper large-v3 turbo, sur carte graphique NVIDIA ou sur processeur. Comparaison et retranscription
  d'un retour dans Réglages → Transcription.
- **Fenêtre** avec transcription en direct, miniatures, historique des retours et test du micro ; barre
  flottante invisible dans les captures pendant l'enregistrement.
- **Bruitages** discrets pour suivre chaque action.
- **Commande `/retour`** pour Claude Code, à installer depuis les Réglages.
- **Installateur** qui récupère la dernière version, et **mises à jour** proposées au lancement avec ce
  changelog.
