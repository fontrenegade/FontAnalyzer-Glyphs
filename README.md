# FontAnalyzer palettes for Glyphs 3

Two separate plugins. They have their own bundle IDs, class names, sidebar
titles and log files, so both can be installed at the same time.

- **Font Analyzer – Free**: no account. Two bundles, `FontAnalyzerFree.glyphsPalette`
  for Glyphs 3 and `FontAnalyzerFreeG4.glyphsPalette` for Glyphs 4 (see below).
  This is the one offered on the website ("DOWNLOAD GLYPHS PLUGIN" in the upload page
  header). The server is fixed to https://fontanalyzer.app and there are no
  settings. Only the four basic templates (Beginner, Designer, Engineer,
  Workshop). Uploads belong to an anonymous user, like uploads from the website
  without logging in. Uses `/api/v1/plugin/public/…`. Keep it as it is.
  Logs: `~/Library/Logs/FontAnalyzer-Free-Glyphs.log` (Glyphs 3),
  `FontAnalyzer-Free-Glyphs4.log` (Glyphs 4).
- **Font Analyzer – Registered** (`FontAnalyzerRegistered.glyphsPalette`): for
  users with an account, signs in through the browser. New functionality
  (projects, notes, todos, …) goes here.
  Log: `~/Library/Logs/FontAnalyzer-Registered-Glyphs.log`.

Both also print errors to the Macro Panel.

## Glyphs 3 and Glyphs 4 (free version)

Both bundles share one `plugin.py`. Only the class name, the User-Agent and the
log file differ; each bundle also has its own bundle ID, so Glyphs 3 and 4 can
both have it installed. **Change both files the same way.**
`build_glyphs_plugin` refuses to build when any other line differs.

The code checks `Glyphs.versionNumber >= 4.0` for the Glyphs 4 changes in
instance export (checked against the GlyphsSDK `Glyphs4` branch):
- `instance.generate(format=VARIABLE)` raises in Glyphs 4. A Variable Font
  Setting is exported with `format=TTF`, and Glyphs picks the variable format.
- Glyphs 4 has icon instances (`INSTANCETYPEICON`). Static export takes only
  `INSTANCETYPESINGLE`.
- `generate()` returns `None` on success in Glyphs 4 (`True` in Glyphs 3), and
  an error string otherwise.

Glyphs 4 runs Python 3.14 or later (Glyphs 3: 3.11). The loader
`Contents/MacOS/plugin` is the same binary in both SDK branches. Network access
goes through NSURLSession, not Python's `ssl`.

## Website download

The upload page links to `static/downloads/FontAnalyzerFree-Glyphs.zip`, which
holds a `Glyphs 3` and a `Glyphs 4` folder and a Read Me. After changing the
free plugin, rebuild the zip and deploy it with the change:

    python manage.py build_glyphs_plugin

The zip keeps Unix permissions, so `Contents/MacOS/plugin` stays executable.

## Signed-in version

Round 1: sign in, send the current font to FontAnalyzer, get a notification
when the analysis is ready, open the results in the browser. Projects, notes,
todos and checklists come in later rounds.

## Install (development)

Symlink the bundle into the Glyphs plugin folder and restart Glyphs:

    ln -s "$PWD/glyphs_plugin/FontAnalyzerRegistered.glyphsPalette" \
      ~/Library/Application\ Support/Glyphs\ 3/Plugins/

Requires the Python and Vanilla modules from Window > Plugin Manager > Modules.
The palette appears in the right sidebar (Window > Palette, then expand
"Font Analyzer – Registered").

`Contents/MacOS/plugin` is the standard GlyphsSDK loader (universal binary,
identical in every Python plugin). Glyphs refuses the bundle without it
("executable could not be found").

## Using it

- **Sign In…** opens the browser at `/plugin/authorize/`. Log in on the website
  (the browser's password manager can fill it), check that the code matches the
  palette and click Connect. The plugin never sees the password.
- The API token is saved in the login Keychain (service
  `app.fontanalyzer.glyphs`, account = server address). **Sign Out** in the
  gear menu revokes it on the server and deletes it from the Keychain.
- Pick a template and a format (static OTF, static TTF, or the font's Variable
  Font Settings) and click **Send to FontAnalyzer**. Active instances are
  exported to a temporary folder, uploaded, and the folder is deleted.
- While the analysis runs, the palette shows the queue position. When it's done,
  Glyphs shows a notification and **Open Results** is highlighted.
- Analyses go to the project matching the font's family name; a new project is
  created when there isn't one (same as the web upload).

For local testing, set the gear menu's **Server…** to `http://127.0.0.1:8000`
(use the IP, not `localhost`: macOS only allows plain http to IP addresses).

## Server API

All under `/api/v1/plugin/`, JSON, `Authorization: Bearer <token>` except the
two sign-in calls. Implemented in `fontanalyzer/plugin_api.py`.

| Method | Path | |
|---|---|---|
| POST | `auth/start/` | `{clientName}` → `deviceCode`, `userCode`, `verificationPath`, `interval`, `expiresIn` |
| POST | `auth/poll/` | `{deviceCode}` → `pending` / `approved` (+ `token`, once) / `denied` / `expired` |
| POST | `auth/revoke/` | revokes the calling token |
| GET | `me/` | signed-in user |
| GET | `templates/` | templates the user may run (system ones first) |
| POST | `analyses/` | multipart: `filename` (repeatable), `analysisTemplate` → 201 with the analysis |
| GET | `analyses/<hash>/` | status, `queuePosition`, counts when complete, results `path` |
| GET | `public/templates/` | no auth: the four system templates |
| POST | `public/analyses/` | no auth: like `analyses/`, system templates only, anonymous user |
| GET | `public/analyses/<hash>/` | no auth: status by hash (the hash is already the public results key) |
