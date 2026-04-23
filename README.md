# Kodi client for AudioBookShelf

Kodi's audio player, PAPlayer doesn't support tempo (playback speed adjustment). 

Video player does, but that requires syncing playback to display which has caused audio problems for me.

Seeing that inputstream.ffmpegdirect has ffmpeg built-in, I figured that it could be used to modify tempo.

Claude addded the capability easily, see the fork here: https://github.com/kontell/inputstream.tempo

However seeking was broken, see the fix here: https://github.com/xbmc/xbmc/pull/28179

## Installation

This can now be tested by:
  - Installing a patched build of Kodi from here: https://github.com/kontell/xbmc/actions/runs/24835968853
  - Installing the Kontell [repository](https://github.com/kontell/repository.kontell):
      - Installing inputstream.tempo
      - KoShelf

## Supported platforms

| Platform | Kodi 22 (Piers) |
|----------|-----------------|
| Linux x86_64 | yes |
| Linux armv7 (Pi 2+) | yes |
| Linux aarch64 (Pi 3+) | yes |
| Android ARM32 | yes |
| Android ARM64 | yes |
