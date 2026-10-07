---
name: Beam
description: Send a file with a link. No account, gone in about a day.
colors:
  action-blue: "#2559e6"
  action-blue-deep: "#1d4bcc"
  action-blue-wash: "#e8efff"
  sun: "#ffd23f"
  sun-wash: "#fff8dc"
  danger: "#c4321f"
  danger-wash: "#fdecea"
  danger-ink: "#8f2416"
  success: "#1f8a55"
  selection: "#ffe680"
  desk: "#eceff3"
  desk-dot: "#d9dee5"
  panel: "#fcfcfd"
  on-accent: "#fcfcfd"
  title-bar: "#f6f7f9"
  line: "#dadee4"
  line-soft: "#e8ebef"
  ink: "#15171a"
  ink-2: "#464d58"
  ink-3: "#5c6470"
  icon-quiet: "#8a93a0"
  scrollbar: "#c3c9d2"
  icon-blue: "#2f6bff"
  kind-image: "#22966a"
  kind-video: "#6d4bd8"
  kind-audio: "#e2702a"
  kind-sheet: "#0e8a8a"
  kind-archive: "#b98a00"
  kind-code: "#3a4350"
  kind-other: "#6a7280"
typography:
  display:
    fontFamily: "Figtree Variable, Figtree, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "30px"
    fontWeight: 750
    lineHeight: 1.15
    letterSpacing: "-0.025em"
  headline:
    fontFamily: "Figtree Variable, Figtree, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "24px"
    fontWeight: 750
    lineHeight: 1.25
    letterSpacing: "-0.02em"
  title:
    fontFamily: "Figtree Variable, Figtree, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "17px"
    fontWeight: 650
  body:
    fontFamily: "Figtree Variable, Figtree, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Figtree Variable, Figtree, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "14px"
    fontWeight: 650
  small:
    fontFamily: "Figtree Variable, Figtree, system-ui, -apple-system, Segoe UI, sans-serif"
    fontSize: "14px"
    fontWeight: 400
  mono:
    fontFamily: "JetBrains Mono Variable, JetBrains Mono, ui-monospace, SF Mono, Menlo, monospace"
    fontSize: "15px"
    fontWeight: 400
rounded:
  window: "14px"
  field: "12px"
  control: "10px"
  small: "8px"
  pill: "999px"
spacing:
  tight: "8px"
  stack: "22px"
  gutter: "28px"
  gutter-mobile: "16px"
  window-inset: "40px"
components:
  button-primary:
    backgroundColor: "{colors.action-blue}"
    textColor: "{colors.on-accent}"
    rounded: "{rounded.control}"
    padding: "0 18px"
    height: "42px"
  button-primary-hover:
    backgroundColor: "{colors.action-blue-deep}"
  button-primary-lg:
    backgroundColor: "{colors.action-blue}"
    textColor: "{colors.on-accent}"
    rounded: "{rounded.control}"
    padding: "0 24px"
    height: "50px"
  button-quiet:
    backgroundColor: "transparent"
    textColor: "{colors.action-blue}"
    rounded: "{rounded.control}"
    padding: "0 12px"
    height: "38px"
  button-quiet-hover:
    backgroundColor: "{colors.action-blue-wash}"
  icon-button:
    backgroundColor: "transparent"
    textColor: "{colors.ink-3}"
    rounded: "{rounded.small}"
    size: "32px"
  icon-button-hover:
    backgroundColor: "{colors.line-soft}"
    textColor: "{colors.ink}"
  window:
    backgroundColor: "{colors.panel}"
    rounded: "{rounded.window}"
    width: "600px"
  window-bar:
    backgroundColor: "{colors.title-bar}"
    textColor: "{colors.ink-2}"
    typography: "{typography.label}"
    height: "44px"
    padding: "0 14px"
  share-field:
    backgroundColor: "{colors.title-bar}"
    textColor: "{colors.ink}"
    typography: "{typography.mono}"
    rounded: "{rounded.field}"
    padding: "6px"
  share-field-copied:
    backgroundColor: "{colors.sun-wash}"
  copy-button-copied:
    backgroundColor: "{colors.success}"
    textColor: "{colors.on-accent}"
    rounded: "{rounded.control}"
  progress:
    backgroundColor: "{colors.line-soft}"
    rounded: "{rounded.pill}"
    height: "10px"
  notice:
    backgroundColor: "{colors.title-bar}"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.control}"
    padding: "10px 14px"
  notice-error:
    backgroundColor: "{colors.danger-wash}"
    textColor: "{colors.danger-ink}"
    rounded: "{rounded.control}"
    padding: "10px 14px"
---

# Design System: Beam

## Overview

**Creative North Star: "The Desktop You Drop Things On"**

Beam is one near-white window resting on a dotted grey desk. Files are drawn as real document objects, with folded corners, type glyphs and a colored extension tag, and they physically move: they fan out under the cursor, lift when you drag, drop into the window, settle when the upload finishes. What comes out the other side is a link, and the moment it arrives is marked with a single warm highlight, sun yellow. Everything else stays cool, quiet and grey so that the file and the link carry the screen.

The system is low density and centred on a single surface. One 600px window per screen holds the entire task. Above it sits the brand at top left, and below it a row of three plain facts aligned to the window's left edge. The window chrome borrows from desktop operating systems (a title bar with the state centred in it) but is modernised: no window-control dots, generous radius, soft layered shadow, no bevels. Colour is functional. Blue means "act", sun means "this just happened to your file", and the per-kind icon tints tell you what the file is.

The user has explicitly rejected the "gradient AI look". The centred gradient drop-card is the refused alternative, and no surface in the build uses a tonal gradient fill.

**Key Characteristics:**
- One window per screen, a 600px column centred and anchored high on a dotted desk.
- Drawn file icons, tinted by kind, are the main imagery. They move with a soft overshooting ease.
- Solid blue for actions. Sun yellow is the only warm accent and appears only as a transient state.
- Figtree for everything people read. JetBrains Mono only for link and ID data.
- Depth comes from layered ambient shadows and drop-shadows on file icons, all tinted from one shadow colour. Surfaces have no borders apart from hairline rings.

## Colors

The palette is cool grey with a single saturated blue, plus one warm yellow held back for moments. Every UI colour is a custom property on `:root`, and no component hard-codes a hex value.

### Primary
- **Action Blue** (`action-blue`): the colour of doing. It fills primary buttons ("Choose a file", "Copy link", "Download"), the progress fill, the focus ring, the share field's focus ring and the quiet-button text. Hover darkens it to **Action Blue Deep**. Text on blue is **On Accent** (`on-accent`), a faintly tinted near-white, not pure white. **Action Blue Wash** is used only as the quiet-button hover ground.

### Secondary
- **Sun** (`sun`): the only warm highlight. It appears in three places: the 3px ring around the window while a file is dragged over the page, the ring around the share field when a fresh link arrives (it fades back to grey over 1.6s), and the same ring when the link is copied. **Sun Wash** fills the surface inside those rings. **Selection** (`selection`), a paler sun, is the text-selection colour. The BeamMark's folded corner is also sun.

### Tertiary
- **File-kind tints** (`kind-*`, plus `icon-blue` for documents): eight mid-saturation hues used only inside the drawn file icons. They colour the extension tag, glyph and corner fold, so a photo reads green, a video violet, audio orange, a sheet teal, an archive ochre, code slate and anything else grey. `icon-blue` is a brighter blue than Action Blue, shared by the doc icon and the BeamMark tile. It belongs to illustration and is never used for UI controls.

### Neutral
- **Desk** (`desk`) with **Desk Dot** (`desk-dot`): the page ground, a 22px grid of 1px dots. The theme-color meta matches Desk.
- **Panel** (`panel`): the window body. It is a tinted near-white, the lightest surface in the system, and never pure #ffffff.
- **Title Bar** (`title-bar`): the window's title strip, and also the resting ground for the share field and neutral notices.
- **Line** (`line`) / **Line Soft** (`line-soft`): Line is the share field's inset ring. Line Soft is used for the title-bar divider, the footer divider, the progress track and the icon-button hover.
- **Ink** (`ink`), **Ink 2** (`ink-2`), **Ink 3** (`ink-3`): primary text, secondary text (subheads, labels, window title) and tertiary text (meta, facts, hints, footer). Ink 3 is the lightest text value and still reads at about 5.2:1 on Desk.
- **Icon Quiet** (`icon-quiet`): the small line icons in the facts row. It is quieter than the text they sit beside.
- **Scrollbar** (`scrollbar`): the scrollbar thumb on a transparent track.
- **Danger** (`danger`) / **Danger Wash** (`danger-wash`) / **Danger Ink** (`danger-ink`): Danger Wash is the error notice ground, and Danger Ink is the error text that sits on it.
- **Success** (`success`): only the Copy button's confirmed state ("Copied").

### Named Rules
**The One Warm Thing Rule.** Sun yellow marks something that is happening to your file right now: the drag, the fresh link, the copy. It never decorates and never rests on a surface permanently. If a screen at rest shows sun anywhere except the BeamMark, that is a bug.

**The No Tonal Gradient Rule.** No fill blends one colour into another. The only CSS gradient function in the build is the hard-stop radial dot pattern on the desk. It produces texture, not a colour blend. Everything else is flat colour, including backgrounds, buttons, progress bars, text, icons and loading skeletons.

**The Blue Means Act Rule.** Action Blue appears only where you can act or where an action is in progress (buttons, progress, focus). Kind tints and icon-blue live inside illustrations only.

## Typography

**Display Font:** Figtree Variable (with system-ui, -apple-system, Segoe UI fallback)
**Body Font:** Figtree Variable
**Label/Mono Font:** JetBrains Mono Variable (with ui-monospace, SF Mono, Menlo fallback)

**Character:** Figtree is a friendly geometric sans with heavy weights that stay warm. It sets every human-readable line, from a 30px heading down to 13px footnotes. JetBrains Mono is reserved for machine data and reads as "this is the thing you copy".

### Hierarchy
- **Display** (750, 30px, 1.15, -0.025em, balanced wrap): the single heading in the idle drop window ("Drop a file to send it"). Drops to 25px under 640px.
- **Headline** (750, 24px, 1.25, -0.02em, balanced, breaks anywhere): the filename or status heading on the download page.
- **Brand** (800, 21px, -0.02em): the "Beam" wordmark next to the mark. Not used elsewhere.
- **Title** (650, 17px): the filename in a file row.
- **Body** (400, 16px, 1.5): base text. The drop subhead is set slightly larger (16.5px) in Ink 2, with a 34ch measure and pretty wrap.
- **Button** (650, 15px; 16px on large buttons).
- **Label** (650, 14px): the window title and the share field label, in Ink 2.
- **Small** (400, 13–15px): meta, facts, hints, notices and footer, in Ink 3. Numbers that change (sizes, percentages) use tabular figures.
- **Mono** (400, 15px in the share field; 12.5px for the file ID in the window bar).

### Named Rules
**The Mono Is Data Rule.** JetBrains Mono appears only on values a person copies or matches: the share URL and the file ID. File sizes and percentages stay in Figtree with tabular numerals.

**The Extension Survives Rule.** A filename never loses its extension. Long names truncate in the middle of the stem with an ellipsis, and the extension stays pinned and visible ("Beach trip — Aug…(edited).mov"). On the download page, where the name is the headline, it wraps anywhere instead of truncating.

## Layout

The page is a three-row grid: a top bar (brand only, max 1040px, 22px × 28px padding), the stage, and a one-line footer. The stage is a single centred column capped at 600px. Its top padding is `clamp(24px, 9vh, 112px)`, so the window sits high in the viewport, not vertically centred. Below the window sits the facts row: three icon-plus-text items (size limit, expiry, no account) with a 10px × 28px gap and 22px above. The row is left-aligned to the window's edge (4px inset). That is the one deliberate break from the centred composition: it reads as a caption to the window, not a second centred block.

Inside the window, centred states (drop, receive) use a 44px top inset and 40px on the sides and bottom, with centred text. Transfer states (uploading, done) are left aligned with a 32px inset. Vertical rhythm between blocks is about 22–28px, and gaps within a group are 6–12px.

Under 640px, gutters shrink to 16px, the stage top padding to 8px, and window insets to 36/20/28px. The facts row becomes a left-aligned column. The share field stacks with a full-width Copy button. The transfer footer stacks. The window-bar meta (the file ID) is hidden.

## Elevation & Depth

Depth is layered and ambient. Every shadow is built from one shadow colour (`--shadow-rgb: 20 24 32`, used inside `rgb()` with alpha), and the button highlight is built from `--highlight-rgb: 255 255 255`. Shadows sit as soft stacks beneath a near-white window on a grey desk, and drawn file icons cast their own drop-shadows so they read as objects lying above the surface. Nothing uses a hard offset shadow, and borders are replaced by 1px rgba rings or inset rings.

### Shadow Vocabulary
- **Window** (`0 1px 2px rgb(20 24 32 / 0.06), 0 14px 36px -10px rgb(20 24 32 / 0.22)` plus a `0 0 0 1px rgb(20 24 32 / 0.07)` ring): the single main surface.
- **Window, highlighted**: the same shadow with the ring swapped for `0 0 0 3px` Sun, and the window lifted 2px.
- **File object** (`drop-shadow(0 2px 2px rgb(20 24 32 / 0.08)) drop-shadow(0 6–10px 8–14px rgb(20 24 32 / 0.10–0.14))`): on every drawn file icon. The blur grows with icon size (44px row, 64–72px fan, 88px receive).
- **Primary button** (`0 1px 2px rgb(20 24 32 / 0.12), inset 0 1px 0 rgb(255 255 255 / 0.18)`): a faint lift and a top highlight, nothing more.

### Named Rules
**The Objects Cast Shadows Rule.** Shadows belong to things that sit on the desk, namely the window and the files. Text, controls inside the window and notices do not cast shadows.

## Shapes

Corners are generous and soft. The window is 14px. The share field is 12px. Buttons and notices are 10px. Icon buttons and skeleton blocks are 8px. The progress bar is a full pill. The focus outline has its own 6px radius so it follows the control. The file icon has a folded top-right corner and a 2.5px-radius body. The BeamMark is an 8/32 rounded square containing the same folded-file silhouette, so the mark and the icons come from one drawing.

## Components

### Window
The app's one container. It is a near-white panel with a 44px title bar, laid out in three columns: an empty spacer on the left, the state as a centred title ("Send a file", "Sending…", "Ready to share", "Someone sent you a file"), and optional mono meta on the right (the file ID on the download page). There are no window-control dots. While a file is dragged over the page, the window lifts 2px, gains a 3px Sun ring, and its body fills with Sun Wash (220ms ease-out).

### Buttons
- **Shape:** gently rounded (10px).
- **Primary:** solid Action Blue, On Accent 650-weight text, a leading 18px line icon. Default height 42px; large is 50px with 24px padding, used for the single main action on a screen.
- **Hover / Active:** hover darkens to Action Blue Deep, and active presses down 1px (140ms ease-out). Focus is a 2.5px Action Blue outline offset 2px.
- **Quiet:** transparent with Action Blue text, 38px tall, and a Blue Wash fill on hover. Used for secondary routes ("Send another", "Send a file of your own").
- **Icon button:** 32px square, Ink 3, with a Line Soft fill on hover. Used for the cancel ×.

### File Icon (signature)
A drawn 48×60 document. It has a white body with a #c9ced6 hairline, a corner fold tinted at 22% of the kind colour, a kind glyph (image landscape, play triangle, waveform, zipper, code brackets, grid, text lines), and a solid kind-coloured tag with the uppercase extension in white 800-weight type. The label takes the system font stack from `--font`, so it is always Figtree. The idle screen fans three icons (photo, pdf, zip) at -11°/0°/10°. Hovering lifts the centre one, and dragging spreads all three. Missing files show a ghosted, greyscale, tilted icon at 45% opacity.

### File Row
A 44px icon, then the filename (Title type, middle-truncated, extension pinned), then a 10px pill progress bar in Action Blue on Line Soft (scaleX, 160ms linear), with "x of y" and a percentage in tabular Small type beneath. The icon drops in on mount (file-in: from 26px above, -7°, 112% scale, 560ms) and does a small settle bounce when the upload completes.

### Share Field
A 12px-radius Title Bar trough with a Line inset ring. It holds the mono URL (selects all on focus) and a 128px-minimum primary Copy button. Focus-within swaps the ring to 2px Action Blue. When the link first arrives, the ring and wash are Sun and fade back to grey over 1.6s. When the link is copied, the field holds the Sun ring and wash for 2.2s, and the button turns Success green with a check and "Copied".

### Notices
Inline 10px-radius strips in 14.5px text with a leading icon. Neutral notices use the Title Bar ground. Errors use Danger Wash with Danger Ink text.

### Loading Skeleton
Flat 8px-radius Line Soft blocks shaped like the incoming content (icon 88×110, a 260px line, a 140px line). They pulse in opacity between 1 and 0.45 (1.2s ease-in-out, alternating). There is no shimmer gradient.

## Do's and Don'ts

### Do:
- **Do** keep each screen to one 600px window on the dotted desk, with the task inside the window.
- **Do** use Sun (#ffd23f) only for transient file events: drag-over, fresh link, copied.
- **Do** set the share URL and file IDs in JetBrains Mono, and everything else in Figtree.
- **Do** truncate filenames in the middle and keep the extension visible.
- **Do** represent files with the drawn File Icon, tinted by kind, casting its object drop-shadow.
- **Do** move file objects with the `cubic-bezier(0.16, 1, 0.3, 1)` ease, and respect reduced motion (all animation collapses to 1ms).
- **Do** use tabular numerals for sizes, percentages and anything else that counts.

### Don't:
- **Don't** use gradient fills, gradient text or gradient buttons. The user rejected the "gradient AI look". The desk's hard-stop dot pattern is the only gradient-function use. Loading skeletons pulse in opacity instead.
- **Don't** build a centred gradient drop-card. The window with a title bar is the container.
- **Don't** use Sun as a resting decoration, a badge colour or a second brand colour.
- **Don't** use icon-blue or the kind tints for controls. Actions are Action Blue only.
- **Don't** put mono type on prose, labels or headings.
- **Don't** add window-control dots or other fake OS chrome to the title bar. It holds the state title and optional meta, nothing else.
- **Don't** hard-code hex or rgb values in UI components. Use the `:root` properties, and build shadows from `--shadow-rgb`. Drawn illustrations (the file icon and BeamMark) are the exception and keep their own fixed fills.
