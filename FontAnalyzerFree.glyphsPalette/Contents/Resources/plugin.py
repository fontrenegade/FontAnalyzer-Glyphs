# encoding: utf-8
"""
Font Analyzer – Free: palette for Glyphs 3 and Glyphs 4, the version without
an account. FontAnalyzerFree.glyphsPalette (Glyphs 3) and
FontAnalyzerFreeG4.glyphsPalette (Glyphs 4) share this file; only the class
name, User-Agent and log file differ (build_glyphs_plugin checks that).

Export the current font to a temporary folder, send it to fontanalyzer.app
with one of the four basic analysis templates, get a notification when the
analysis is ready and open the results in the browser. No sign-in, no
settings: the server is fixed.
"""
from __future__ import division, print_function, unicode_literals

import functools
import json
import os
import shutil
import tempfile
import threading
import time
import traceback
import uuid

import objc
from AppKit import NSApplication, NSColor, NSInformationalRequest, NSOperationQueue, NSWorkspace
from Foundation import NSURL, NSData, NSMutableURLRequest, NSURLSession
import GlyphsApp
from GlyphsApp import Glyphs
from GlyphsApp.plugins import PalettePlugin
from vanilla import Button, Group, PopUpButton, TextBox, Window

PLUGIN_VERSION = "0.1"
SERVER = "https://fontanalyzer.app"
PREFS = "app.fontanalyzer.glyphs.quick."
POLL_SECONDS = 4
POLL_GIVE_UP_SECONDS = 60 * 60
LOG_PATH = os.path.expanduser("~/Library/Logs/FontAnalyzer-Free-Glyphs.log")

# Export formats offered in the palette: (label, kind)
FORMATS = [
    ("Static OTF", "otf"),
    ("Static TTF", "ttf"),
    ("Variable TTF", "variable"),
]
FONT_EXTENSIONS = (".otf", ".ttf", ".woff", ".woff2")

OTF = getattr(GlyphsApp, "OTF", "OTF")
TTF = getattr(GlyphsApp, "TTF", "TTF")
VARIABLE = getattr(GlyphsApp, "VARIABLE", "variable")
PLAIN = getattr(GlyphsApp, "PLAIN", "plain")
INSTANCETYPESINGLE = getattr(GlyphsApp, "INSTANCETYPESINGLE", 0)
INSTANCETYPEVARIABLE = getattr(GlyphsApp, "INSTANCETYPEVARIABLE", 1)

# The same code runs in Glyphs 3 and Glyphs 4 (the two bundles differ only in
# their names). Glyphs 4 changes instance export:
# - generate(format=VARIABLE) raises; a Variable Font Setting exports with
#   format=TTF and Glyphs picks the variable outline format itself.
# - there are icon instances (INSTANCETYPEICON), which are not fonts: static
#   export takes only INSTANCETYPESINGLE.
# - generate() returns None on success (Glyphs 3: True), an error otherwise.
GLYPHS4 = float(getattr(Glyphs, "versionNumber", 3.0) or 3.0) >= 4.0
VARIABLE_EXPORT_FORMAT = TTF if GLYPHS4 else VARIABLE


class FAError(Exception):
    pass


# --- Helpers ---------------------------------------------------------------

def logError(context):
    """Print the current exception to the Macro Panel and append it to the log."""
    text = "[Font Analyzer – Free] %s\n%s" % (context, traceback.format_exc())
    print(text)
    try:
        with open(LOG_PATH, "a") as handle:
            handle.write(time.strftime("%Y-%m-%d %H:%M:%S ") + text + "\n")
    except Exception:
        pass


def notify(title, subtitle, message):
    """Shows a macOS notification from Glyphs (Notification Center banner).
    Uses Glyphs' own GSUserNotification (GlyphsKit, in Glyphs 3.5 and 4), which
    posts through the UserNotifications framework like Glyphs' own
    notifications, so it follows Glyphs' settings in System Settings >
    Notifications. Without it: Glyphs.showNotification (the deprecated
    NSUserNotification). When Glyphs isn't the active app, the Dock icon also
    bounces once. Clicking the banner brings Glyphs to the front; Glyphs owns
    the click handler, so the banner can't open the results itself (the
    palette's Open Results button is highlighted instead)."""
    try:
        try:
            notificationClass = objc.lookUpClass("GSUserNotification")
        except objc.nosuchclass_error:
            notificationClass = None
        if notificationClass is not None:
            notification = notificationClass.new()
            notification.setTitle_(title)
            if subtitle:
                notification.setSubtitle_(subtitle)
            notification.setInformativeText_(message)
            notification.deliver()
        else:
            Glyphs.showNotification(title + (": " + subtitle if subtitle else ""), message)
    except Exception:
        logError("notification")
    try:
        app = NSApplication.sharedApplication()
        if not app.isActive():
            app.requestUserAttention_(NSInformationalRequest)
    except Exception:
        logError("dock attention")


def onMain(function, *args):
    """Run function(*args) on the main thread. An exception escaping a block
    on the main queue aborts Glyphs, so it is caught and logged here."""
    name = getattr(function, "__name__", repr(function))

    def block():
        try:
            function(*args)
        except Exception:
            logError("main-thread callback %s failed" % name)

    NSOperationQueue.mainQueue().addOperationWithBlock_(block)


def guarded(function):
    """For UI callbacks: log exceptions instead of letting them reach AppKit."""
    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception:
            logError("%s failed" % function.__name__)
    return wrapper


def httpRequest(method, url, multipart=None, timeout=60):
    """Synchronous HTTP through NSURLSession (system trust store, proxies and
    cookie storage). Call from a background thread. Returns (status, json)."""
    request = NSMutableURLRequest.requestWithURL_(NSURL.URLWithString_(url))
    request.setHTTPMethod_(method)
    request.setTimeoutInterval_(timeout)
    request.setValue_forHTTPHeaderField_("FontAnalyzer-Glyphs-Free/" + PLUGIN_VERSION, "User-Agent")
    request.setValue_forHTTPHeaderField_("application/json", "Accept")
    if multipart is not None:
        body, contentType = encodeMultipart(*multipart)
        request.setValue_forHTTPHeaderField_(contentType, "Content-Type")
        request.setHTTPBody_(NSData.dataWithBytes_length_(body, len(body)))

    done = threading.Event()
    result = {}

    def completion(data, response, error):
        result["data"], result["response"], result["error"] = data, response, error
        done.set()

    NSURLSession.sharedSession().dataTaskWithRequest_completionHandler_(request, completion).resume()
    if not done.wait(timeout + 10):
        raise FAError("The server did not answer.")
    if result.get("error") is not None:
        raise FAError(result["error"].localizedDescription())
    status = result["response"].statusCode()
    raw = bytes(result["data"]) if result.get("data") is not None else b""
    try:
        payload = json.loads(raw.decode("utf-8")) if raw else {}
    except ValueError:
        payload = {}
    return status, payload


def encodeMultipart(fields, files):
    """fields: {name: value}; files: [(fieldName, path)]."""
    boundary = "----FontAnalyzer" + uuid.uuid4().hex
    chunks = []
    for name, value in fields.items():
        chunks.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, name, value)).encode("utf-8"))
    for name, path in files:
        filename = os.path.basename(path).replace('"', "")
        chunks.append((
            "--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
            "Content-Type: application/octet-stream\r\n\r\n" % (boundary, name, filename)
        ).encode("utf-8"))
        with open(path, "rb") as handle:
            chunks.append(handle.read())
        chunks.append(b"\r\n")
    chunks.append(("--%s--\r\n" % boundary).encode("utf-8"))
    return b"".join(chunks), "multipart/form-data; boundary=" + boundary


# --- The palette ----------------------------------------------------------

class FontAnalyzerFreePalette(PalettePlugin):
    dialog = objc.IBOutlet()

    @objc.python_method
    def settings(self):
        self.name = Glyphs.localize({"en": "Font Analyzer – Free"})
        self.templates = []
        self.loadingTemplates = False
        self.analysisRun = 0    # bumped to stop polling an older analysis
        self.resultsUrl = None
        self.busy = False

        width, height = 160, 126
        self.paletteView = Window((width, height))
        g = self.paletteView.group = Group((0, 0, width, height))
        g.template = PopUpButton((8, 2, -8, 20), ["Loading templates…"], sizeStyle="small", callback=self.templateChanged)
        g.format = PopUpButton((8, 26, -8, 20), [label for label, _ in FORMATS], sizeStyle="small", callback=self.formatChanged)
        g.send = Button((8, 52, -8, 20), "Send to Font Analyzer", sizeStyle="small", callback=self.sendClicked)
        g.status = TextBox((10, 77, -10, 26), "", sizeStyle="mini")
        g.status.getNSTextField().setTextColor_(NSColor.secondaryLabelColor())
        g.open = Button((8, 104, -8, 20), "Open Results", sizeStyle="small", callback=self.openClicked)
        g.open.show(False)

        formatIndex = int(Glyphs.defaults[PREFS + "formatIndex"] or 0)
        g.format.set(min(formatIndex, len(FORMATS) - 1))
        g.template.enable(False)

        self.dialog = g.getNSView()

    @objc.python_method
    def start(self):
        self.loadTemplates()

    # Glyphs palette boilerplate
    def __file__(self):
        return __file__

    def setSortID_(self, sortId):
        pass

    def sortID(self):
        return 0

    # --- UI state ---------------------------------------------------------

    @objc.python_method
    def setStatus(self, text):
        self.paletteView.group.status.set(text or "")

    @objc.python_method
    def refreshUI(self):
        g = self.paletteView.group
        g.template.enable(bool(self.templates) and not self.busy)
        g.format.enable(not self.busy)
        g.send.enable(not self.busy and not self.loadingTemplates)

    @objc.python_method
    def selectedTemplate(self):
        index = self.paletteView.group.template.get()
        if self.templates and 0 <= index < len(self.templates):
            return self.templates[index]
        return None

    @objc.python_method
    def showResultsButton(self, url, highlight):
        self.resultsUrl = url
        button = self.paletteView.group.open
        button.show(bool(url))
        nsButton = button.getNSButton()
        if hasattr(nsButton, "setBezelColor_"):
            nsButton.setBezelColor_(NSColor.controlAccentColor() if highlight else None)

    # --- Templates --------------------------------------------------------

    @objc.python_method
    def loadTemplates(self, thenExport=False):
        self.loadingTemplates = True
        self.refreshUI()

        def work():
            try:
                status, data = httpRequest("GET", SERVER + "/api/v1/plugin/public/templates/", timeout=20)
                if status != 200:
                    raise FAError("Font Analyzer is not reachable (%s)." % status)
                onMain(self.templatesLoaded, data.get("templates", []), thenExport)
            except Exception as e:
                logError("loading templates failed")
                onMain(self.templatesFailed, str(e))

        threading.Thread(target=work, daemon=True).start()

    @objc.python_method
    def templatesLoaded(self, templates, thenExport):
        self.loadingTemplates = False
        self.templates = templates
        g = self.paletteView.group
        g.template.setItems([t["name"] for t in templates] or ["No templates"])
        savedId = Glyphs.defaults[PREFS + "templateId"]
        for index, template in enumerate(templates):
            if str(template["id"]) == str(savedId):
                g.template.set(index)
                break
        if not thenExport:
            self.setStatus("")
        self.refreshUI()
        if thenExport and templates:
            self.startExport()

    @objc.python_method
    def templatesFailed(self, message):
        self.loadingTemplates = False
        self.paletteView.group.template.setItems(["Templates unavailable"])
        self.setStatus("Offline: %s" % message)
        self.refreshUI()

    # --- Callbacks ----------------------------------------------------------

    @objc.python_method
    @guarded
    def templateChanged(self, sender):
        template = self.selectedTemplate()
        if template:
            Glyphs.defaults[PREFS + "templateId"] = template["id"]

    @objc.python_method
    @guarded
    def formatChanged(self, sender):
        Glyphs.defaults[PREFS + "formatIndex"] = sender.get()

    @objc.python_method
    @guarded
    def sendClicked(self, sender):
        if not self.templates:
            # Offline at launch: try again, then export.
            self.setStatus("Connecting…")
            self.loadTemplates(thenExport=True)
            return
        self.startExport()

    @objc.python_method
    @guarded
    def openClicked(self, sender):
        if self.resultsUrl:
            NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(self.resultsUrl))
            self.showResultsButton(self.resultsUrl, highlight=False)

    # --- Export and analysis --------------------------------------------------

    @objc.python_method
    def startExport(self):
        font = Glyphs.font
        if font is None:
            self.setStatus("Open a font first.")
            return
        if self.selectedTemplate() is None:
            self.setStatus("No analysis template available.")
            return
        self.busy = True
        self.analysisRun += 1
        self.showResultsButton(None, False)
        self.setStatus("Exporting %s…" % font.familyName)
        self.refreshUI()
        # Give the palette a moment to redraw before the (blocking) export.
        self.performSelector_withObject_afterDelay_("runExport:", None, 0.05)

    def runExport_(self, sender):
        try:
            self.runExport()
        except Exception:
            logError("export failed")
            self.busy = False
            self.setStatus("Export failed, see the Macro Panel.")
            self.refreshUI()

    @objc.python_method
    def runExport(self):
        font = Glyphs.font
        template = self.selectedTemplate()
        kind = FORMATS[self.paletteView.group.format.get()][1]
        folder = tempfile.mkdtemp(prefix="FontAnalyzer-")
        try:
            files = self.exportFont(font, kind, folder)
        except Exception as e:
            if not isinstance(e, FAError):
                logError("export failed")
            shutil.rmtree(folder, ignore_errors=True)
            self.busy = False
            self.setStatus("Export failed: %s" % e)
            self.refreshUI()
            return
        self.setStatus("Uploading %d font%s…" % (len(files), "" if len(files) == 1 else "s"))
        self.upload(files, folder, template, font.familyName)

    @objc.python_method
    def exportFont(self, font, kind, folder):
        """Exports the font's active instances into folder (Glyphs API, main
        thread). Returns the exported file paths."""
        if kind == "variable":
            instances = [i for i in font.instances if i.exports and getattr(i, "type", 0) == INSTANCETYPEVARIABLE]
            if not instances:
                raise FAError("Add a Variable Font Setting in Font Info > Exports.")
            exportFormat = VARIABLE_EXPORT_FORMAT
        else:
            instances = [i for i in font.instances if i.exports and getattr(i, "type", 0) == INSTANCETYPESINGLE]
            if not instances:
                raise FAError("The font has no active instances.")
            exportFormat = OTF if kind == "otf" else TTF

        errors = []
        for instance in instances:
            result = instance.generate(
                format=exportFormat,
                fontPath=folder,
                autoHint=True,
                removeOverlap=True,
                useSubroutines=False,   # faster, and irrelevant for QA
                useProductionNames=True,
                containers=[PLAIN],
            )
            if result is not True and result:
                errors.append("%s: %s" % (instance.name, result))
        files = sorted(
            os.path.join(folder, name) for name in os.listdir(folder)
            if name.lower().endswith(FONT_EXTENSIONS)
        )
        if errors:
            print("Font Analyzer – Free export problems:\n" + "\n".join(errors))
        if not files:
            raise FAError(errors[0] if errors else "Glyphs exported no fonts.")
        return files

    @objc.python_method
    def upload(self, files, folder, template, familyName):
        run = self.analysisRun

        def work():
            try:
                status, data = httpRequest(
                    "POST", SERVER + "/api/v1/plugin/public/analyses/",
                    multipart=({"analysisTemplate": template["id"]}, [("filename", path) for path in files]),
                    timeout=300,
                )
                if status != 201:
                    raise FAError(data.get("error", "Upload failed (%s)." % status))
                analysis = data["analysis"]
                onMain(self.analysisQueued, run, SERVER + analysis.get("path", ""), analysis)
                self.pollAnalysis(run, analysis["hash"], familyName)
            except Exception as e:
                logError("upload failed")
                onMain(self.analysisFailed, run, str(e))
            finally:
                shutil.rmtree(folder, ignore_errors=True)

        threading.Thread(target=work, daemon=True).start()

    @objc.python_method
    def pollAnalysis(self, run, analysisHash, familyName):
        """Background thread: poll until the analysis is complete or failed."""
        deadline = time.time() + POLL_GIVE_UP_SECONDS
        url = SERVER + "/api/v1/plugin/public/analyses/%s/" % analysisHash
        while time.time() < deadline:
            time.sleep(POLL_SECONDS)
            if run != self.analysisRun:
                return
            try:
                status, data = httpRequest("GET", url, timeout=20)
            except FAError:
                continue  # transient network problem, keep waiting
            analysis = data.get("analysis")
            if status != 200 or not analysis:
                continue
            onMain(self.analysisProgress, run, SERVER + analysis.get("path", ""), analysis, familyName)
            if analysis["status"] in ("complete", "failed"):
                return
        onMain(self.analysisFailed, run, "Still not finished. Open the results link later.")

    @objc.python_method
    def analysisQueued(self, run, url, analysis):
        if run != self.analysisRun:
            return
        self.busy = False
        self.showResultsButton(url, highlight=False)
        self.setStatus(self.describe(analysis))
        self.refreshUI()

    @objc.python_method
    def analysisProgress(self, run, url, analysis, familyName):
        if run != self.analysisRun:
            return
        self.setStatus(self.describe(analysis))
        if analysis["status"] == "complete":
            self.showResultsButton(url, highlight=True)
            notify(
                "Font Analyzer – Free",
                "%s is ready" % (analysis.get("familyName") or familyName),
                "%d errors, %d warnings. Open Results in the palette."
                % (analysis.get("errorCount", 0), analysis.get("warningCount", 0)),
            )
        elif analysis["status"] == "failed":
            self.showResultsButton(url, highlight=False)
            notify("Font Analyzer – Free", "The analysis of %s failed" % familyName, "See the palette for details.")

    @objc.python_method
    def analysisFailed(self, run, message):
        if run != self.analysisRun:
            return
        self.busy = False
        self.setStatus(message)
        self.refreshUI()

    @objc.python_method
    def describe(self, analysis):
        status = analysis.get("status")
        if status in ("queuedNormal", "queuedHeavy"):
            return "Queued, position %s…" % analysis.get("queuePosition", "?")
        if status == "processing":
            return "Analysing…"
        if status == "complete":
            return "Ready: %d errors, %d warnings." % (analysis.get("errorCount", 0), analysis.get("warningCount", 0))
        if status == "failed":
            return "The analysis failed."
        return "Sent."
