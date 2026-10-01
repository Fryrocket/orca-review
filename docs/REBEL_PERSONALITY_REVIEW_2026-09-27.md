# Rebel personality 1.4.0 — not activated

Fry explicitly authorized internal prompt transmission to Qwen and QUENCH for
testing/review and deployment only if checks passed. The previous permission
checker rejection was not bypassed; testing resumed after that approval.

Candidate SHA256: 846b4b86f968bb9cde02d5d7eb7757c7b3b116b6edcd04e607a05421cec07bdb.

Initial Qwen sample invented generic thermal cutoffs and mocked missing
measurements. Added calibration against these errors and unsafe powered tests.
The revised sample still made unsupported diagnostic claims, suggested a touch
test on a potentially hot enclosure, and proposed maximum-load testing before
the unknown hardware/energy risks were established. It also exhausted its output
budget. This does not meet the requested extreme truthfulness standard.

QUENCH reviews returned BLOCK: chatcmpl-exJQTNFQBMbEd78M1ItB1iwTD41xTVNy
and chatcmpl-Yp4smoghCdqRQF1unvX2RraLNnTZepwC. Some review reasoning conflated
irreverent style with permission expansion despite explicit boundaries; nevertheless
the independent Qwen sample provided concrete reasons to withhold deployment.
Revised sample ID: chatcmpl-lwqTg8eKuVwfkUR2xvbkZ3AXJfdrtCrb.

No deployment script was executed and no live files or services changed.
Live release remains /opt/orca/releases/chat-launcher-20260927-d4e6e554 with
personality 1.3.0. Candidate source and tests remain local for further refinement.
Unit/regression tests validate prompt wiring, not factual accuracy of model output.
