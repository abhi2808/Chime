# Privacy policy

Chime is a personal, open-source project, not a commercial product. It runs on the
owner's own machine or server, and it is limited to a handful of authorized accounts.
This page exists because Spotify and WHOOP require a privacy policy link in their OAuth
consent screens, and because you should know what happens to your data before you
connect anything.

Last updated: 21 September 2026.

## What Chime reads

**From Spotify**, with your permission:

- your profile id and display name, to identify your account,
- your liked songs and the artists on them (names, ids, album art URLs, genres),
- your playback state and devices, so a session can start and follow along.

**From WHOOP**, with your permission:

- your profile name,
- your daily cycle (day strain), recovery (score, HRV, resting heart rate, SpO2, skin
  temperature), sleep (performance and timings), and finished workouts.

WHOOP has no live heart-rate or stress endpoint, and Chime does not attempt to infer one.

## What Chime stores, and where

Everything is stored in a single database file on the machine running Chime — by default
`data/chime.db` on the owner's own computer. There is no Chime server, no hosted account,
and no third party receiving your data.

- **OAuth tokens** are encrypted at rest (Fernet) with a key that lives only in the
  local environment. They are never written to logs.
- **Spotify metadata** (tracks, artists, genres) is cached so Chime does not have to
  re-read your library on every use.
- **WHOOP figures** are stored as the few numbers the app actually uses: recovery, HRV,
  resting heart rate, sleep performance, day strain, SpO2, skin temperature, and workout
  strain and heart rates. Raw WHOOP payloads are not stored and are never logged.
- **Sessions** record how a session started, what played, and how it ended, so History
  can show it back to you.

## What Chime does not do

- No analytics, no tracking, no advertising, no data sold or shared.
- Nothing is posted to your Spotify or WHOOP account. Chime creates playlists you asked
  for and removes them again unless you keep them.
- **No Spotify content is ever sent to an AI or machine-learning model, and nothing is
  trained or fine-tuned on it.** Song tagging is deterministic. Where Chime uses a
  language model at all, it is given only non-Spotify inputs — your WHOOP-derived body
  state, your mood, and the time of day — to write a one-sentence explanation of a mix.
- No email address, postal address, payment details, or precise location is collected.
  Spotify no longer exposes email, country or subscription status to apps like this one,
  and Chime does not ask for them.

## Your control

- **Disconnect Spotify** at https://www.spotify.com/account/apps/ .
- **Disconnect WHOOP** in the WHOOP app under your profile's app connections, or at
  https://developer-dashboard.whoop.com if you are the app owner.
- **Delete everything** by deleting the database file (`data/chime.db`) on the machine
  running Chime. Revoking access above stops any further reads immediately.

Because Chime is self-hosted, the person running the instance controls the database file.
If that is not you, ask them.

## Retention

Data stays in the local database until you delete it or the instance owner does. Cached
Spotify metadata is kept minimal and is always refreshable from Spotify.

## Contact

Open an issue on the project's GitHub repository.
