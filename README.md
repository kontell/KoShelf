### Kodi client for AudioBookShelf

The client is working, however seeking is broken.

Kodi's audi player, PAPlayer doesn't support tempo (playback speed adjustment). 

Video player does, but that requires syncing playback to display which has caused audio problems for me.

Seeing that inputstream.ffmpegdirect has ffmpeg built-in, I figured that it could be used to modify tempo.

Claude addded the capability easily, see the fork here: https://github.com/kontell/inputstream.tempo

However seeking is broken, see a proposed solution here: https://github.com/xbmc/xbmc/pull/28163
