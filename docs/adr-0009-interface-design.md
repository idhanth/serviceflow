# ADR 0009 - The interface

Status: accepted
Date: 2026-08-31

Phase 9 changed no features. It gave the product an interface a shop would
recognise as software they pay for, rather than one generated from a prompt.

The work was done by rendering pages in a real browser and looking at them -
every decision below came from a screenshot, not from reading the source.

## 1. What was actually wrong

The starting point was not a matter of taste:

- **The whole product rendered in a serif.** `--font-sans` was defined as
  `var(--font-sans)` - a self-reference that resolves to nothing - so every
  screen fell back to the browser's default. Geist was loaded and never used.
- **The admin dashboard was a phase 1 placeholder** reading "Foundation is live.
  Bookings, scheduling and jobs land in the next phases", under a greeting
  ("Good evening, Alex") on an otherwise empty page.
- **The jobs board was a stack of cards**, one per job, on a screen whose whole
  purpose is comparing a day's work.
- **The calendar drew overlapping jobs on top of each other** and labelled them
  in the browser's timezone while positioning them in the shop's, so a job
  labelled 12:00 PM sat on the 9am line.
- **The activity feed printed its own storage format**: "Job — employee: Marcus
  Webb · scheduled start: 2026-09-02T19:00:00-04:00".
- **The jobs board said "No active jobs" while its own footer counted 198**,
  because "active" filtered one page of a date-ordered list client-side.

Those are defects, and they were fixed as such.

## 2. The system

**Type.** Geist, 14px body, one scale used everywhere: page titles 20px
semibold, section headings 15px medium, body 14px, secondary 13px, metadata and
column headers 12px. No page title is larger than 20px - this is a tool, not a
landing page. Numbers are tabular globally, so money, durations and times line
up in every column without each table remembering.

**Colour.** Neutrals carry a trace of blue (hue 250) rather than being pure
grey: invisible as colour, but it stops the product looking like unstyled HTML.
Primary is near-black, so the decisive action needs no hue. There is exactly one
accent - a deep teal - and it is spent only on selection, focus, links and live
work.

**Status.** Six meanings, one colour each: pending, info, active, done, danger,
muted. A booking, a job and a feed entry that mean "waiting on us" look the
same. The default rendering is a dot and a word, not a filled chip - twenty
pills in a column read as decoration, twenty dots read as a status column.
Chips are reserved for the one place a record's state is the headline.

**Shape.** A 6px base radius with small steps, so nothing reads as a bubble.
Elevation is used for things that genuinely float; a table sits on the page with
a single hairline border and no shadow.

**Density.** Sidebar rows 30px, table rows 44px, controls 32px, page gutters 24
to 32px. Every list page is the same frame: page header, toolbar, panel.

## 3. Composition rules that came out of the pages

- **Tables are the product.** Card-per-row was removed from the jobs board. The
  primary column carries the identity (customer and their vehicle, or the
  service and who it is for) with the supporting fact underneath in a quieter
  voice; numbers are right-aligned; column headers are labels, not content.
- **Phones get a list, not a scroll.** A six-column table at 390px pushes the
  status and the price off screen. The two operational tables render the same
  records stacked below `md`. This is not card-per-row returning; it is the same
  data at a width where rows cannot exist.
- **The dashboard answers three questions in order**: what needs a decision from
  me, what is happening today, what is waiting. The counts are counted from the
  API - there is no trend arrow anywhere in this product, because nothing in it
  measures a trend.
- **A closed shop is told about tomorrow.** Today's schedule falls back to the
  next working day rather than showing a void on a Sunday.
- **Forms are grouped by how a person thinks about the record** - Person, Role,
  Qualifications - not presented as one stack of labels. Qualifications became a
  checkbox list; six bordered boxes inside a dialog is a frame too many.
- **Empty states say why it is empty.** A search that found nothing and an empty
  queue are different situations and get different words and different actions.

## 4. Accessibility findings

Two came out of this work and both were fixed at the source:

- Rows were given `role="button"` to make them keyboard-activatable, which
  **destroys the table's row semantics** - a screen reader stops announcing the
  column for each cell. Rows are focusable and activatable while remaining rows,
  and the jobs board's primary cell is a real link so a job can be opened in a
  new tab.
- `Button render={<Link/>}` warned on every page because a non-native button
  keeps button semantics it cannot honour. The `Button` now infers this, so no
  call site has to remember and the console is clean.

The filter count is `aria-hidden` because the table's footer already states the
total, and folding it into the button's name turned "Pending" into "Pending22".
The pager's position is spelled out in visually hidden text rather than in an
`aria-label` on a span, which is not reliably announced.

## 5. What was deliberately not done

No new dependency was added. No animation library, no chart library, no icon
set beyond Lucide, no component framework. Everything above is composition,
spacing, typography and the tokens in `globals.css`.

Motion is limited to 75-100ms colour transitions on hover and selection. Nothing
in this product fades, floats or scales on hover.
