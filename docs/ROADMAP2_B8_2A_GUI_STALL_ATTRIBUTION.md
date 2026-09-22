# Roadmap 2 / B8.2A — GUI stall attribution (diagnostic build)

B8.1 external heartbeat observed multiple Windows GUI response stalls. It cannot
identify the blocking MainWindow action or Python stack. B8.2A adds a strictly
opt-in trace to a **separate diagnostic Portable**; it does not alter the certified
B7 Portable or automatically change any provider, voice, account or run settings.

Enable only through `RUN-B8.2-GUI-DIAGNOSTIC.cmd`. The launcher sets
`S_TALKING_B82_GUI_TRACE=1` and `S_TALKING_B82_TRACE_DIR=C:\zip-for-GPT`.
After running the same real project scenario, exit the diagnostic application.
Send the resulting `S-Talking-B82-GUI-Trace-*.jsonl` and launcher `last-run.txt`.

Records: a UTC timestamp, a known literal GUI action label, elapsed duration,
GUI heartbeat delays and sanitized **application module/function/line** identifiers.
No CSV text, project/account names, settings, credentials, filesystem paths,
function arguments, return values, stack locals or Python source lines are stored.
A watchdog may be unable to sample a stack while a native function holds the GIL;
the external B8.1 heartbeat remains complementary evidence.

**This is an attribution phase, not a structural remediation or manual acceptance.**
After the blocking stages are identified, B8.2B will move *only verified* heavy
work off the UI thread or phase the work without losing lifecycle guarantees.
The app is unchanged when the environment switch is not set.
