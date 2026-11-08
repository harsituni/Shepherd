---
name: Shepherd
description: Live evacuation routing for Edmonton. One plain blue-and-white service across the command dashboard and the public phone app.
colors:
  navy: "#0B3D6E"
  header: "#005072"
  navy-deep: "#0A3360"
  blue: "#0070C4"
  blue-hover: "#005A9E"
  tint: "#EAF3FB"
  border: "#D3E3F2"
  divider: "#E3ECF5"
  text: "#0B2545"
  muted: "#3B5A7A"
  muted-2: "#5B7590"
  on-navy-muted: "#BFD7EE"
  map-bg: "#F3F7FB"
  surface: "#FFFFFF"
  hazard: "#D9480F"
  hazard-high: "#7A1F0A"
  closed: "#C62828"
  predicted: "#C62828"
  evac-stripe: "#FFD400"
  evac-edge: "#9A6B00"
  danger-bg: "#FFF3EC"
  danger-border: "#F6D2BE"
  danger-title: "#8A2F06"
  danger-text: "#6B3A1F"
  danger-icon: "#B4400B"
  focus: "#FEBA35"
typography:
  headline:
    fontFamily: "Public Sans, system-ui, sans-serif"
    fontSize: "26px"
    fontWeight: 700
    lineHeight: 1.1
    fontFeature: "tnum"
  heading:
    fontFamily: "Public Sans, system-ui, sans-serif"
    fontSize: "20px"
    fontWeight: 700
  title:
    fontFamily: "Public Sans, system-ui, sans-serif"
    fontSize: "18px"
    fontWeight: 700
  body:
    fontFamily: "Public Sans, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 400
  body-strong:
    fontFamily: "Public Sans, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 600
  body-small:
    fontFamily: "Public Sans, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
  label:
    fontFamily: "Public Sans, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 600
rounded:
  swatch: "3px"
  marker: "4px"
  control: "6px"
  card: "8px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "20px"
  2xl: "24px"
  gutter: "28px"
components:
  button-primary:
    backgroundColor: "{colors.blue}"
    textColor: "{colors.surface}"
    rounded: "{rounded.control}"
    height: "48px"
    typography: "{typography.body-strong}"
  button-primary-hover:
    backgroundColor: "{colors.blue-hover}"
  button-primary-disabled:
    backgroundColor: "{colors.divider}"
    textColor: "{colors.muted-2}"
  button-primary-phone:
    backgroundColor: "{colors.blue}"
    textColor: "{colors.surface}"
    rounded: "{rounded.control}"
    height: "52px"
  button-outline:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.navy}"
    rounded: "{rounded.control}"
    height: "40px"
    padding: "0 14px"
  control-disabled:
    backgroundColor: "{colors.map-bg}"
    textColor: "{colors.muted-2}"
  icon-button:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.navy}"
    rounded: "{rounded.control}"
    size: "44px"
  choice:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.control}"
    height: "44px"
  choice-selected:
    backgroundColor: "{colors.navy}"
    textColor: "{colors.surface}"
  choice-selected-locked:
    backgroundColor: "{colors.muted-2}"
    textColor: "{colors.surface}"
  segment-evacuation-selected:
    backgroundColor: "{colors.danger-title}"
    textColor: "{colors.surface}"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.control}"
    height: "40px"
    padding: "0 10px"
  tab:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.muted}"
    height: "44px"
  tab-selected:
    textColor: "{colors.navy}"
  stat-tile:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.text}"
    rounded: "{rounded.card}"
    padding: "14px"
  header:
    backgroundColor: "{colors.navy}"
    textColor: "{colors.surface}"
  incident-banner:
    backgroundColor: "{colors.tint}"
    textColor: "{colors.text}"
  alert-evacuation:
    backgroundColor: "{colors.danger-bg}"
    textColor: "{colors.danger-title}"
  action-secondary:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.navy}"
    rounded: "{rounded.control}"
    height: "48px"
  action-help:
    backgroundColor: "{colors.navy}"
    textColor: "{colors.surface}"
    rounded: "{rounded.control}"
    height: "48px"
  toast:
    backgroundColor: "{colors.navy}"
    textColor: "{colors.surface}"
    rounded: "{rounded.control}"
    padding: "12px 14px"
---

# Design System: Shepherd

## Overview

**Creative North Star: "The Public Service Map"**

Shepherd looks like a civic service, not a product launch. The map is the subject; everything around it is plain white paper with navy and blue ink, organised like a good government information page: a solid Alberta-blue masthead, a thin tinted status strip, then content in calm, bordered panels. Nothing competes with the hazard, which is the only warm colour on screen.

The two surfaces share one system at two densities. The **dashboard** (emergency managers, desktop) is a three-column command layout: controls, map, stats and feeds. It is dense but quiet, with plain sentence-case section headings and tabular numbers. The **phone** (residents, ~390px) is the same vocabulary scaled for thumbs and stress: larger targets, one primary action per view, and an always-visible action bar. Both surfaces use the same square-ish 6px corners and the same type scale, in the manner of Alberta.ca: plain, text-led and squared off rather than rounded and app-like.

The visual rejections are explicit and binding (see Do's and Don'ts): no gradients, no glass, no glows, no emoji icons, no default "AI website" fonts, no decorative charts, no pill shapes. Depth comes from 1px borders, never from shadows. The Sky Tint is reserved for the alert surface.

**Key Characteristics:**
- White surfaces, navy chrome, blue as the single interactive and route colour.
- Orange means hazard now; red means danger ahead: a closed road, the predicted spread, or a call for help. Neither colour ever appears for any other purpose.
- Flat. 1px borders separate surfaces; the tint belongs to the alert banner alone.
- One solid button per area; everything else is a plain outline.
- Public Sans throughout, with tabular numerals for every time, ETA, distance and stat.
- Touch targets of at least 44px everywhere and at least 48px for primary phone actions.

## Colors

A cool, low-saturation blue-and-white civic palette, with one warm signal colour kept for danger.

### Primary
- **Service Blue** (#0070C4): the one primary-action and route colour. Primary buttons, range accents, the tab underline and evacuation routes. On the phone it is also the "you" dot and the Advisory severity label. Hover deepens to **Pressed Blue** (#005A9E).
- **Alberta Header Blue** (#005072): the dashboard header and the phone's Shepherd mark (the phone is map-first, with no header bar), matching Alberta's brand dark blue (`--goa-color-brand-dark` in the GoA design tokens). White text on it is 8.8:1.
- **Masthead Navy** (#0B3D6E): shelter markers, selected-state fills (choice tiles and segmented controls), outline-button borders and labels, icon-button glyphs and the toast. **Deep Navy** (#0A3360) is a reserved token and currently unused.

### Signal
- **Hazard Orange** (#D9480F): the active hazard only, used as fills, outlines, the incident-banner dot, the start marker and report-pin strokes.
- **Fire Core** (#7A1F0A): the hottest part of a wildfire on the dashboard map (its centre, shading out to Hazard Orange at the edge), and the centre of the "Active hazard" legend swatch. Darker than Closure Red so the two never read as the same thing. Nothing else.
- **Closure Red** (#C62828): closed roads (solid), the predicted spread (dotted rings, token `predicted`), unsafe shelters (the square and its pop-up text, 5.6:1 on white), the "Roads closed" stat, SOS reports, and the phone's "Need help" button (white text, 5.6:1). Nothing else.
- **Evacuation Yellow** (#FFD400, token `evac-stripe`) and **Evacuation Edge** (#9A6B00, token `evac-edge`): the evacuation zone around each wildfire only. Diagonal stripes of Evacuation Yellow on a transparent fill, inside a solid 2px Evacuation Edge border. Evacuation Edge is the same deep yellow as the dashboard's selected "Alert" severity segment. Nothing else.
- **Clear Green** (#1E7B34, token `clear`): the "Clear" route status on the phone only (the label and its square swatch, on the route cards and in Route details), 5.3:1 on white. Nothing else.
- **Focus Gold** (#FEBA35): the keyboard focus ring only, as on Alberta.ca: a 3px outline. Never decoration, never a fill. Gold on white is about 1.7:1, below WCAG 2.2's 3:1 guidance for focus indicators, so the 3px width is what carries it. If an accessibility review flags it, keep the gold and add a 1px navy ring inside it rather than switching back to blue.
- **Evacuation Tint family**, shared by both surfaces for evacuation-order alerts and "no safe route" states: background **Ember Wash** (#FFF3EC), border **Ember Edge** (#F6D2BE), title **Ember Ink** (#8A2F06), body **Ember Text** (#6B3A1F) and icon **Ember Mark** (#B4400B). Ember Ink is also the fill of the selected "Evacuation" severity segment (white text, which passes 4.5:1 where Hazard Orange would not).

### Neutral
- **Ink** (#0B2545): body text and values.
- **Slate Muted** (#3B5A7A): secondary text, field labels, unselected tabs, section titles.
- **Slate Faint** (#5B7590): timestamps, hints, slider ticks, idle states and disabled labels. Also the fill of a selected choice that is locked while a simulation runs.
- **Frost Border** (#D3E3F2): control and card borders.
- **Frost Divider** (#E3ECF5): panel separators and list rules, lighter than a border. Also the fill of a disabled primary button.
- **Sky Tint** (#EAF3FB): the alert surface only, i.e. the dashboard incident banner and the phone alert banner. Not for selection, hover, notices or buttons.
- **Map Paper** (#F3F7FB): the map background under the desaturated basemap, the page behind the phone column on desktop, hover rows, and the fill of disabled controls.
- **On-Navy Muted** (#BFD7EE): secondary text on the header (5.9:1 on Alberta Header Blue).

### Named Rules
**The Two Warnings Rule.** Orange is the hazard now (with Fire Core at a wildfire's centre); red is danger ahead: a closed road, the predicted spread, or a call for help (SOS reports and the phone's "Need help" button). Line style keeps the reds apart on the map: closed roads are solid lines (dashed when slowed), the predicted spread is dotted closed rings. Neither colour may be used for decoration, emphasis, branding, or generic errors.

**The One Ink Rule.** Blue marks the primary action and the route. Anything blue is either the main thing to press or a route on the map. Selection is navy, not blue.

**The One Tint Rule.** Sky Tint means "this is the alert". If the banner and a hint look the same, the banner has lost its authority, so inline hints and notices are plain text with an icon.

**The Quiet Basemap Rule.** The OpenStreetMap raster is desaturated (saturation −0.85, contrast −0.15, opacity 0.8) over Map Paper, so Shepherd's own layers are always the loudest thing on the map while street names stay readable on a phone outdoors.

## Typography

**Font:** Public Sans (Google Fonts, weights 400/500/600/700), with `system-ui, sans-serif` as the fallback. One family for everything.

**Character:** a US-government-designed sans, neutral and legible, chosen because it reads as public service rather than startup.

### Hierarchy
One scale for both surfaces, exposed as tokens in each `index.css`: `--fs-sm` 14px, `--fs-body` 16px, `--fs-brand` 18px, `--fs-h` 20px. Nothing on screen is smaller than 14px except MapLibre's attribution.

- **Headline** (700, 26px, line-height 1.1, tabular): dashboard stat tile values only. Numbers, not sentences. The phone has no big stat number; its ETA reads inline (see Route summary).
- **Heading** (700, 20px): phone shelter name, report sheet heading.
- **Title** (700, 18px): dashboard panel titles such as "Simulate" (sentence case, no uppercase tracking). **Brand name (dashboard header):** "Shepherd" alone, no subtitle, 700 26px beside the 32px logo mark, its capital band centred on the mark (measured: within 0.25px); the p's descender hangs below as descenders do.
- **Body** (400–600, 16px): the default size. Alert titles, banner text, phone tabs, inline notices, list item titles, the next-turn instruction, primary button labels, inputs and selects.
- **Body Small** (400–500, 14px): supporting copy, field labels, hints, report notes, timestamps, header sub-lines, legend entries, dashboard tabs, choice and segment labels, action-bar labels.
- **Label** (600, 14px): map labels (with a white halo), field values, the history label.

### Named Rules
**The No Eyebrow Rule.** No small uppercase tracked labels above headings. A section has a plain bold heading or nothing.

**The Tabular Rule.** Every number that updates (T+min, ETA, km, counts, percentages) uses `font-variant-numeric: tabular-nums` (the `.num` class), so live values don't jitter as they tick.

**The 16px Input Rule.** Phone text inputs are 16px so iOS doesn't zoom on focus.

## Layout

- **Dashboard:** a full-height column with an Alberta Header Blue header (padding 14px 28px), the incident banner (10px 28px), then a wrapping three-column flex row: controls (260–300px, 24px padding), the map centre (grows, map minimum height 620px) with a history slider bar along the bottom, and a side panel (340–380px, 24px padding) with a 2×2 stat-tile grid and tabs. The map has the legend at bottom-left and zoom buttons at top-right, both inset 16px.
- **Phone:** a single column, max 480px wide and 100dvh tall, centred on Map Paper with 1px side borders on desktop. A 56px Alberta Header Blue header with even padding, so the brand and city share one centre line (a 28px white placeholder mark with a navy crook, left of the Shepherd name, same as the dashboard), alert banner, tabs (Route · Alerts), scrolling content, and a fixed three-button action bar that respects `env(safe-area-inset-bottom)`. The route map is `min(440px, 55dvh)` tall until a location is set (the map is the whole task then), and 290px after, with a one-row map key under it.
- **Spacing rhythm:** 4 / 6 / 8 / 12 / 14 / 16 / 20 / 24 px, with a 28px horizontal gutter on the dashboard chrome and 20px on the phone. Gaps inside groups are 6–8px; between sections, 14–24px.
- **Responsive:** below 1100px the dashboard panels stack and the separators move from left/right borders to top/bottom (map minimum 480px). Below 600px the gutters drop to 16px.

## Elevation & Depth

Shepherd is flat. Surfaces are white and separated by 1px Frost Border or Frost Divider lines; selection is a navy fill and hover is Map Paper. There are no drop shadows on cards, panels, buttons or tiles.

### Shadow Vocabulary
- **Tab underline** (`box-shadow: inset 0 -3px 0 #0070C4`): the selected-tab indicator. It's an inset rule, not elevation.
- **Map label halo** (`text-shadow: 0 0 3px #fff, 0 0 3px #fff`): keeps map labels legible over the basemap.
- **Scrim** (`rgba(11, 37, 69, 0.45)`): the dimmed backdrop behind the phone report sheet.

### Named Rules
**The One Float Rule.** Shadows belong only to things that float. The phone's notification pop-up carries the strongest one; the phone's map screen controls, which float over a busy map (area chip, alert card, rail buttons, route panel and strip, Need help bar), carry one lighter soft shadow (`0 2px 10px rgba(11, 37, 69, 0.16)`) to separate them from it; shelter pop-ups a lighter one still. Everything that sits in the page stays flat.

## Shapes

- **Control** (6px): every button, input, select, segmented control, choice tile, icon button, zoom button, the legend, the toast and the phone no-route card, on both surfaces.
- **Card** (8px): dashboard stat tiles and the top corners of the phone report sheet.
- **Marker** (4px): shelter squares on the map. **Swatch** (3px): hazard/priority legend swatches.

**The Square Corner Rule.** Corners stay at 6px, with 8px for cards. No 10px "bubble" controls and no pills (999px). A two-way or three-way choice is a segmented control (one bordered strip with joined buttons), not a row of pills.

## Components

### Buttons
Plain and confident, with solid fills and no ornament.
- **Primary:** Service Blue fill, white 600 16px label, 6px corners. Dashboard: 48px tall. Phone: 52px tall. Hover goes to Pressed Blue; disabled goes to Frost Divider fill with Slate Faint text.
- **Outline (secondary):** white with a 1px navy border and a navy 600 14px label, 40px tall on the dashboard (e.g. "Back to live") and 48px in the phone action bar.
- **Icon button:** 44×44px square with a 1px navy border and navy glyph (dashboard). The play/pause button is the panel's one solid Service Blue button. Phone close buttons are borderless and muted.
- **Disabled:** a distinct flat style, never an opacity fade. Frost Border outline, Map Paper fill, Slate Faint label. A disabled fieldset turns its labels and slider accents Slate Faint.
- **Focus:** a 3px Focus Gold outline with a 2px offset on every focusable control. Tabs, segmented-control buttons and the Live/Simulation switch draw it inside (`outline-offset: -3px`) so the edges aren't clipped.

**The One Solid Rule.** Each area has at most one solid-filled button: play/pause in the controls panel, "Send update" in Notify, "Start navigation" in the phone route view, and "Need help" in the phone action bar. Everything beside it is an outline. Never give three side-by-side buttons three different treatments.

**The Never Disabled Rule.** "Need help" is never disabled. Without a pinned location it asks the device for one, and if that fails it tells the resident to tap the map or call 911.

### Choices and segmented controls
- **Choice tile:** a 44–48px white tile with a 1px border and 6px corners. Selected is a navy fill with white 600 text. Uses `aria-pressed` on the dashboard and `aria-checked` on the phone. A selected tile that is locked (disabled while a simulation runs) becomes a Slate Faint fill with white text, so the choice stays visible.
- **Segmented control:** buttons joined inside one 6px bordered container, separated by 1px Frost Border rules. Selected is a navy fill with white 600 text. The "Evacuation" severity uses an Ember Ink fill when selected. Used for the dashboard speed and severity controls.
- **Live/Simulation switch (dashboard header):** the same segmented form on navy, with an On-Navy Muted 1px border. The selected half is white with navy text.

### Inputs
- **Style:** a 1px Frost Border on white with 6px corners, 16px text. 40px minimum height on the dashboard.
- **Range sliders and checkboxes:** native controls with `accent-color: #0070C4`.

### Navigation
- **Header:** a solid Alberta Header Blue (#005072) masthead with a 28px white placeholder mark, the Shepherd name (700) and a sub-line in On-Navy Muted. The dashboard adds the Live/Simulation segmented switch and a 14px last-updated line.
- **Tabs:** full-width, equal-flex, Slate Muted 500 text. Dashboard: 44px tall, 14px (four tabs share a narrow column). Phone: 48px tall, 16px. The selected tab is navy 600 with the 3px blue inset underline, and the row sits on a Frost Divider.

### Stat tiles (dashboard)
A 2×2 grid of four tiles only: People at risk, Roads closed, Active reroutes and Shelter capacity used. Each has 14px padding, an 8px corner and a 1px border, with a 14px muted label over a 26px 700 tabular value. Roads closed takes Closure Red; Active reroutes takes Service Blue.

### Incident banner and alerts
- **Incident banner (dashboard):** a 16px Sky Tint strip with a bottom border, an 8px hazard-orange status dot (grey when idle), a bold hazard name and a muted status line.
- **Alert banner (phone):** an icon plus a 16px 700 navy title and a 14px muted line (at most two lines) on Sky Tint. It shows the most severe active government notification, else the nearest hazard. The second line is the hazard relation when known ("Fire is 2.4 km west of you, moving east."). Advisory has a blue info icon, Alert a navy warning icon, and an evacuation order (or being inside the hazard) switches the whole banner to the Evacuation Tint family.
- **Notification pop-up (phone):** slides down over the top of the map screen when a new government notification arrives (220ms ease-out, none under reduced motion). A white card with 8px corners, a 1px border and the system's one soft shadow (`0 8px 24px rgba(11,37,69,0.18)`). A severity icon, a 14px 600 severity · time line, a 16px 700 title, and "Tap to read" expanding to the message; a close button dismisses it. Evacuation orders use the Ember Edge border.
- **Severity colours:** Advisory = Service Blue, Alert = Masthead Navy, Evacuation order = Ember Ink text with an Ember Mark icon. These colour the severity label and icon only, never a left-border stripe or fill.
- **Inline notice (phone):** plain 16px text with a leading stroke icon, with no box, fill or border. Hints ("Tap the map…") are Slate Muted; the reroute notice is navy 600 so it reads as news.

### Route summary (phone)
The shelter name as a 20px 700 heading, then one 16px line: **ETA** in Ink 700, then distance and "% full" in Slate Muted, separated by middots ("**6 min** · 4.1 km · 41% full"). No eyebrow label and no oversized ETA figure.

### Alerts tab (phone)
Government notifications, newest first, as plain divided rows: the coloured severity · time line, a 16px bold title and a 14px muted message. The empty state is one muted sentence.

### Feed and report lists
Rows divided by Frost Divider lines, with no cards. Each row has a 16px 600 title (SOS in Closure Red), a 14px Slate Faint time and location, and a 14px muted note. Hovering a row fills it with Map Paper, and every row is at least 44px tall.

### Phone map screen and toast
- **Map-first** (like a scooter app): the map fills the screen; every control floats over it on white with a 1px Frost Border, 8px corners and the light float shadow.
- **Top:** area chip (28px mark + place name, 600 14px) top left; the alert / evacuation card top right, compact (14px title, 22px headline, detail lines hidden) with a muted chevron; the whole card is one button that opens it to full width (30px headline, detail lines shown).
- **Rail:** four 64px square buttons stacked on the right just above the route panel: icon + 600 14px navy label (Alerts with a navy count badge, Key, Report, Safe).
- **Route panel:** opens at the height of its main content (cards, drive mode, Start evacuating, the location-shared line) with the top of a "Route details" heading (16px 700, a muted down chevron) peeking under a Frost Divider; the panel scrolls vertically to show those details: shelter (open, spaces free of capacity), trip, fire forecast status and its line, leave-by and directions when the backend sends them, the drive-mode explanation, and a straight-line-estimate note when the route is approximate. Rows are a 112px 14px Slate Muted label column beside the value, separated by Frost Divider rules. The shelter card row still scrolls sideways (cards 84% wide with an explicit width, so the selected 2px navy border wraps the whole card in Safari too). Cards show name, status ("Clear" in Clear Green), and "8 min · 3.7 km · 0% full · Recommended"; a clear route adds no extra line, a blocked one just "Fire forecast on this route". While it's open the rail is hidden, and a subtle 44px white × with a muted icon floats just above its top-right corner; it closes the panel to a 56px one-line strip with a chevron. Tapping the strip slides the panel up from the bottom (320ms, `cubic-bezier(0.22, 1, 0.36, 1)`, none under reduced motion).
- **Need help:** a full-width 56px Closure Red bar with white 700 18px text, always at the bottom.
- **Toast:** a solid navy bar with 6px corners and white 500 14px text, under the top row.

### Map layers (signature)
- **Hazard core:** Hazard Orange fill at 0.85 opacity with a 1.5px orange outline. **Buffer:** orange at 0.3 opacity. On the dashboard a wildfire core also gets three nested bands (the core shrunk to 75 / 50 / 25% toward its centre) stepping from orange to Fire Core at 0.9 opacity: solid colours, not a gradient.
- **Predicted spread** (both surfaces): the single 60 min outline from `GET /forecast` (one ring only: nested 30 + 60 rings read as a doubled border), drawn as a feature with a `predicted_min` property. No fill; a 2px dotted Closure Red line (`line-dasharray [0, 2]`, round caps, 0.9 opacity), labelled T+60 at the leading edge in navy 600 14px with a halo. The legend/key swatch is a 2px dotted red square. They are never drawn or counted as the current hazard.
- **Evacuation zone** (both surfaces): a perfect circle around each wildfire as it is now (never the predicted path), centred on the fire with radius = its farthest edge + 1 km (`EVAC_BUFFER_M` in each app's `src/evacuation.js`), so it always covers the whole fire and grows only as the fire grows, drawn under everything else: a `fill-pattern` of dense 1px (2 device px) diagonal Evacuation Yellow stripes on a 4px tile (canvas-drawn, full opacity) and a solid 2px Evacuation Edge line. It is built from whichever fire shape is drawn, so on the dashboard it follows the history slider. Legend/key swatch: a striped square with a 2px Evacuation Edge border (an inline SVG, not a gradient).
- **Unsafe shelter** (both surfaces): a shelter inside the evacuation circle of the fire now, or of the circle any `/forecast` outline (up to +120 min) would have. Its square turns Closure Red, and its pop-up (hover on the dashboard, tap on the phone) turns red: the capacity line, then one 600-weight line "Unsafe: Find another shelter". Judged from the live fire and forecast, not the slider.
- **Route (phone):** a 5px Service Blue line over a 9px white casing, with round caps and joins, so it stays legible over grey tiles and orange hazards. Never cyan or any off-palette colour.
- **Closed road:** Closure Red, solid when closed and dashed when slowed.
- **Shelter:** a 20px navy square (4px corners, 2px white border) with a 600 14px label. On the phone only the route's destination is labelled, on whichever side of the square has more room.
- **Map key (phone):** opened from the rail's Key button as a sheet, listing only what is drawn (Hazard now, Predicted spread, Your route, Shelter, You), 16px Slate Muted with small swatches. The dashboard keeps its floating legend, bottom-left: a white card (1px Frost Border, 6px corners) under a 24px Alberta Header Blue bar reading "LEGEND" in white 700 14px capitals tracked +0.08em (about 10px tall with ~7px of air above and below, sized to the word, never tight enough to clip it; the one uppercase label in the system, by request; written "Legend" in the markup so screen readers say the word), with a 24px square minimise button (14px minus icon) whose invisible tap area is 44px. Minimising folds the list down into the bar with a 220ms ease height transition (none under reduced motion); then only the blue bar stays, docked at the bottom of the map, with a plus to expand it.
- **Report pin:** a white circle with a 2.5px hazard-orange stroke. **Priority resident:** a navy-outlined diamond. **You:** an 18px blue dot with a 3px white ring. **Evacuee (dashboard):** each phone from `GET /evacuees` as a 12px Service Blue dot with a 2.5px white ring, drawn above every other layer.

## Do's and Don'ts

### Do:
- **Do** use Public Sans only, at weights 400/500/600/700.
- **Do** keep surfaces flat and white, separated by 1px Frost Border (#D3E3F2) or Frost Divider (#E3ECF5).
- **Do** use a navy fill with white text for every selected state, and keep Sky Tint (#EAF3FB) for the alert banner only.
- **Do** keep corners at 6px (8px for cards), and use a segmented control for small option sets.
- **Do** give disabled controls a flat Map Paper / Slate Faint style.
- **Do** use the 14/16/18/20 type scale, with 16px as the default.
- **Do** keep touch targets at least 44px, primary phone actions at least 48px, and text contrast at least 4.5:1.
- **Do** use tabular numerals for every live number.
- **Do** use simple inline stroke SVG icons.
- **Do** keep both apps on the same token values. A colour added to one `index.css` belongs in the other, and here, too.

### Don't:
- **Don't** use Inter, Roboto, Poppins, Montserrat, DM Sans, Manrope, Space Grotesk, Plus Jakarta Sans, Geist, Outfit or any other default "AI website" font.
- **Don't** use gradients of any kind: backgrounds, buttons, text or glows.
- **Don't** use emoji as icons.
- **Don't** use glassmorphism or blur, neon glows, coloured left-border accent cards, oversized rounded "bubble" cards or bouncy animations.
- **Don't** use orange or red for anything except the hazard, closed roads, the predicted spread, unsafe shelters and calls for help (SOS, "Need help"), Evacuation Yellow for anything but the evacuation zone, or Focus Gold for anything but the focus ring.
- **Don't** use pill shapes (999px corners) or 10px "bubble" controls.
- **Don't** fade disabled controls with `opacity`, and never disable "Need help".
- **Don't** set text smaller than 14px, or use small uppercase tracked eyebrow labels.
- **Don't** put three different button treatments side by side.
- **Don't** add drop shadows to cards, tiles or panels. The only one allowed is on a floating pop-up notification.
- **Don't** add filler stats, decorative charts or lorem ipsum. Every number comes from the backend or a fixture.
- **Don't** use the Government of Alberta logo or wordmark. Shepherd is its own brand.
