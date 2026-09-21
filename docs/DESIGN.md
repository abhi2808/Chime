# Chime design

Direction: **Apple Music's calm layout and big artwork, Spotify's dense track rows, and one glowing orb** as the memorable element. The orb is taken from the reference in `docs/reference/inspiration.png` (dark navy screen, warm glowing orb, frosted "End session?" card, ring timer). Everything else stays quiet.

Mobile-first (design at 390 px wide), works on desktop. Dark only for v1.

## Principles
1. **One bold thing: the orb.** It is the Chime in button on Home, the pulsing centerpiece in a session, and the color signature of a session in History. Keep everything around it disciplined.
2. **Color means something.** Each session type owns a hue. The orb, the history card accent, and the player glow all use that hue. No decorative gradients elsewhere.
3. **Say what the body said.** Show real WHOOP numbers with honest labels (recovery, sleep, strain, HRV). Never call anything "live stress".
4. **Sentence case, plain verbs.** No all-caps labels, no tracked-out eyebrows, no arrows in button text.
5. **Quiet motion.** One entrance moment on Home, a slow breathing orb during sessions, sheets that spring open in response to a tap. No hover animations on every card. Respect `prefers-reduced-motion` (static orb, no breathing).

## Tokens (define as CSS variables, expose in Tailwind theme)
Color
- `--midnight` `#0A0F24` base background, fading to `#05070F` at the bottom of the screen
- `--mist` `#F3F5FB` primary text
- `--fog` `#98A2BC` secondary text
- `--glass` `rgba(255,255,255,0.06)` surface, with `1px` border `rgba(255,255,255,0.10)` and `backdrop-filter: blur(24px)`
- `--danger` `#FF5C6C` destructive actions only

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
- Mobile: bottom tab bar with Home, History, Insights, Settings. Insights is hidden until it exists.
- Desktop (>= 1024): left rail with the same items; content max-width 720, centered.
- While a session is active, a **mini player bar** sits above the tab bar (artwork, title, play/pause, orb-colored progress line). Tapping opens Session.

## Screens

### Home
```
Good evening, Abhinav
Recovery 41% · Sleep 63% · Strain 9.4        (three small figures, WHOOP)

              ( ORB )
             Chime in

"Low recovery and a late evening. A slow, warm mix would fit."   (why-line, plain text)

[ Last session card: Wind down, 38 min, Wired -> Steady ]
[ Library: 1,842 songs synced ]  [ WHOOP: connected ]
```
The orb is ~200 px, slow glow, tappable, aria-label "Chime in". If WHOOP is disconnected the figures are replaced by a single "Connect WHOOP" row and Chime in still works on mood + time.

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
Auto is preselected. Start is disabled until a mood is chosen. On press the orb expands to fill the sheet, then the Session screen appears.

"Take me **here**" is intent `match`, "**somewhere else**" is `shift`; the wording avoids "opposite", which is wrong for steady and overstates the change for wired. Arriving by hold preselects "somewhere else". Choosing it recolours the orb and the Start pill to the hue of where the session is heading, so the intent is visible before you commit. When mood is steady, show the control with "somewhere else" available but add the caption "Steady has nowhere to move to, so this changes nothing."

### Session
```
           (ring = time elapsed)
        [  big artwork, 14 radius, orb glow behind  ]
        Track title
        Artist
        ---------o----------  1:12 / 3:41
        [prev] [play/pause] [next]

Why this mix                (collapsible, 2-3 lines)
Up next                     (rows: art 48, title, artist, energy dots, overflow menu)
Body                        (Recovery, Sleep, Strain: at start; strain now)

[ Chime out ]               (secondary pill, bottom)
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
Grouped list: Connections (Spotify, WHOOP with reconnect), Sources (liked songs, playlists, top tracks), Explicit songs, Default on Chime out (keep or remove), Data (delete all my data). Discovery slider appears in Phase 8.

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
