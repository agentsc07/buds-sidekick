# Dashboard v2 acceptance (spec 12, dashboard rows)

## Not done: the unaided new-user run
"A new user reaches a working first ask within 5 minutes, unaided" needs a person who has not seen the product. No such person
was available in this session, so this is **not verified**. Run it with someone and record the time here.

## Done: scripted task coverage (automated, `tests/test_dashboard_tasks.py`)
Every API call in the JavaScript matches a real route; no `alert/confirm/prompt`; and these tasks work through the endpoints the UI uses:
enrol yourself, ask, listen, mark, replay, catch me up, record audio, go private, name a voice, change a person's remember setting,
change sensitivity, remap a gesture, read/export activity, forget a person (preview then delete), delete everything.

## Done: visual checks (headless Chrome screenshots in this folder)
Light and dark, 1280 / 768 / 500 px, every screen and the disconnected and Ollama-down banners. Contrast of text and mode colours is at least
4.5:1 in both themes (computed). The Chrome extension was not connected, so there are no GIFs and no click-through of dialogs;
dialogs use the native `<dialog>` element and were not exercised in a real browser session.

## Not checked
390 px phones (headless Chrome's minimum window is about 500 px), WebSocket drop and "Reconnecting" banner, keyboard shortcuts, focus order.
