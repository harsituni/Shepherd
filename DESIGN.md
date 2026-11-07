---
name: Shepherd
description: Live evacuation routing for Edmonton. One plain blue-and-white service across the command dashboard and the public phone app.
colors:
  navy: "#0B3D6E"
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
  closed: "#C62828"
  danger-bg: "#FFF3EC"
  danger-border: "#F6D2BE"
  danger-title: "#8A2F06"
  danger-text: "#6B3A1F"
  danger-icon: "#B4400B"
typography:
  headline:
    fontFamily: "Public Sans, system-ui, sans-serif"
    fontSize: "26px"
    fontWeight: 700
    lineHeight: 1.1
    fontFeature: "tnum"
  title:
    fontFamily: "Public Sans, system-ui, sans-serif"
    fontSize: "18px"
    fontWeight: 700
  title-small:
    fontFamily: "Public Sans, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 600
  body:
    fontFamily: "Public Sans, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
  body-small:
    fontFamily: "Public Sans, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 400
  label:
    fontFamily: "Public Sans, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 600
    letterSpacing: "0.06em"
  caption:
    fontFamily: "Public Sans, system-ui, sans-serif"
    fontSize: "12px"
    fontWeight: 400
rounded:
  marker: "4px"
  control: "6px"
  card: "8px"
  touch: "10px"
  pill: "999px"
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
    typography: "{typography.title-small}"
  button-primary-hover:
    backgroundColor: "{colors.blue-hover}"
  button-primary-disabled:
    backgroundColor: "{colors.border}"
    textColor: "{colors.muted}"
  button-primary-phone:
    backgroundColor: "{colors.blue}"
    textColor: "{colors.surface}"
    rounded: "{rounded.touch}"
    height: "52px"
  button-outline:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.blue}"
    rounded: "{rounded.control}"
    height: "40px"
    padding: "0 14px"
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
    backgroundColor: "{colors.tint}"
    textColor: "{colors.navy}"
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
  action-help:
    backgroundColor: "{colors.navy}"
    textColor: "{colors.surface}"
    rounded: "{rounded.touch}"
    height: "48px"
  toast:
    backgroundColor: "{colors.navy}"
    textColor: "{colors.surface}"
    rounded: "{rounded.card}"
    padding: "12px 14px"
---

# Design System: Shepherd

## Overview

**Creative North Star: "The Public Service Map"**

Shepherd looks like a civic service, not a product launch. The map is the subject; everything around it is plain white paper with navy and blue ink, organised like a good government information page: a solid navy masthead, a thin tinted status strip, then content in calm, bordered panels. Nothing competes with the hazard, which is the only warm colour on screen.

The two surfaces share one system at two densities. The **dashboard** (emergency managers, desktop) is a three-column command layout: controls, map, stats and feeds. It is dense but quiet, with small uppercase section labels and tabular numbers. The **phone** (residents, ~390px) is the same vocabulary scaled for thumbs and stress: larger targets, softer 10px corners on the controls you press, one primary action per view, and an always-visible action bar.

The visual rejections are explicit and binding (see Do's and Don'ts): no gradients, no glass, no glows, no emoji icons, no default "AI website" fonts, no decorative charts. Depth comes from 1px borders and tint, never from shadows.

**Key Characteristics:**
- White surfaces, navy chrome, blue as the single interactive and route colour.
- Orange means hazard and red means closed road. Neither colour ever appears for any other purpose.
- Flat. 1px borders and the tint fill separate surfaces.
- Public Sans throughout, with tabular numerals for every time, ETA, distance and stat.
- Touch targets of at least 44px everywhere and at least 48px for primary phone actions.

## Colors

A cool, low-saturation blue-and-white civic palette, with one warm signal colour kept for danger.

### Primary
- **Service Blue** (#0070C4): the one interactive colour. Primary buttons, selected-state borders, focus rings, range accents, the tab underline, evacuation routes, and the dashed predicted-spread rings. On the phone it is also the ETA figure and the "you" dot. Hover deepens to **Pressed Blue** (#005A9E).
- **Masthead Navy** (#0B3D6E): headers, shelter markers, selected-state text, icon-button glyphs, the toast and the "Need help" action. **Deep Navy** (#0A3360) is only the track behind the dashboard's Live/Drill switch.

### Signal
- **Hazard Orange** (#D9480F): the active hazard only, used as fills, outlines, the incident-banner dot, the start marker and report-pin strokes.
- **Closure Red** (#C62828): closed roads, the "Roads closed" stat and SOS reports only.
- **Evacuation Tint family**, shared by both surfaces for evacuation-order alerts and "no safe route" states: background **Ember Wash** (#FFF3EC), border **Ember Edge** (#F6D2BE), title **Ember Ink** (#8A2F06), body **Ember Text** (#6B3A1F) and icon **Ember Mark** (#B4400B).

### Neutral
- **Ink** (#0B2545): body text and values.
- **Slate Muted** (#3B5A7A): secondary text, field labels, unselected tabs, section titles.
- **Slate Faint** (#5B7590): timestamps, hints, slider ticks, idle states. Meant for metadata on white.
- **Frost Border** (#D3E3F2): control and card borders.
- **Frost Divider** (#E3ECF5): panel separators and list rules, lighter than a border.
- **Sky Tint** (#EAF3FB): selected fills, hover rows, the incident banner, the reroute notice.
- **Map Paper** (#F3F7FB): the map background under the desaturated basemap, and the page behind the phone column on desktop.
- **On-Navy Muted** (#BFD7EE): secondary text on the navy header.

### Named Rules
**The Two Warnings Rule.** Orange is the hazard; red is a closed road. Neither may be used for decoration, emphasis, branding, or generic errors.

**The One Ink Rule.** Blue is the only interactive colour. Anything blue is either clickable, selected, or a route/prediction on the map.

**The Quiet Basemap Rule.** The OpenStreetMap raster is desaturated (saturation −0.85, contrast −0.15, opacity 0.6) over Map Paper, so Shepherd's own layers are always the loudest thing on the map.

## Typography

**Font:** Public Sans (Google Fonts, weights 400/500/600/700), with `system-ui, sans-serif` as the fallback. One family for everything.

**Character:** a US-government-designed sans, neutral and legible, chosen because it reads as public service rather than startup.

### Hierarchy
- **Headline** (700, 26–28px, line-height 1.1, tabular): stat tile values (26px) and the phone ETA (28px). Numbers, not sentences.
- **Title** (700, 17–18px): brand name, phone shelter name, sheet headings.
- **Title Small** (600, 15px): alert titles, list item titles, the next-turn instruction, primary button labels.
- **Body** (400–500, 14px): banner text, controls, toggle rows. The phone uses 13–16px depending on the control.
- **Body Small** (400, 13px): supporting copy, report notes, field labels.
- **Label** (600, 12–13px, uppercase, 0.06em tracking): dashboard section titles such as "Simulate & predict". Dashboard only.
- **Caption** (400, 11–12px): timestamps, header sub-lines, legend entries, map labels (600 11px with a white halo).

### Named Rules
**The Tabular Rule.** Every number that updates (T+min, ETA, km, counts, percentages) uses `font-variant-numeric: tabular-nums` (the `.num` class), so live values don't jitter as they tick.

**The 16px Input Rule.** Phone text inputs are 16px so iOS doesn't zoom on focus.

## Layout

- **Dashboard:** a full-height column with a navy header (padding 14px 28px), the incident banner (10px 28px), then a wrapping three-column flex row: controls (260–300px, 24px padding), the map centre (grows, map minimum height 620px) with a history slider bar along the bottom, and a side panel (340–380px, 24px padding) with a 2×2 stat-tile grid and tabs. The map has the legend at bottom-left and zoom buttons at top-right, both inset 16px.
- **Phone:** a single column, max 480px wide and 100dvh tall, centred on Map Paper with 1px side borders on desktop. Navy header, alert banner, tabs, scrolling content (route map 290px tall), and a fixed three-button action bar that respects `env(safe-area-inset-bottom)`.
- **Spacing rhythm:** 4 / 6 / 8 / 12 / 14 / 16 / 20 / 24 px, with a 28px horizontal gutter on the dashboard chrome and 20px on the phone. Gaps inside groups are 6–8px; between sections, 14–24px.
- **Responsive:** below 1100px the dashboard panels stack and the separators move from left/right borders to top/bottom (map minimum 480px). Below 600px the gutters drop to 16px.

## Elevation & Depth

Shepherd is flat. Surfaces are white and separated by 1px Frost Border or Frost Divider lines; selection and hover use Sky Tint. There are no drop shadows on cards, panels, buttons or tiles.

### Shadow Vocabulary
- **Tab underline** (`box-shadow: inset 0 -3px 0 #0070C4`): the selected-tab indicator. It's an inset rule, not elevation.
- **Map label halo** (`text-shadow: 0 0 3px #fff, 0 0 3px #fff`): keeps map labels legible over the basemap.
- **Scrim** (`rgba(11, 37, 69, 0.45)`): the dimmed backdrop behind the phone report sheet.

### Named Rules
**The One Float Rule.** At most one soft shadow exists in the whole system, and it belongs only to a floating pop-up notification. Everything else stays flat.

## Shapes

- **Control** (6px): dashboard buttons, inputs, selects, segmented controls, icon buttons, zoom buttons and the legend. Phone text areas and icon buttons.
- **Card** (8px): dashboard stat tiles, phone notices, the no-route card, the toast and phone choice tiles.
- **Touch** (10px, phone only): the controls a resident presses with a thumb, i.e. the primary button, action-bar buttons and the report sheet's top corners.
- **Pill** (999px): the dashboard Live/Drill switch and the phone hazard-type filter pills.
- **Marker** (4px): shelter squares on the map. Hazard/priority swatches use 3px.

**The Per-Surface Corner Rule.** 6/8px is the shared language. 10px and pills are phone-only affordances for large touch controls; don't carry 10px onto the dashboard.

## Components

### Buttons
Plain and confident, with solid fills and no ornament.
- **Primary:** Service Blue fill, white 600 label. Dashboard: 48px tall, 6px corners, 15px label. Phone: 52px tall, 10px corners, 16px label. Hover goes to Pressed Blue; disabled goes to Frost Border fill with Slate Muted text.
- **Outline:** white with a 1px Service Blue border and blue 600 13px label, 40px tall (e.g. "Back to live"). Disabled turns the border and text grey.
- **Icon button:** 44×44px square with a 1px border and navy glyph (dashboard). The play/pause button inverts to a Service Blue fill. Phone close buttons are borderless and muted.
- **Focus:** a 2px Service Blue outline with a 2px offset on every focusable control.

### Choices, segmented controls and pills
- **Choice tile:** a 44–48px white tile with a 1px border. Selected gets a 1.5px Service Blue border, Sky Tint fill and navy 600 text. Uses `aria-pressed` on the dashboard and `aria-checked` on the phone.
- **Segmented control:** buttons joined inside one 6px bordered container. Selected gets Sky Tint and navy text. The "Evacuation order" severity uses the Ember Wash/Ember Ink pair when selected.
- **Pill (phone):** 44px tall, fully rounded, with the same selected treatment as a choice tile.

### Inputs
- **Style:** a 1px Frost Border on white with 6px corners. 40px minimum height and 14px text on the dashboard; 16px text on phone textareas.
- **Range sliders and checkboxes:** native controls with `accent-color: #0070C4`.

### Navigation
- **Header:** a solid navy masthead with the Shepherd name (700) and a sub-line in On-Navy Muted. The dashboard adds the Live/Drill pill switch (the selected half is white with navy text) and a last-updated caption.
- **Tabs:** full-width, equal-flex, 44px (dashboard) or 48px (phone) tall, Slate Muted 500 text. The selected tab is navy 600 with the 3px blue inset underline, and the row sits on a Frost Divider.

### Stat tiles (dashboard)
A 2×2 grid of four tiles only: People at risk, Roads closed, Active reroutes and Shelter capacity used. Each has 14px padding, an 8px corner and a 1px border, with a 12px muted label over a 26px 700 tabular value. Roads closed takes Closure Red; Active reroutes takes Service Blue.

### Incident banner and alerts
- **Incident banner (dashboard):** a Sky Tint strip with a bottom border, an 8px hazard-orange status dot (grey when idle), a bold hazard name and a muted status line.
- **Alert banner (phone):** an icon plus a 15px 700 navy title and a 13px muted line on Sky Tint. An evacuation order switches the whole banner to the Evacuation Tint family.

### Feed and report lists
Rows divided by Frost Divider lines, with no cards. Each row has a 14px 600 title (SOS in Closure Red), a 12px Slate Faint time and location, and a 13px muted note. Hovering a row fills it with Sky Tint, and every row is at least 44px tall.

### Phone action bar and toast
- **Action bar:** a three-column grid of 48px buttons with 10px corners. "Report hazard" is white with a border, "I'm safe" is Sky Tint with a blue border, and "Need help" is solid navy.
- **Toast:** a solid navy bar with 8px corners and white 500 14px text, floating just above the action bar.

### Map layers (signature)
- **Hazard core:** Hazard Orange fill at 0.85 opacity with a 1.5px orange outline. **Buffer:** orange at 0.3 opacity.
- **Predicted spread:** Service Blue fill at 0.06 with a 1.5px dashed line (`[3, 3]`, 0.6 opacity), labelled T+30 / T+60 in navy 600 12px with a halo.
- **Route (phone):** a 5px Service Blue line with round caps and joins.
- **Closed road:** Closure Red, solid when closed and dashed when slowed.
- **Shelter:** a 20px navy square (4px corners, 2px white border) with a 600 11px label.
- **Report pin:** a white circle with a 2.5px hazard-orange stroke. **Priority resident:** a navy-outlined diamond. **You:** an 18px blue dot with a 3px white ring.

## Do's and Don'ts

### Do:
- **Do** use Public Sans only, at weights 400/500/600/700.
- **Do** keep surfaces flat and white, separated by 1px Frost Border (#D3E3F2) or Frost Divider (#E3ECF5).
- **Do** use Sky Tint (#EAF3FB) plus a 1.5px Service Blue border for every selected state.
- **Do** keep touch targets at least 44px, primary phone actions at least 48px, and text contrast at least 4.5:1.
- **Do** use tabular numerals for every live number.
- **Do** use simple inline stroke SVG icons.
- **Do** keep both apps on the same token values. A colour added to one `index.css` belongs in the other, and here, too.

### Don't:
- **Don't** use Inter, Roboto, Poppins, Montserrat, DM Sans, Manrope, Space Grotesk, Plus Jakarta Sans, Geist, Outfit or any other default "AI website" font.
- **Don't** use gradients of any kind: backgrounds, buttons, text or glows.
- **Don't** use emoji as icons.
- **Don't** use glassmorphism or blur, neon glows, coloured left-border accent cards, oversized rounded "bubble" cards or bouncy animations.
- **Don't** use orange or red for anything except the hazard and closed roads.
- **Don't** add drop shadows to cards, tiles or panels. The only one allowed is on a floating pop-up notification.
- **Don't** add filler stats, decorative charts or lorem ipsum. Every number comes from the backend or a fixture.
- **Don't** use the Government of Alberta logo or wordmark. Shepherd is its own brand.
