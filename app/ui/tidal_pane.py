from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

# We embed the TIDAL DL-NG GUI MainWindow as a child widget inside our app.
# This avoids creating a second QApplication and reuses the existing event loop.
try:
    from tidal_dl_ng.gui import MainWindow as TidalMainWindow
except Exception as e:
    TidalMainWindow = None  # type: ignore


class TidalPane(QWidget):
    """Embed the tidal-dl-ng GUI inside a pane of this app.

    Notes:
    - Requires tidal-dl-ng and its Qt deps to be installed in the venv.
    - We instantiate its MainWindow as a child widget and add to our layout.
    """

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._layout = layout
        self._ready = False
        self.tidal_window = None
        # Lightweight placeholder until user activates the page
        self._placeholder = QLabel("TIDAL Playlists — open this page to initialize…")
        self._layout.addWidget(self._placeholder)

    def activate(self):
        """Create and embed the tidal-dl-ng window on first activation."""
        if self._ready:
            return
        if TidalMainWindow is None:
            # Keep placeholder text if dependency is missing
            self._placeholder.setText("Tidal-dl-ng not Installed. Install dependencies.")
            return
        # Instantiate lazily to avoid network calls at app startup
        try:
            tw = TidalMainWindow(tidal=None)
            tw.setParent(self)
            # swap placeholder with actual widget
            self._layout.removeWidget(self._placeholder)
            self._placeholder.deleteLater()
            self._placeholder = None  # type: ignore
            self._layout.addWidget(tw)
            self.tidal_window = tw
            self._ready = True
        except Exception as e:
            # Fall back to placeholder message
            if self._placeholder is None:
                self._placeholder = QLabel(str(e))
                self._layout.addWidget(self._placeholder)
            else:
                self._placeholder.setText(f"Failed to initialize TIDAL pane: {e}")

    def showEvent(self, ev):
        # Initialize on first show of the page to avoid startup errors
        try:
            self.activate()
        except Exception:
            pass
        super().showEvent(ev)

    def shutdown(self):
        """Gracefully stop tidal-dl-ng background work to allow app exit."""
        if not hasattr(self, "tidal_window") or self.tidal_window is None:
            return
        try:
            # Pause queue and signal global abort so workers can exit cleanly
            try:
                self.tidal_window.pb_queue_download_pause()
            except Exception:
                pass
            try:
                from tidal_dl_ng.config import HandlingApp  # type: ignore
                HandlingApp().event_abort.set()
            except Exception:
                pass
            # Ask threadpool to finish and wait a short time
            try:
                self.tidal_window.threadpool.clear()
            except Exception:
                pass
            try:
                # Wait up to 2 seconds for cleanup
                self.tidal_window.threadpool.waitForDone(2000)
            except Exception:
                pass
        finally:
            try:
                # Trigger its own close handlers (invokes closeEvent)
                self.tidal_window.close()
            except Exception:
                pass
