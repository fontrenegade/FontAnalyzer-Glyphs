# Font Analyzer – Free, for Glyphs 3 and Glyphs 4

A sidebar palette that sends the open font to [Font Analyzer](https://fontanalyzer.app)
and lets you know when the analysis is ready. No account, no settings.

| | Glyphs 3 | Glyphs 4 |
|---|---|---|
| Bundle | `FontAnalyzerFree.glyphsPalette` | `FontAnalyzerFreeG4.glyphsPalette` |
| Bundle ID | `app.fontanalyzer.glyphs.FontAnalyzerFreePalette` | `app.fontanalyzer.glyphs.FontAnalyzerFreeG4Palette` |
| Python | 3.11 (Plugin Manager module) | 3.14 or later (Plugin Manager module) |
| Log | `~/Library/Logs/FontAnalyzer-Free-Glyphs.log` | `~/Library/Logs/FontAnalyzer-Free-Glyphs4.log` |

Both appear in the sidebar as **Font Analyzer – Free**. They have different
bundle IDs and class names, so Glyphs 3 and Glyphs 4 can both have it installed.
Errors also go to the Macro Panel.

## What it does

1. Pick the analysis (Beginner, Designer, Engineer or Workshop) and the export
   format (static OTF, static TTF, or the font's Variable Font Settings).
2. **Send to Font Analyzer** exports the active instances into a temporary
   folder, uploads them to https://fontanalyzer.app and deletes the folder.
3. While the analysis runs, the palette shows the queue position.
4. When it's done, Glyphs shows a macOS notification (and the Dock icon bounces
   once if Glyphs is in the background), and **Open Results** is highlighted.
   Clicking it opens the results in the browser.

The server is fixed to https://fontanalyzer.app, and only the four basic
analyses are offered. Uploads belong to an anonymous user, like uploads from the
website without logging in. The results link is the private, unguessable
results address of the analysis.

## Install

- **Plugin Manager**: Window → Plugin Manager → Plugins, search for
  "Font Analyzer" (once it's listed in glyphs-packages, see below).
- **Website**: "DOWNLOAD GLYPHS PLUGIN" in the header of
  https://fontanalyzer.app/upload/. The zip has a `Glyphs 3` and a `Glyphs 4`
  folder. Double-click the bundle for your Glyphs version, or drag it onto that
  Glyphs app if double-click opens the other one. Restart Glyphs.
- **Development**: symlink the bundle into the Glyphs plugin folder and restart
  Glyphs:

      ln -s "$PWD/glyphs_plugin/FontAnalyzerFree.glyphsPalette" ~/Library/Application\ Support/Glyphs\ 3/Plugins/
      ln -s "$PWD/glyphs_plugin/FontAnalyzerFreeG4.glyphsPalette" ~/Library/Application\ Support/Glyphs\ 4/Plugins/

Requires the **Python** and **Vanilla** modules (Window → Plugin Manager →
Modules). Glyphs 4 needs its own copies; it doesn't use the Glyphs 3 ones. Then
show the palette with Window → Palette and expand "Font Analyzer – Free" in the
right sidebar.

### If the palette doesn't show up

- Check that Python and Vanilla are installed *in this Glyphs version* (above).
- Check that the bundle is in the right Plugins folder: the Glyphs 3 bundle in
  `~/Library/Application Support/Glyphs 3/Plugins/`, the Glyphs 4 bundle in
  `…/Glyphs 4/Plugins/`.
- Look for errors in Window → Macro Panel and in the log file (table above).

## One code base for both versions

Both bundles have the same `plugin.py`. Only three lines differ: the class name,
the User-Agent and the log file. **Change both files the same way.** The build
command (below) refuses to build when any other line differs.

The code checks `Glyphs.versionNumber >= 4.0` for the Glyphs 4 changes in
instance export (checked against the GlyphsSDK `Glyphs4` branch):

- `instance.generate(format=VARIABLE)` raises in Glyphs 4. A Variable Font
  Setting is exported with `format=TTF`, and Glyphs picks the variable format.
- Glyphs 4 has icon instances (`INSTANCETYPEICON`). Static export takes only
  `INSTANCETYPESINGLE`.
- `generate()` returns `None` on success in Glyphs 4 (`True` in Glyphs 3), and
  an error string otherwise.

Notifications go through Glyphs' own `GSUserNotification` (GlyphsKit, in
Glyphs 3.5 and 4), falling back to `Glyphs.showNotification`. Glyphs owns the
click handler, so a click on the banner brings Glyphs to the front but can't
open the results itself.

Network access uses NSURLSession, not Python's `ssl`. `Contents/MacOS/plugin`
is the standard GlyphsSDK loader (the same universal binary in the Glyphs3 and
Glyphs4 SDK branches). Glyphs refuses a bundle without it ("executable could
not be found"). `Info.plist` follows the SDK template (`PyMainFileNames`,
`NSPrincipalClass` = the class in `plugin.py`).

## Building the downloads

    python manage.py build_glyphs_plugin

writes to `fontanalyzer/static/downloads/`:

| File | Contents | Used by |
|---|---|---|
| `FontAnalyzerFree-Glyphs.zip` | `Font Analyzer – Free/Glyphs 3/…`, `…/Glyphs 4/…`, `Read Me.txt` | website download |
| `FontAnalyzerFree-Glyphs3.zip` | `FontAnalyzerFree.glyphsPalette/` at the top level | Plugin Manager (Glyphs 3) |
| `FontAnalyzerFree-Glyphs4.zip` | `FontAnalyzerFreeG4.glyphsPalette/` at the top level | Plugin Manager (Glyphs 4, `archiveURL`) |

Run it after every change to the plugin and deploy the zips with the change.
The zips keep Unix permissions, so the loader stays executable. nginx serves
them with an `ETag` and answers `If-None-Match` with `304`. The Plugin Manager
uses that to detect updates.

The website link goes through `/download/glyphs-plugin/`, which counts the
download (shown on `/stats/`) and redirects to the zip.

## Glyphs Plugin Manager (glyphs-packages)

The entries to add to
[`packages.plist`](https://github.com/schriftgestalt/glyphs-packages/blob/glyphs3/packages.plist)
are in [`packages.plist-entry.txt`](packages.plist-entry.txt):

- The Glyphs 3 entry (`maxVersion = "3799"`) is installed by cloning the git
  repository in `url`, using the bundle at `path`.
- The Glyphs 4 entry (`minVersion = "3877"`) downloads `archiveURL`, the zip
  with the bundle at the top level.
  This follows Florian Pircher's Glyphs 4 entries (commit `59eff4a` in
  glyphs-packages).

`url` must be a **public** git repository that contains the bundles. This repo
(FontAnalyzer) is private and holds server secrets, so it can't be used. The
bundles go into a separate public repo with only `FontAnalyzerFree.glyphsPalette`,
`FontAnalyzerFreeG4.glyphsPalette` and this README. Keep that repo in sync when
releasing, and bump `CFBundleVersion` / `CFBundleShortVersionString` in both
`Info.plist` files.

Server API used by the plugin (no auth, `fontanalyzer/plugin_api.py`):

| Method | Path | |
|---|---|---|
| GET | `/api/v1/plugin/public/templates/` | the four system templates |
| POST | `/api/v1/plugin/public/analyses/` | multipart: `filename` (repeatable), `analysisTemplate` → 201 with the analysis |
| GET | `/api/v1/plugin/public/analyses/<hash>/` | status, `queuePosition`, counts when complete, results URL |

The account version (Font Analyzer – Registered) is described in
[REGISTERED.md](REGISTERED.md).
