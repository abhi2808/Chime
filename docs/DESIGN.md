# Chime design

Direction: **Apple Music's calm layout and big artwork, Spotify's dense track rows, and one glowing orb** as the memorable element. The orb is taken from the reference in `docs/reference/inspiration.png` (dark navy screen, warm glowing orb, frosted "End session?" card, ring timer). Everything else stays quiet.

Mobile-first (design at 390 px wide), works on desktop. Dark only for v1.

**Redesign (2026-10-07).** Home and Session were redrawn in Claude Design; the approved mockups are `docs/design/Home.dc.html` and `docs/design/Session.dc.html`, with notes in `docs/design/README.md`. Where they disagree with this file, they win, and the sections below have been brought in line.

## Principles
1. **One bold thing: the orb.** It is the Chime in button on Home, the pulsing centerpiece in a session, and the color signature of a session in History. Keep everything around it disciplined.
2. **Color means something.** Each session type owns a hue. The orb, the history card accent, and the player glow all use that hue. No decorative gradients elsewhere.
3. **Say what the body said.** Show real WHOOP numbers with honest labels (recovery, sleep, strain, HRV). Never call anything "live stress".
4. **Sentence case, plain verbs.** No all-caps labels, no tracked-out eyebrows, no arrows in button text. One exception, from the approved mockup: the petal labels on Home's ring are uppercase with 1.2 tracking, because they are set on a curve where mixed case reads as noise. Screen readers get the sentence-case name from `aria-label`.
5. **Quiet motion.** One entrance moment on Home, a slow breathing orb during sessions, sheets that spring open in response to a tap. No hover animations on every card. Respect `prefers-reduced-motion` (static orb, no breathing).

## Tokens (define as CSS variables, expose in Tailwind theme)
Color
- `--midnight` `#0A0F24` base background: a radial from `--dusk` `#121A3D` at 50% 30%, through midnight at 45%, to `--abyss` `#05070F`
- `--mist` `#F3F5FB` primary text
- `--fog` `#98A2BC` secondary text
- `--glass` `rgba(255,255,255,0.06)` surface, with `1px` border `rgba(255,255,255,0.10)` and `backdrop-filter: blur(24px)`
- `--danger` `#FF5C6C` destructive actions only (and the WHOOP petal's dot when the grant is dead)
- `--ember-soft` `#FFB27A` active nav label and selected chip text; `--ember-bright` `#FF9A3D` link hover
- `--sheet` `rgba(16,20,40,0.92)` sheet surface, blur 28: more opaque than glass so it reads over the orb's glow
- The sphere has its own ramp (`--sphere-core` … `--sphere-rim`, plus shade, light, bounce, glow, aura, corona, pulse). All of it lives in `frontend/src/styles/tokens.css`.

Session hues (orb, accents, glow)
- `--ember` `#FF7A1A` workout
- `--amber` `#FFB238` wake up
- `--moss` `#6FD6A0` focus
- `--indigo` `#7080FF` wind down
- Auto resolves to one of the four after Chime in; before that the orb uses ember at reduced intensity.

Type (one family): **Figtree** variable, self-hosted via `@fontsource-variable/figtree`.
- display 40/44 weight 800, title 28/34 weight 700, headline 20/26 weight 650, body 16/24 weight 450, caption 13/18 weight 500
- Numbers: tabular figures. Session timer 56/60 weight 300.
- Line length under 70 characters.

Shape and space
- Radii, deliberately different: sheets and big cards 28, tiles and chips 18, artwork 14 (12 in list rows), pills 999.
- 4 px spacing scale. Screen padding 20. Minimum tap target 44.
- Elevation comes from glass + blur, not drop shadows.

## Navigation
- **Below 880 px:** bottom tab bar with Home, History, Insights, Library (84 px, `midnight` at 85% with blur, active item in `--ember-soft`). Settings is the 44 px round gear at the top right of Home.
- **From 880 px:** no tab bar. On Home the **petal ring** around the orb is the navigation. Every other screen gets a slim top bar (wordmark with a small sphere back to Home; History, Insights, Library; the gear), because without it the only way off History would be the back button.
- While a session is active, a **mini player bar** sits above the tab bar, or at the foot of the page from 880 px (artwork, title, play/pause, hue-coloured progress line). Tapping opens Session.

## Screens

### Home
```
Good evening, Abhinav                                   (gear)
Recovery 41% · Sleep 63% · Strain 9.4        (three small figures, WHOOP)

          HOME
   WHOOP         HISTORY          (petal ring, >= 880 px only)
          ( SPHERE )
          Chime in
 LIBRARY 1,842    INSIGHTS

"Low recovery and a late evening. A slow, warm mix would fit."   (why-line, plain text)

[ Last session card: Wind down, 38 min, Wired -> Steady · yesterday, 7:15 PM ]
```
- **Sphere orb**, 208 px: a layered radial gradient from a pale gold core to deep ember, inset shadows for 3D shading, a blurred specular highlight top-left, a faint bounce light bottom-right, an outer glow. "Chime in" is written on it. It breathes (scale 1 to 1.04, 4.5 s).
- **Corona**, 300 px, behind it: a soft radial glow pulsing in opacity on the same 4.5 s.
- **Pulse rings**: three 228 px rings, staggered 1.2 s, expanding to 1.22x and fading, so they stay inside the petals.
- **Petal ring (>= 880 px)**: five SVG arc sectors in a 460 box, radius 170, stroke 46, round caps. Clockwise from the top: Home, History, Insights, Library (with the synced song count), WHOOP (a moss dot when connected, danger when it needs reconnecting). The bottom two are drawn counter-clockwise so their labels read left to right. Active petal is ember; hover and focus brighten it, and keyboard focus turns its edge white. Each petal is a real link. WHOOP has no screen of its own, so its petal leads to Settings.
- **The Library and WHOOP cards are gone from Home.** Their detail lives on the Library screen and in Settings; Home keeps only what the petals cannot say. If WHOOP is disconnected, the figures line becomes a single "Connect WHOOP" link and Chime in still works on mood and time.
- **The why-line** is written in the browser from `/api/body-state` (readiness, day part, a workout in the last hour). It names a feel, never a session type, because the mood in the sheet can change what Auto resolves to.
- **While a session is live** the sphere takes that session's hue (the same lighting, mixed from the hue), reads "Your session", and leads back to it.
- All animation stops under `prefers-reduced-motion`; the pulse rings are not drawn at all.

**Press and hold to shift.** A tap opens the sheet with intent `match`. Holding the orb inflates it like a bubble over ~1.2 s and then bursts, opening the sheet with intent `shift` preselected. The hold is a shortcut, not the only route: the sheet always carries the control.
- Inflating: scale to ~1.12, the glow thins and lightens, a faint highlight arc appears near the top. It reads as a bubble under pressure, not as a loading spinner.
- Burst at 1.2 s: the orb pops outward and vanishes for ~120 ms while the sheet rises, with the hue already flipped to the shift target.
- Release before 1.2 s: it deflates back to idle over ~180 ms and opens as `match`. Cancelling is silent and costs nothing, which is what makes the gesture safe to discover by accident.
- Do not fire the sheet on pointer-down. The sheet opens on release or on burst, so a hold that is abandoned by dragging off the orb does nothing.
- `prefers-reduced-motion`: no inflate, no burst. The orb holds still, the hue crossfades to the shift target and a caption reads "Shift" after 1.2 s. Same timing, same outcome.
- Keyboard and screen reader: there is no hold gesture. Enter or Space opens the sheet as `match`, and the in-sheet control does the rest. The orb's `aria-label` stays "Chime in"; the hold is announced nowhere because it is not required to reach anything.

### Chime in sheet (bottom sheet, glass)
```
How are you feeling?
[Wired] [Drained] [Flat] [Steady] [Fired up]     (single select chips, 18 radius)

Take me
(Here)  Somewhere else                            (segmented, two options)

Session
(Auto)  Workout  Focus  Wind down  Wake up        (segmented, hue dot on each)

[ Start ]                                          (pill, filled with session hue)
```
Chips are pills (14 px, weight 600, glass with a 14% white edge); the selected one is ember-edged on an 18% ember fill with `--ember-soft` text, whatever the session type. The sheet is 460 wide on `--sheet` with a close button beside the title. Auto is preselected. **Mood is optional** (decided 2026-09-22, which overrides both this file's old "Start is disabled until a mood is chosen" and the mockup's disabled Start): without one the mix runs on body data and the time of day.

"Take me **here**" is intent `match`, "**somewhere else**" is `shift`; the wording avoids "opposite", which is wrong for steady and overstates the change for wired. Arriving by hold preselects "somewhere else". Choosing it recolours the orb and the Start pill to the hue of where the session is heading, so the intent is visible before you commit. When mood is steady, show the control with "somewhere else" available but add the caption "Steady has nowhere to move to, so this changes nothing."

### Session
```
(hue dot) Wind down                         18 min elapsed
        ( ring = time elapsed, 248 px, stroke 4 )
        [  artwork, inset 18, radius 22, hue glow  ]
        Track title  (19 / 700)
        Artist
        ------------------  1:12        3:08
        [prev]  ( play/pause: mist disc )  [next]

[ Why this mix: the sentence, always shown; the rules folded under "How it was built" ]
Up next                     (rows: art, title, artist, energy dots, open in Spotify)
[ Recovery 41% ] [ Sleep 63% ] [ Strain now 10.1 ]   (tiles; recovery and sleep are from the start)

[ Chime out ]               (glass pill, bottom)
```
Row overflow menu: "Feels calmer", "Feels more intense", "Remove from this session", "Open in Spotify".

### Chime out sheet (frosted card, like the reference's "End session?")
```
Wrap up this session?
How do you feel now?   [Wired] [Drained] [Flat] [Steady] [Fired up]
[toggle] Keep this playlist     (name field appears when on)

[ Keep going ]      primary, session hue
[ Chime out ]       secondary glass
```
After confirming: a short summary card (minutes, songs played, skips, mood in -> mood out, WHOOP snapshot), then back to Home.

### History (important)
Grouped by day, newest first. A filter row of chips: All, session types, Kept. A quiet week summary at top (sessions, total time, most common mood shift).

Session card:
```
Yesterday, 7:15 PM                              38 min
(hue dot) Wind down
Entered  Wired · Recovery 41% · Sleep 63%
Left     Steady
[art][art][art][art] +8      12 played · 3 skipped      Kept / Removed
```
Left edge carries a 4 px bar in the session hue. Entered/Left are two aligned rows so the change reads at a glance.

Session detail:
- Header: hue glow, session name, date and duration.
- **Before and after** panel: mood in -> mood out; WHOOP at start (recovery, HRV, sleep) and day strain at start -> end. State plainly that WHOOP updates through the day, so short sessions show small changes.
- **Why this mix**: the stored why_text and the target profile.
- **Songs**: full list with per-song outcome (played fully, skipped at 0:08) shown as a thin bar, plus energy dots. Each row opens the song in Spotify.
- **Timeline**: mood re-checks, adaptations, WHOOP refreshes from session_events.
- Actions: **Bring it back as a playlist** (recreates from the stored tracks), Delete this record.

Empty state: "No sessions yet. Chime in and they will show up here."

### Settings
Grouped list: Connections (Spotify, WHOOP with reconnect), the WHOOP card that used to sit on Home (last update, last workout, refresh), Sources (liked songs, playlists, top tracks), Explicit songs, Default on Chime out (keep or remove), Data (delete all my data). Discovery slider appears in Phase 8.

## Components to build once and reuse
`Orb` (props: hue, size, state idle | pulsing | inflating | bursting | expanding), `MoodChips`, `SessionTypeSegment`, `IntentSegment`, `Sheet`, `TrackRow`, `MiniPlayer`, `SessionCard`, `StatFigure`, `EmptyState`.

## Copy
- Buttons name the action and keep that name everywhere: "Chime in", "Chime out", "Keep going", "Save playlist", "Bring it back".
- Errors say what happened and what to do, without apologizing. Example: "Spotify isn't open on any device. Open Spotify on your phone or laptop, then try again."
- WHOOP disconnected: "WHOOP isn't connected, so this mix uses your mood and the time of day."

## Accessibility floor
Contrast of text on glass at least 4.5:1. Visible focus ring (2 px, `--mist`). The orb and sheets are keyboard operable. Animated elements have a static fallback.

## Spotify attribution
Follow Spotify's design guidelines (https://developer.spotify.com/documentation/design): link songs back to Spotify and show the required attribution wherever Spotify content is displayed. Do not restyle the Spotify mark.
