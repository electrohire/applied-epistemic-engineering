# Shared input-boundary fuzzing

The ClusterFuzzLite/Atheris target and portable corpus tests share bundle_target.py.
Selectors0/1 cover claim JSON/Markdown;2 covers execution-record ingestion and3
covers JUnit parsing;4 covers receipt-backed test-discovery records. Other
selectors preserve even/odd claim routing. A fuzzed
record is never executed. Accepted execution records must roundtrip with the same
canonical digest, including nested collection and membership records; invalid
documents may fail with documented input errors.

The execution/JUnit seeds are synthetic fixtures, not real execution evidence,
trusted CI, or a passing assessment. junit-hidden-result retains the regression
for structured test results hidden inside metadata. Actual process capture is
covered separately by real subprocess integration tests on all supported targets.
