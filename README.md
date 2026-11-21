# StreamKeeper 🎥

Prosty w obsłudze rejestrator streamów na żywo (Twitch, YouTube, Kick i inne serwisy obsługiwane przez [streamlink](https://streamlink.github.io/)). Zapisuje transmisję do pliku MP4 bez rekodowania — strumień jest kopiowany 1:1, więc nagrywanie nie obciąża CPU.

[![Licencja MIT](https://img.shields.io/badge/licencja-MIT-zielony.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-%E2%89%A53.9-niebieski.svg)](https://www.python.org)

## Funkcje

- 🎬 **Nagrywanie na żywo** z Twitcha, YouTube, Kicka i [wielu innych serwisów](https://streamlink.github.io/plugins.html)
- 🔗 **Akceptuje różne formaty wejścia** — pełny URL, `@nazwa` kanału YouTube albo samą nazwę kanału (z `--platform`)
- ⏳ **Tryb oczekiwania** (`--wait`) — jeśli stream jeszcze nie wystartował, skrypt czeka i rozpoczyna nagrywanie automatycznie
- 📦 **Zapis do MP4** z faststart (gotowy do odtwarzania w trakcie pobierania) + opcjonalny zapis źródłowego `.ts`
- 🚫 **Blokada reklam na Twitchu** domyślnie włączona (można wyłączyć flagą `--twitch-ads`)
- 🧠 **Rozróżnia przyczyny błędów** — wyraźnie informuje, czy kanał jest offline, czy wybrana jakość nie istnieje
- 🛑 **Łagodne przerywanie Ctrl+C** — plik jest poprawnie finalizowany (przetestowane)

## Wymagania

- **Python 3.9 lub nowszy**
- **ffmpeg** (z `ffprobe`) — [pobierz tutaj](https://ffmpeg.org/download.html); folder `bin` musi być dodany do `PATH`
- **streamlink** — instalacja:

```bash
python -m pip install streamlink
```

## Instalacja

1. Skopiuj plik `StreamKeeper.py` w dowolne miejsce na dysku.
2. Zainstaluj zależności z sekcji [Wymagania](#wymagania).

Gotowe — to pojedynczy plik, bez żadnej dodatkowej konfiguracji.

## Szybki start

```bash
# Nagraj kanał Twitch (nazwa kanału wystarczy)
python StreamKeeper.py TwitchChanel

# Nagraj kanał YouTube przez @nazwę
python StreamKeeper.py @YoutubeChanel

# Wymuś platformę dla zwykłej nazwy kanału
python StreamKeeper.py KickChanel --platform kick

# Pełny URL (dowolny serwis obsługiwany przez streamlink)
python StreamKeeper.py "https://www.youtube.com/@YoutubeChanel/live"
```

Nagrywanie zatrzymuje się klawiszami **Ctrl+C**. Plik MP4 trafia do folderu `recordings/`.

## Wszystkie opcje

```
python StreamKeeper.py CEL [opcje]

CEL:
  URL streamu (dowolny serwis obsługiwany przez streamlink),
  @nazwa kanału YouTube, lub sama nazwa kanału (zobacz --platform)

Opcje:
  --platform {twitch,kick,youtube}
                        platforma dla zwykłej nazwy kanału (domyślnie: twitch)
  --quality JAKOŚĆ     best, worst, 1080p60, 720p60, 480p, audio_only...
                        (domyślnie: best)
  --output-dir FOLDER  folder na pliki .ts (domyślnie: ./recordings)
  --mp4-dir FOLDER     osobny folder na gotowe MP4 (domyślnie: ten sam co --output-dir)
  --no-convert         zostaw tylko plik .ts, pomiń konwersję do MP4
  --keep-ts            nie usuwaj pliku .ts po udanej konwersji
  --wait SEKUNDY       jeśli stream jest offline, sprawdzaj co SEKUNDY
                        i rozpocznij nagrywanie, gdy wystartuje
                        (0 = zakończ od razu, domyślnie: 0)
  --twitch-ads         zachowaj reklamy na Twitchu (domyślnie są blokowane)
  --sl-arg ARG         dodatkowy argument przekazywany do streamlinka,
                       można używać wielokrotnie, np.
                       --sl-arg=--http-cookie --sl-arg=nazwa=wartość
```

## Przykłady

```bash
# Czekaj na start streamu, sprawdzaj co 60 sekund
python StreamKeeper.py xQcOW --wait 60

# Nagrywaj tylko dźwięk, zostaw plik .ts
python StreamKeeper.py "https://twitch.tv/lofi" --quality audio_only --no-convert

# Jakość 720p z zachowaniem pliku źródłowego .ts
python StreamKeeper.py shroud --platform kick --quality 720p --keep-ts

# Stream prywatny / z ograniczeniami — przekaż ciasteczko do streamlinka
python StreamKeeper.py "https://twitch.tv/kanal" --sl-arg=--http-cookie --sl-arg="auth-token=XXX"

# VOD (archiwum) zamiast live — też zadziała
python StreamKeeper.py "https://www.twitch.tv/xqc/videos/123456789"
```

## Jak to działa

1. `resolve_target()` normalizuje cel do postaci URL zrozumiałej dla streamlinka
   (np. `youtu.be/xyz` → `youtube.com/watch?v=xyz`, `@nazwa` → link `/live`).
2. **streamlink** pobiera strumień i wypisuje go na standardowe wyjście (`--stdout`).
3. **ffmpeg** odbiera strumień przez pipe i zapisuje go do pliku `.ts` bez rekodowania
   (`-c copy`) — dlatego obciążenie CPU jest minimalne.
4. Po zakończeniu nagrania ffmpeg przepakowuje `.ts` do `.mp4`
   (bitstream filter AAC stosowany tylko gdy trzeba, flaga `+faststart`).
5. MP4 przechodzi test integralności; plik `.ts` jest usuwany, chyba że podano `--keep-ts`.

## Rozwiązywanie problemów

| Problem | Rozwiązanie |
|---|---|
| `ERROR: ffmpeg not found` | Dodaj folder `bin` ffmpega do zmiennej `PATH` i uruchom terminal ponownie |
| `ERROR: streamlink not installed` | Uruchom `python -m pip install streamlink` |
| „No playable streams" | Kanał jest offline — użyj `--wait`, żeby zaczekać na start |
| „quality 'X' is not available" | Stream działa, ale nie ma takiej jakości — sprawdź wypisane przez streamlinka dostępne opcje lub użyj `best` |
| Nie chcę reklam / chcę reklamy | Domyślnie reklamy Twitcha są blokowane; `--twitch-ads` je przywraca |
| Stream z logowaniem / hasłem | Przekaż dane przez `--sl-arg` (ciasteczka, nagłówki HTTP) |

## Licencja

Projekt wydano na licencji [MIT](LICENSE) — możesz swobodnie używać, kopiować, modyfikować i rozpowszechniać skrypt, także w celach komercyjnych.
