/** Scoped FullCalendar theme driven by the app's CSS tokens, so it follows light and dark mode. */
const CSS = `
.cortex-fc .fc {
  --fc-border-color: hsl(var(--border));
  --fc-page-bg-color: hsl(var(--card));
  --fc-neutral-bg-color: hsl(var(--muted));
  --fc-neutral-text-color: hsl(var(--muted-foreground));
  --fc-list-event-hover-bg-color: hsl(var(--accent));
  --fc-today-bg-color: hsl(var(--primary) / 0.08);
  --fc-now-indicator-color: hsl(var(--destructive));
  --fc-button-text-color: hsl(var(--foreground));
  --fc-button-bg-color: hsl(var(--background));
  --fc-button-border-color: hsl(var(--input));
  --fc-button-hover-bg-color: hsl(var(--accent));
  --fc-button-hover-border-color: hsl(var(--input));
  --fc-button-active-bg-color: hsl(var(--primary));
  --fc-button-active-border-color: hsl(var(--primary));
  --fc-event-text-color: #fff;
  color: hsl(var(--foreground));
  font-size: 0.8125rem;
}
.cortex-fc .fc .fc-button { font-size: 0.8125rem; text-transform: none; box-shadow: none; }
.cortex-fc .fc .fc-button-primary:not(:disabled).fc-button-active,
.cortex-fc .fc .fc-button-primary:not(:disabled):active { color: hsl(var(--primary-foreground)); }
.cortex-fc .fc .fc-button:focus-visible,
.cortex-fc .fc .fc-event:focus-visible,
.cortex-fc .fc a:focus-visible { outline: 2px solid hsl(var(--ring)); outline-offset: 2px; box-shadow: none; }
.cortex-fc .fc .fc-toolbar-title { font-size: 1rem; font-weight: 600; }
.cortex-fc .fc a { color: inherit; }
.cortex-fc .fc .fc-col-header-cell-cushion,
.cortex-fc .fc .fc-daygrid-day-number { color: hsl(var(--muted-foreground)); text-decoration: none; }
.cortex-fc .fc .fc-list-day-cushion { background: hsl(var(--muted)); }
.cortex-fc .fc .fc-list-event td { background: hsl(var(--card)); }
.cortex-fc .fc .fc-list-event:hover td { background: hsl(var(--accent)); }
.cortex-fc .fc .fc-list-empty { background: hsl(var(--card)); color: hsl(var(--muted-foreground)); }
.cortex-fc .fc .fc-event { cursor: pointer; }
.cortex-fc .fc .fc-daygrid-event { white-space: normal; }
.cortex-fc .fc .fc-popover { background: hsl(var(--card)); border-color: hsl(var(--border)); }
.cortex-fc .fc .fc-popover-header { background: hsl(var(--muted)); color: hsl(var(--foreground)); }
.cortex-fc .fc .cortex-demo { background-image: repeating-linear-gradient(135deg, transparent 0 6px, rgb(255 255 255 / 0.18) 6px 9px); }
`;

export function CalendarTheme() {
  return <style>{CSS}</style>;
}
