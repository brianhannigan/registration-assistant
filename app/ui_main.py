from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit,
    QPushButton, QTextEdit, QListWidget, QListWidgetItem, QGroupBox,
    QLabel, QSplitter, QTableWidget, QTableWidgetItem, QMessageBox,
    QAbstractItemView, QCheckBox, QScrollArea, QPlainTextEdit,
    QTabWidget, QFileDialog, QApplication
)

from .models import RegistrantProfile
from .selector_tools import domain_from_url, extract_selector_suggestions
from .mapping_store import MappingStore
from .playwright_worker import PlaywrightWorker
from .billing_profile import BillingProfile, load_billing_profile, save_billing_profile

APP_FIELDS = [
    ("registrant_name", "Registrant Name"),
    ("email", "Email"),
    ("phone", "Phone"),
    ("address1", "Address 1"),
    ("address2", "Address 2"),
    ("city", "City"),
    ("state", "State"),
    ("zip", "ZIP"),
]

# SAFE billing/contact-only fields (no PAN/CVV/expiry)
BILLING_FIELDS = [
    ("billing_name", "Billing Name"),
    ("email", "Billing Email"),
    ("phone", "Billing Phone"),
    ("address1", "Billing Address 1"),
    ("address2", "Billing Address 2"),
    ("city", "Billing City"),
    ("state", "Billing State"),
    ("zip", "Billing ZIP"),
    ("country", "Billing Country"),
    ("name_on_card", "Name on Card (non-sensitive)"),
    ("card_last4", "Card Last4 (display-only)"),
]

DEFAULT_SESSIONS = [
    ("week_1", "Week 1"),
    ("week_2", "Week 2"),
    ("week_3", "Week 3"),
    ("session_a", "Session A"),
    ("session_b", "Session B"),
]

def _mono_font():
    f = QFont("Consolas")
    if not f.exactMatch():
        f = QFont("Courier New")
    return f


class MainWindowUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Registration Assistant (Stops Before Payment)")
        self.resize(1320, 900)

        self.store = MappingStore()
        self.worker = PlaywrightWorker()
        self.worker.log.connect(self._log)
        self.worker.status.connect(self._status)
        self.worker.page_scanned.connect(self._on_scanned)
        self.worker.picked.connect(self._on_picked)

        self._picker_timer = QTimer(self)
        self._picker_timer.setInterval(200)
        self._picker_timer.timeout.connect(self.worker.poll_picker_once)

        self._picker_mode: Optional[str] = None  # "field" | "billing" | "session" | "continue"
        self._picker_target_key: Optional[str] = None
        self._picker_target_row: Optional[int] = None

        self.detected_fields: List[dict] = []
        self._session_bindings_cache: Dict[str, str] = {}

        # --- Shared controls ---
        self.url_input = QLineEdit()
        self.btn_goto = QPushButton("Go")
        self.btn_scan = QPushButton("Scan Page")
        self.btn_save = QPushButton("Save Mapping")
        self.btn_load = QPushButton("Load Mapping")
        self.btn_run = QPushButton("Run (Stop Before Payment)")

        self.status_label = QLabel("Status: idle")

        # Log
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)

        # Profile
        self.profile_inputs: Dict[str, QLineEdit] = {}
        self.gb_profile = QGroupBox("Registrant Profile")
        form = QFormLayout(self.gb_profile)
        for key, label in APP_FIELDS:
            le = QLineEdit()
            self.profile_inputs[key] = le
            form.addRow(label + ":", le)

        # Continue selector
        self.continue_selector_input = QLineEdit()
        self.continue_selector_input.setPlaceholderText("CSS selector for Continue/Next (optional)")
        self.continue_selector_input.setFont(_mono_font())
        self.btn_pick_continue = QPushButton("Pick Continue/Next Button")
        self.btn_clear_continue = QPushButton("Clear")
        self.btn_copy_continue = QPushButton("Copy")

        # Detected list + details
        self.list_detected = QListWidget()
        self.list_detected.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list_detected.setDragEnabled(True)
        self.list_detected.setDragDropMode(QAbstractItemView.DragOnly)

        self.detected_details = QPlainTextEdit()
        self.detected_details.setReadOnly(True)
        self.detected_details.setFont(_mono_font())
        self.btn_copy_detected_selector = QPushButton("Copy Selected Selector")

        # Mapping table (registrant)
        self.map_table = QTableWidget(0, 4)
        self.map_table.setHorizontalHeaderLabels(["App Field", "CSS Selector", "Pick From Page", "Clear"])
        self.map_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.map_table.setAcceptDrops(True)
        self.map_table.setDefaultDropAction(Qt.CopyAction)

        self.mapping_preview = QPlainTextEdit()
        self.mapping_preview.setReadOnly(True)
        self.mapping_preview.setFont(_mono_font())
        self.btn_copy_mapping_selector = QPushButton("Copy Selector From Selected Row")

        # Billing profile + mapping
        self.billing_inputs: Dict[str, QLineEdit] = {}
        self.gb_billing = QGroupBox("Billing Profile (Non-sensitive only)")
        bf = QFormLayout(self.gb_billing)
        for key, label in BILLING_FIELDS:
            le = QLineEdit()
            self.billing_inputs[key] = le
            bf.addRow(label + ":", le)

        self.btn_billing_load = QPushButton("Load Billing JSON")
        self.btn_billing_save = QPushButton("Save Billing JSON")

        # HTML helper
        self.html_input = QPlainTextEdit()
        self.html_input.setPlaceholderText("Paste HTML snippet here (optional). Then click Analyze to suggest selectors.")
        self.btn_html_analyze = QPushButton("Analyze HTML")
        self.suggest_list = QListWidget()
        self.btn_apply_suggest_to_selected_row = QPushButton("Apply Suggestion → Selected Mapping Row")
        self.suggest_details = QPlainTextEdit()
        self.suggest_details.setReadOnly(True)
        self.suggest_details.setFont(_mono_font())
        self.btn_copy_suggest_selector = QPushButton("Copy Suggestion Selector")

        # Sessions
        self.session_checks: Dict[str, QCheckBox] = {}
        self.session_selector_labels: Dict[str, QLabel] = {}
        self.sessions_box = QGroupBox("Sessions / Weeks (Pick each element on the page)")
        self.sessions_area = QScrollArea()
        self.sessions_area.setWidgetResizable(True)
        self.sessions_widget = QWidget()
        self.sessions_layout = QVBoxLayout(self.sessions_widget)
        self.sessions_layout.setAlignment(Qt.AlignTop)
        self.sessions_area.setWidget(self.sessions_widget)
        vb_sessions = QVBoxLayout(self.sessions_box)
        vb_sessions.addWidget(QLabel("Check sessions, then Pick each session element in the browser."))
        vb_sessions.addWidget(self.sessions_area)

        # Tabs
        self.tabs = QTabWidget()

        # Top bar
        self._build_layout()
        self._wire_events()

        self.worker.start()
        self._init_mapping_table()
        self._init_sessions(DEFAULT_SESSIONS)

    # ---------------- Layout ----------------
    def _build_layout(self):
        top = QHBoxLayout()
        top.addWidget(QLabel("URL:"))
        top.addWidget(self.url_input, 1)
        top.addWidget(self.btn_goto)
        top.addWidget(self.btn_scan)
        top.addWidget(self.btn_load)
        top.addWidget(self.btn_save)
        top.addWidget(self.btn_run)

        # TAB: Run
        tab_run = QWidget()
        run_v = QVBoxLayout(tab_run)
        run_v.addWidget(self.gb_profile)

        cont_row = QHBoxLayout()
        cont_row.addWidget(QLabel("Continue selector:"))
        cont_row.addWidget(self.continue_selector_input, 1)
        cont_row.addWidget(self.btn_pick_continue)
        cont_row.addWidget(self.btn_clear_continue)
        cont_row.addWidget(self.btn_copy_continue)
        run_v.addLayout(cont_row)

        run_v.addWidget(QLabel("Stops before payment. Complete payment manually."))
        run_v.addStretch(1)

        # TAB: Detected
        tab_detected = QWidget()
        det_v = QVBoxLayout(tab_detected)
        det_v.addWidget(QLabel("Detected elements (click one to see full selector/details):"))

        split_det = QSplitter(Qt.Vertical)
        split_det.addWidget(self.list_detected)

        det_detail_box = QWidget()
        det_detail_v = QVBoxLayout(det_detail_box)
        det_detail_v.addWidget(QLabel("Selected Element Details"))
        det_detail_v.addWidget(self.detected_details, 1)
        det_btns = QHBoxLayout()
        det_btns.addWidget(self.btn_copy_detected_selector)
        det_btns.addStretch(1)
        det_detail_v.addLayout(det_btns)

        split_det.addWidget(det_detail_box)
        split_det.setStretchFactor(0, 2)
        split_det.setStretchFactor(1, 2)
        det_v.addWidget(split_det, 1)

        # TAB: Field Mapping
        tab_map = QWidget()
        map_v = QVBoxLayout(tab_map)

        map_v.addWidget(QLabel("Drag a detected element onto a mapping row OR use Pick."))
        split_map = QSplitter(Qt.Vertical)
        split_map.addWidget(self.map_table)

        prev_box = QWidget()
        prev_v = QVBoxLayout(prev_box)
        prev_v.addWidget(QLabel("Selected Mapping Row Preview"))
        prev_v.addWidget(self.mapping_preview, 1)
        prev_btns = QHBoxLayout()
        prev_btns.addWidget(self.btn_copy_mapping_selector)
        prev_btns.addStretch(1)
        prev_v.addLayout(prev_btns)

        split_map.addWidget(prev_box)
        split_map.setStretchFactor(0, 2)
        split_map.setStretchFactor(1, 1)
        map_v.addWidget(split_map, 1)

        # TAB: Billing
        tab_billing = QWidget()
        bill_v = QVBoxLayout(tab_billing)

        warn = QLabel(
            "Billing Profile is NON-SENSITIVE only.\n"
            "It does NOT store card number (PAN), CVV/CVC, or expiry, and it does NOT submit payment."
        )
        warn.setWordWrap(True)
        bill_v.addWidget(warn)

        bill_v.addWidget(self.gb_billing)

        bbtn = QHBoxLayout()
        bbtn.addWidget(self.btn_billing_load)
        bbtn.addWidget(self.btn_billing_save)
        bbtn.addStretch(1)
        bill_v.addLayout(bbtn)

        # TAB: Sessions
        tab_sessions = QWidget()
        sess_v = QVBoxLayout(tab_sessions)
        sess_v.addWidget(self.sessions_box)

        # TAB: HTML Helper
        tab_html = QWidget()
        html_v = QVBoxLayout(tab_html)
        html_v.addWidget(QLabel("Paste HTML snippet and analyze to suggest selectors:"))
        html_v.addWidget(self.html_input, 1)

        row = QHBoxLayout()
        row.addWidget(self.btn_html_analyze)
        row.addWidget(self.btn_apply_suggest_to_selected_row)
        row.addStretch(1)
        html_v.addLayout(row)

        split_html = QSplitter(Qt.Vertical)
        split_html.addWidget(self.suggest_list)

        sdet_box = QWidget()
        sdet_v = QVBoxLayout(sdet_box)
        sdet_v.addWidget(QLabel("Selected Suggestion Details"))
        sdet_v.addWidget(self.suggest_details, 1)
        sbtns = QHBoxLayout()
        sbtns.addWidget(self.btn_copy_suggest_selector)
        sbtns.addStretch(1)
        sdet_v.addLayout(sbtns)

        split_html.addWidget(sdet_box)
        split_html.setStretchFactor(0, 2)
        split_html.setStretchFactor(1, 2)
        html_v.addWidget(split_html, 1)

        # TAB: Logs
        tab_logs = QWidget()
        logs_v = QVBoxLayout(tab_logs)
        logs_v.addWidget(self.log_box, 1)

        # Add tabs
        self.tabs.addTab(tab_run, "Run")
        self.tabs.addTab(tab_detected, "Detected")
        self.tabs.addTab(tab_map, "Field Mapping")
        self.tabs.addTab(tab_billing, "Billing")
        self.tabs.addTab(tab_sessions, "Sessions")
        self.tabs.addTab(tab_html, "HTML Helper")
        self.tabs.addTab(tab_logs, "Logs")

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(self.status_label)

    # ---------------- Wiring ----------------
    def _wire_events(self):
        self.btn_goto.clicked.connect(self._on_goto)
        self.btn_scan.clicked.connect(self.worker.scan_page)
        self.btn_save.clicked.connect(self._on_save)
        self.btn_load.clicked.connect(self._on_load)
        self.btn_run.clicked.connect(self._on_run)

        self.btn_pick_continue.clicked.connect(self._pick_continue)
        self.btn_clear_continue.clicked.connect(lambda: self.continue_selector_input.setText(""))
        self.btn_copy_continue.clicked.connect(lambda: self._copy_text(self.continue_selector_input.text().strip()))

        self.list_detected.currentItemChanged.connect(self._on_detected_selected)
        self.btn_copy_detected_selector.clicked.connect(self._copy_selected_detected_selector)

        self.map_table.dragEnterEvent = self._map_drag_enter
        self.map_table.dropEvent = lambda e: self._map_drop(e, self.map_table)
        self.map_table.itemSelectionChanged.connect(self._on_mapping_row_selected)
        self.btn_copy_mapping_selector.clicked.connect(self._copy_selector_from_selected_row)

        self.btn_billing_load.clicked.connect(self._on_billing_load)
        self.btn_billing_save.clicked.connect(self._on_billing_save)

        self.btn_html_analyze.clicked.connect(self._on_html_analyze)
        self.suggest_list.currentItemChanged.connect(self._on_suggest_selected)
        self.btn_copy_suggest_selector.clicked.connect(self._copy_selected_suggest_selector)
        self.btn_apply_suggest_to_selected_row.clicked.connect(self._apply_suggestion_to_selected_row)

    def _init_mapping_table(self):
        self.map_table.setRowCount(len(APP_FIELDS))
        for row, (key, label) in enumerate(APP_FIELDS):
            it0 = QTableWidgetItem(f"{label} ({key})")
            it0.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.map_table.setItem(row, 0, it0)

            it1 = QTableWidgetItem("")
            it1.setFont(_mono_font())
            self.map_table.setItem(row, 1, it1)

            btn_pick = QPushButton("Pick")
            btn_clear = QPushButton("Clear")
            btn_pick.clicked.connect(lambda _, k=key, r=row: self._start_picker_for_field(k, r))
            btn_clear.clicked.connect(lambda _, r=row: self.map_table.item(r, 1).setText(""))
            self.map_table.setCellWidget(row, 2, btn_pick)
            self.map_table.setCellWidget(row, 3, btn_clear)

        hdr = self.map_table.horizontalHeader()
        hdr.setSectionResizeMode(0, hdr.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(1, hdr.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, hdr.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, hdr.ResizeMode.ResizeToContents)

    def _init_sessions(self, sessions: List[Tuple[str, str]]):
        while self.sessions_layout.count():
            item = self.sessions_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        self.session_checks.clear()
        self.session_selector_labels.clear()

        for key, label in sessions:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)

            cb = QCheckBox(label)
            self.session_checks[key] = cb

            sel_lbl = QLabel("(not mapped)")
            sel_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
            sel_lbl.setWordWrap(True)
            sel_lbl.setFont(_mono_font())
            self.session_selector_labels[key] = sel_lbl

            btn_pick = QPushButton("Pick")
            btn_clear = QPushButton("Clear")
            btn_copy = QPushButton("Copy")

            btn_pick.clicked.connect(lambda _, k=key: self._start_picker_for_session(k))
            btn_clear.clicked.connect(lambda _, k=key: self._clear_session_mapping(k))
            btn_copy.clicked.connect(lambda _, k=key: self._copy_text(self._session_bindings_cache.get(k, "")))

            h.addWidget(cb, 2)
            h.addWidget(sel_lbl, 6)
            h.addWidget(btn_pick)
            h.addWidget(btn_clear)
            h.addWidget(btn_copy)

            self.sessions_layout.addWidget(row)

        self.sessions_layout.addStretch(1)

    def _on_detected_selected(self, cur: QListWidgetItem, _prev: QListWidgetItem):
        if not cur:
            self.detected_details.setPlainText("")
            return
        f = cur.data(Qt.UserRole) or {}
        lines = [
            f"tag: {f.get('tag','')}",
            f"type: {f.get('input_type','')}",
            f"label_hint: {f.get('label_hint','')}",
            f"name: {f.get('name','')}",
            f"id: {f.get('id','')}",
            f"placeholder: {f.get('placeholder','')}",
            f"aria_label: {f.get('aria_label','')}",
            f"role: {f.get('role','')}",
            f"confidence: {f.get('confidence','')}",
            "",
            "selector:",
            f.get("selector",""),
        ]
        self.detected_details.setPlainText("\n".join(lines))

    def _copy_selected_detected_selector(self):
        item = self.list_detected.currentItem()
        if not item:
            return
        f = item.data(Qt.UserRole) or {}
        self._copy_text(f.get("selector", ""))

    def _on_mapping_row_selected(self):
        row = self.map_table.currentRow()
        if row < 0:
            self.mapping_preview.setPlainText("")
            return
        app_field = self.map_table.item(row, 0).text()
        sel = self.map_table.item(row, 1).text()
        self.mapping_preview.setPlainText(f"{app_field}\n\nselector:\n{sel}")

    def _copy_selector_from_selected_row(self):
        row = self.map_table.currentRow()
        if row < 0:
            return
        self._copy_text(self.map_table.item(row, 1).text().strip())

    def _map_drag_enter(self, event):
        event.acceptProposedAction()

    def _map_drop(self, event, table: QTableWidget):
        pos = event.position().toPoint()
        row = table.rowAt(pos.y())
        if row < 0:
            event.ignore()
            return

        item = self.list_detected.currentItem()
        if not item:
            event.ignore()
            return
        f = item.data(Qt.UserRole) or {}
        sel = f.get("selector", "")
        if not sel:
            QMessageBox.warning(self, "No selector", "That element has no auto selector. Use Pick instead.")
            event.ignore()
            return
        table.item(row, 1).setText(sel)
        self._log(f"Mapped row {row} -> {sel}")
        event.acceptProposedAction()

    def _start_picker_for_field(self, app_field_key: str, row: int):
        self._picker_mode = "field"
        self._picker_target_key = app_field_key
        self._picker_target_row = row
        self.worker.start_picker()
        self._picker_timer.start()
        self._log(f"Picker started for field: {app_field_key}. Click element in browser.")

    def _start_picker_for_session(self, session_key: str):
        self._picker_mode = "session"
        self._picker_target_key = session_key
        self._picker_target_row = None
        self.worker.start_picker()
        self._picker_timer.start()
        self._log(f"Picker started for session: {session_key}. Click its checkbox/row element in browser.")

    def _pick_continue(self):
        self._picker_mode = "continue"
        self._picker_target_key = "__continue__"
        self._picker_target_row = None
        self.worker.start_picker()
        self._picker_timer.start()
        self._log("Picker started for Continue/Next button. Click the button in browser.")

    def _on_picked(self, selector: str, meta: dict):
        self.worker.stop_picker()
        self._picker_timer.stop()

        mode = self._picker_mode
        key = self._picker_target_key

        if mode == "continue":
            self.continue_selector_input.setText(selector)
            self._log(f"Picked Continue selector: {selector}")
        elif mode == "session" and key:
            self._session_bindings_cache[key] = selector
            self.session_selector_labels[key].setText(selector)
            self._log(f"Mapped session {key} -> {selector} | meta={meta}")
        elif mode == "field" and key is not None and self._picker_target_row is not None:
            self.map_table.item(self._picker_target_row, 1).setText(selector)
            self._log(f"Picked selector for {key}: {selector} | meta={meta}")
        else:
            self._log(f"Picked selector (unbound): {selector}")

        self._picker_mode = None
        self._picker_target_key = None
        self._picker_target_row = None

    def _clear_session_mapping(self, session_key: str):
        self._session_bindings_cache.pop(session_key, None)
        self.session_selector_labels[session_key].setText("(not mapped)")
        self._log(f"Cleared session mapping: {session_key}")

    def _on_billing_load(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load Billing Profile JSON", "", "JSON Files (*.json)")
        if not path:
            return
        try:
            prof = load_billing_profile(path)
            self._set_billing_form(prof)
            self._log(f"Loaded billing profile: {path}")
        except Exception as e:
            QMessageBox.critical(self, "Load failed", str(e))

    def _on_billing_save(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Billing Profile JSON", "billing_profile.json", "JSON Files (*.json)")
        if not path:
            return
        try:
            prof = self._get_billing_form()
            save_billing_profile(path, prof)
            self._log(f"Saved billing profile: {path}")
        except Exception as e:
            QMessageBox.critical(self, "Save failed", str(e))

    def _get_billing_form(self) -> BillingProfile:
        return BillingProfile(
            profile_name="Billing",
            billing_name=self.billing_inputs["billing_name"].text().strip(),
            email=self.billing_inputs["email"].text().strip(),
            phone=self.billing_inputs["phone"].text().strip(),
            address1=self.billing_inputs["address1"].text().strip(),
            address2=self.billing_inputs["address2"].text().strip(),
            city=self.billing_inputs["city"].text().strip(),
            state=self.billing_inputs["state"].text().strip(),
            zip=self.billing_inputs["zip"].text().strip(),
            country=self.billing_inputs["country"].text().strip() or "US",
            name_on_card=self.billing_inputs["name_on_card"].text().strip(),
            card_last4=self.billing_inputs["card_last4"].text().strip(),
        )

    def _set_billing_form(self, bp: BillingProfile):
        self.billing_inputs["billing_name"].setText(bp.billing_name)
        self.billing_inputs["email"].setText(bp.email)
        self.billing_inputs["phone"].setText(bp.phone)
        self.billing_inputs["address1"].setText(bp.address1)
        self.billing_inputs["address2"].setText(bp.address2)
        self.billing_inputs["city"].setText(bp.city)
        self.billing_inputs["state"].setText(bp.state)
        self.billing_inputs["zip"].setText(bp.zip)
        self.billing_inputs["country"].setText(bp.country)
        self.billing_inputs["name_on_card"].setText(bp.name_on_card)
        self.billing_inputs["card_last4"].setText(bp.card_last4)

    def _on_html_analyze(self):
        html = self.html_input.toPlainText()
        suggestions = extract_selector_suggestions(html)
        self.suggest_list.clear()
        for s in suggestions[:400]:
            txt = f"{s.get('tag')}  hint='{s.get('hint')}'  selector='{s.get('selector')}'"
            item = QListWidgetItem(txt)
            item.setData(Qt.UserRole, s)
            self.suggest_list.addItem(item)
        self._log(f"HTML analysis produced {len(suggestions)} selector suggestions.")

    def _on_suggest_selected(self, cur: QListWidgetItem, _prev: QListWidgetItem):
        if not cur:
            self.suggest_details.setPlainText("")
            return
        s = cur.data(Qt.UserRole) or {}
        self.suggest_details.setPlainText(
            f"tag: {s.get('tag','')}\n"
            f"type: {s.get('type','')}\n"
            f"hint: {s.get('hint','')}\n\n"
            f"selector:\n{s.get('selector','')}"
        )

    def _copy_selected_suggest_selector(self):
        item = self.suggest_list.currentItem()
        if not item:
            return
        s = item.data(Qt.UserRole) or {}
        self._copy_text(s.get("selector", ""))

    def _apply_suggestion_to_selected_row(self):
        item = self.suggest_list.currentItem()
        if not item:
            QMessageBox.information(self, "No suggestion selected", "Select a suggestion first.")
            return
        s = item.data(Qt.UserRole) or {}
        sel = s.get("selector", "")
        if not sel:
            return
        row = self.map_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "No mapping row selected", "Click a mapping row first, then apply.")
            return
        self.map_table.item(row, 1).setText(sel)
        self._log(f"Applied suggestion to row {row}: {sel}")

    def _on_save(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Missing URL", "Enter a URL so we can save per-domain.")
            return
        domain = domain_from_url(url)

        data = {
            "url": url,
            "field_bindings": self._collect_field_bindings(),
            "session_bindings": dict(self._session_bindings_cache),
            "continue_selector": self.continue_selector_input.text().strip() or None
        }
        self.store.save(domain, data)
        self._log(f"Saved mapping for domain: {domain}")

    def _on_load(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Missing URL", "Enter a URL so we can load per-domain.")
            return
        domain = domain_from_url(url)
        data = self.store.load(domain)
        if not data:
            QMessageBox.information(self, "No mapping", f"No saved mapping found for {domain}")
            return

        fb = data.get("field_bindings", {})
        for row, (key, _label) in enumerate(APP_FIELDS):
            sel = fb.get(key, "")
            self.map_table.item(row, 1).setText(sel)

        self._session_bindings_cache = data.get("session_bindings", {}) or {}
        for k, lbl in self.session_selector_labels.items():
            lbl.setText(self._session_bindings_cache.get(k, "(not mapped)"))

        self.continue_selector_input.setText(data.get("continue_selector") or "")
        self._log(f"Loaded mapping for domain: {domain}")

    def _on_run(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Missing URL", "Enter a URL first.")
            return

        prof = RegistrantProfile(
            registrant_name=self.profile_inputs["registrant_name"].text().strip(),
            email=self.profile_inputs["email"].text().strip(),
            phone=self.profile_inputs["phone"].text().strip(),
            address1=self.profile_inputs["address1"].text().strip(),
            address2=self.profile_inputs["address2"].text().strip(),
            city=self.profile_inputs["city"].text().strip(),
            state=self.profile_inputs["state"].text().strip(),
            zip=self.profile_inputs["zip"].text().strip(),
        )

        bindings = self._collect_field_bindings()
        field_values: Dict[str, Tuple[str, str]] = {}
        for key, _ in APP_FIELDS:
            sel = bindings.get(key, "")
            val = getattr(prof, key) or ""
            if sel and val:
                field_values[key] = (sel, val)

        to_click: List[str] = []
        for key, cb in self.session_checks.items():
            if cb.isChecked():
                sel = self._session_bindings_cache.get(key, "")
                if sel:
                    to_click.append(sel)
                else:
                    self._log(f"Session checked but not mapped: {key}")

        cont_sel = self.continue_selector_input.text().strip() or None

        self._log("=== RUN START (stops before payment) ===")
        self.worker.goto(url)

        if to_click:
            self.worker.click_selectors(to_click)

        self.worker.fill_and_click_safe(field_values, cont_sel)
        self._log("=== RUN END (manual from here) ===")

        self.tabs.setCurrentIndex(self.tabs.count() - 1)

    def _collect_field_bindings(self) -> Dict[str, str]:
        fb = {}
        for row, (key, _label) in enumerate(APP_FIELDS):
            sel = self.map_table.item(row, 1).text().strip()
            if sel:
                fb[key] = sel
        return fb

    def _on_scanned(self, fields: list):
        self.detected_fields = fields
        self.list_detected.clear()
        for f in fields:
            hint = f.get("label_hint", "")
            tag = f.get("tag", "")
            name = f.get("name", "")
            _id = f.get("id", "")
            conf = f.get("confidence", 0.0)
            s = f"[{conf:.2f}] {tag}  hint='{hint}'  name='{name}' id='{_id}'"
            item = QListWidgetItem(s)
            item.setData(Qt.UserRole, f)
            self.list_detected.addItem(item)

        self._log(f"Scanned {len(fields)} elements.")
        self.tabs.setCurrentIndex(1)

    def _on_goto(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Missing URL", "Enter a URL first.")
            return
        self.worker.goto(url)

    def _status(self, s: str):
        self.status_label.setText(f"Status: {s}")

    def _log(self, s: str):
        self.log_box.append(s)

    def _copy_text(self, s: str):
        if not s:
            return
        QApplication.clipboard().setText(s)
        self._log("Copied to clipboard.")
