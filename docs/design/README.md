# Design reference (from Claude Design)

`Home.dc.html` and `Session.dc.html` are the approved mockups. They are written in a design-canvas format (`<x-dc>`, `<sc-for>`, `<sc-if>`, `{{holes}}`, a `DCLogic` class). Treat them as a visual spec: copy colors, sizes, gradients, shadows, keyframes and SVG geometry exactly, but rebuild the markup as normal React + Tailwind components. Do not copy the canvas runtime syntax.

These supersede the matching parts of `docs/DESIGN.md`.

## Home: what changed
- **Sphere orb** (208 px): layered radial gradient (pale gold core to deep ember), inset shadows for 3D shading, a blurred specular highlight top-left, a faint bounce light bottom-right, outer glow. It breathes (scale 1 to 1.04, 4.5 s).
- **Corona** (300 px) behind the orb: soft radial glow, opacity pulse.
- **Pulse rings**: three 228 px rings, staggered 1.2 s, expanding to 1.22x and fading, so they stay inside the petal ring.
- **Petal ring (>= 880 px wide only)**: five SVG arc sectors around the orb, in a 460x460 SVG, radius 170, stroke 46 with round caps. Clockwise from top: Home, History, Insights, Library (shows song count), WHOOP (green dot = connected). Exact arc paths are in `Home.dc.html`. Bottom petals are drawn counter-clockwise so labels read left to right. Active petal is warm orange; hover/focus brightens. Each petal is a real link and keyboard-focusable.
- **Settings** moved to a 44 px round gear button, top right of the header.
- **Removed** the Library and WHOOP status cards (their info now lives on the petals).
- **Below 880 px**: no petal ring; bottom tab bar with Home, History, Insights, Library.
- All animation stops under `prefers-reduced-motion`.

## Session
Unchanged from `Session.dc.html`: ring timer around artwork, now playing, progress, transport, "Why this mix", Up next, body stats, Chime out.
