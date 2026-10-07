# Prompt 02: UI redesign from Claude Design

Paste everything below the line into Claude Code.

---

The UI has been redesigned. Read `docs/design/README.md` first, then `docs/design/Home.dc.html` and `docs/design/Session.dc.html`.

**Do not write code yet.** Reply with a short plan: which existing frontend files and components change, which new components you'll add (I expect at least `Orb`, `PetalRing`, `SettingsButton`, and a `Session` screen), and anything in the reference that conflicts with the current code or `docs/DESIGN.md`. Wait for my OK.

After my OK:
1. Rebuild Home to match `Home.dc.html` exactly in look and motion: the sphere orb, corona, pulse rings, five-petal ring at >= 880 px (reuse the exact SVG arc paths), settings gear top right, the removed status cards, and the mobile tab bar below 880 px.
2. Feed the petals real data: Library petal from `/api/library/status`, WHOOP petal shows connected/disconnected (placeholder until Phase 2).
3. Add the Session screen as a static UI page at `/session` using `Session.dc.html` (mock data for now; real wiring is Phase 4).
4. Keep the Chime-in sheet behavior (mood chips, session type, Start disabled until a mood is picked).
5. Respect `prefers-reduced-motion`, keep keyboard focus visible, no hardcoded colors outside the design tokens (add any new ones to the token file).
6. Update `docs/DESIGN.md` so its Home and Navigation sections match `docs/design/README.md`.
7. Run typecheck and lint, then tell me what changed and what to check at 390 px and desktop width.
