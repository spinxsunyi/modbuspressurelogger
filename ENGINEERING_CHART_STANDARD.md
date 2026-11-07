# Engineering Chart Standard — V1

This is a functional measurement/readability contract, not a cosmetic UI preference.

## Single source of truth
- `chart_scale.py` owns the fixed Live/History time-window grid, rounded reporting display widths, engineering pressure tick selection, and visual-only reduction.
- Live uses Unix timestamps in **seconds**; History and Reporting use elapsed **minutes**. Grid conversion must respect the axis units.
- Fixed windows: 1 min = 10s/2s; 5 min = 60s/12s; 10 min = 120s/30s; 15 min = 180s/30s; 30 min = 300s/60s; 1h = 600s/120s; 12h = 3600s/900s; 24h = 7200s/1800s (major/minor).
- Grid locations are relative to the axis's time origin; date/time labels represent actual timestamps. Panning must not change spacing.
- Reporting rounds **only visible chart width** to a convenient duration (48 min -> 50 min; 10 min major, 2 min minor). Original timestamps, selected interval, event times, extrema, and stored samples remain unchanged.
- User-entered manual X/Y limits must remain exact. Grid ticks may fall inside those limits without moving the limits.
- Pressure grid intervals use engineering-friendly increments in the axis's displayed units. Raw pressure storage remains canonical psi; axis labels convert units only.

## Chart fidelity
- Display reduction is never used for recording persistence or statistical computation.
- Preserve local minima/maxima and all non-OK samples; invalid samples must render as gaps, not as zero pressure or a continuous line across missing data.
- The in-memory 24h buffer is not a replacement for persistent History.
- Any PCE test pass/fail decision must follow the applicable client/SLB pressure-test procedure, not a synthetic demonstration threshold.

## Regression acceptance
1. Matplotlib locators produce the correct major/minor tick positions for all fixed windows, both second and minute X axes.
2. Report preview, PDF portrait, PDF landscape, and JPEG share the same reporting time scale.
3. 48-minute selection stays 48 minutes of source data when plotted on a 50-minute axis.
4. Zoom and manual scale never silently modify interval selection.
5. Isolated spikes, depressurization, and TIMEOUT gaps remain visible after visual reduction.
6. Test date/time formatting across midnight and different UTC offsets.
7. Verify 24-hour rendering responsiveness and memory usage in the packaged Windows app.

Run `pytest tests/test_engineering_charts.py` before release, then complete the Windows UI/PDF visual acceptance review. Automated tests do not replace the operator's validation of exported charts.
