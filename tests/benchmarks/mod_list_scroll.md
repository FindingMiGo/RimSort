# Mod list scrolling

Run the opt-in benchmark from the repository root:

```sh
QT_QPA_PLATFORM=offscreen RIMSORT_SCROLL_BENCHMARK=1 RIMSORT_SCROLL_ROWS=5000 \
  uv run pytest tests/views/test_mods_panel_scroll.py -k benchmark -s --no-qt-log
```

Set `RIMSORT_SCROLL_PROFILE=1` to write per-pass cProfile files to the system
temporary directory. Omit `QT_QPA_PLATFORM` to use the native window system.
The ordinary regression tests run without these environment variables.

The benchmark uses synthetic mod metadata, Japanese and Latin tags, the Modern
theme, a 640-by-600 viewport, and ten-row scroll steps. It measures the scroll
update plus one event-loop processing pass. Tag database reads are mocked and
counted; timings therefore exclude real database latency. These are comparative
UI-processing measurements, not displayed-frame timings or a real-mod benchmark.

## Results on macOS ARM64, Qt 6.11.2

Measured on 2026-09-21 against upstream `7b192b64`, with 5,000 rows, tags enabled,
and profiling disabled. Times are milliseconds per scroll step.

| Pass | Before median | After median | Before p95 | After p95 |
| --- | ---: | ---: | ---: | ---: |
| First traversal | 47.613 | 41.026 | 66.920 | 55.904 |
| Return traversal | 15.853 | 7.572 | 17.131 | 8.203 |
| Repeat traversal | 16.097 | 7.605 | 17.308 | 8.300 |

Tag getter calls during the first traversal dropped from 9,950 to zero. The
initial visible rows are created before the timed pass. Return and repeat passes
made zero tag getter calls in both versions. Both retained 5,000 row widgets.

An additional profiled return pass found 2,507,365 calls to the Python
`ModListWidget.eventFilter`. Qt installs the view as an event filter on index
widgets, so its Python override received movement events for all retained rows.
Moving context-menu handling to `contextMenuEvent` eliminated this Python filter
from the scrolling path. Menus still use the existing action implementation.

The other changes pass existing item tags into row widgets and avoid resetting
or recalculating unchanged tag text. On the 1,000-row benchmark, these changes
alone reduced first-pass median time from 32.127 to 28.990 ms, but did not
materially improve return scrolling. The context-menu change addresses that
separate cost without replacing the list's rendering and interaction model.

Initial row construction and retained-widget movement remain costs. These
results do not establish smoothness for every mod count, theme, or platform.

## Scroll code refactor check

On 2026-09-22, the tag cache and text layout were refactored without changing the
context-menu event routing. Tags are copied into an immutable tuple, display
updates report whether they changed anything, and text layout is called directly
instead of manufacturing resize events. The layout cache uses the fonts of the
labels that actually render the text.

A before/after check used the same command with `RIMSORT_SCROLL_ROWS=1000` and
profiling disabled. This compares the already optimized implementation to its
refactor, not to upstream. Each value is milliseconds per ten-row scroll step.

| Tags | Pass | Before median | After median | Before p95 | After p95 |
| --- | --- | ---: | ---: | ---: | ---: |
| Off | First | 16.396 | 16.396 | 19.272 | 19.833 |
| Off | Return | 2.545 | 2.478 | 3.114 | 2.927 |
| Off | Repeat | 2.783 | 2.556 | 3.240 | 3.183 |
| On | First | 27.155 | 28.931 | 31.344 | 36.184 |
| On | Return | 4.061 | 4.129 | 4.847 | 5.220 |
| On | Repeat | 4.318 | 4.390 | 5.066 | 5.067 |

All passes made zero tag-getter calls and retained 1,000 widgets. Warm tagged
medians differed by about 1.7%; the first tagged pass was slower in this single
comparison. These measurements do not establish a speedup or eliminate the
remaining cost of creating row widgets.

Regression tests also cover empty cached tags, changes to tags and effective
fonts, caller mutation of tag lists, and collection labels on lazily created rows.
