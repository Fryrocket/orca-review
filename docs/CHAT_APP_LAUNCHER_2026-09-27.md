# Chat app launcher — deployed

Fry requested both Studio navigation and installed KILN app launching.

Commands: `open canvas`, `open inventory`, `open code`, `open engineering`,
`open operations`, `open browser`, `open https://example.com`, `open Google Drive`,
`open Notion`, `open Linear`, `open Google Photos`, `open Firefox`, `open files`,
`open calculator`, `open text editor`.

The frontend matches explicit, anchored user commands before model inference.
Model replies, older memory and website text cannot request launches through this
path. Website opening does not grant ORCA access to account contents. Login is
performed by the user. Launch commands/URLs are not archived to server memory.

Native KILN app launching uses four fixed system `.desktop` files through Gio,
without shell execution or user-provided arguments. Acknowledgment reports a
launch request accepted, not proof that an external app is ready. A missing native
bridge gives a clear unsupported-client message, plus a clickable website link
when appropriate. iPhone and Mac native launching are not implemented here.

ORCA Browser opens as another KILN Studio application window. It has a separate
ephemeral WebKit context with no privileged content manager or Studio cookies.
Only HTTP/HTTPS navigation is allowed; device permissions and downloads are
disabled. Six-window limit; login sessions are not retained after their private
context closes. Existing green titlebar and sidebar are preserved.

## Live activation

Fry approved deployment and reopening on 2026-09-27. FORGE now uses
`/opt/orca/releases/chat-launcher-20260927-d4e6e554`; prior personality release
remains intact. Updated assets were SHA256-checked before activation; health
returned healthy with integrity valid. Native KILN launcher backup is
`/home/fryrocket/.local/lib/kiln-studio/kiln-studio.before-launcher-20260927.py`.

A real WebKit/GTK desktop smoke test executed `runPrompt` for Canvas, browser,
and Calculator. Canvas became active, a native browser window appeared, and
Calculator's launch was acknowledged (process 432071). JavaScript in the separate
browser confirmed it had no ORCA launch handler. Test windows and that Calculator
were closed afterward. Studio was reopened normally. No test commands were
archived to conversation memory. The first harness attempt failed due to an invalid
Python GType module name; fixing the test module name allowed the checks to pass.

Rollback: restore the prior FORGE release symlink and restart `orca.service`;
restore the native launcher backup and reopen KILN Studio after saving Canvas.

Verification: 651 Python tests passed, plus Node parser and runPrompt integration
checks. Candidate Python compiled on KILN; installed WebKit 2.50.4 supports the
required APIs. Real desktop smoke checks subsequently passed as recorded above.

QUENCH initially alleged a JSON validation bypass in a truncated response
`chatcmpl-Eiloe4xbKefDTLI2Yz3UYhpND2SAOjtf`. Reassessment with complete validation,
origin guard and static app IDs returned PASS
`chatcmpl-H2cxyNpB0GLjjQh9UvQOfFt5wyyKxxRt`. Review is advisory; its broad security
claims are not proof of all possible runtime behavior.

Deployment includes the three static assets (`app.js`, `index.html`, `launcher.js`)
in a new ORCA release and the native `desktop/KILNStudio/kiln-studio.py` installed
on KILN. The prior personality release and native launcher are retained for rollback.
The earlier candidate in `/tmp/orca-launcher-candidate-20260927.py` is not the installed entrypoint.
