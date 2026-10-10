"""App GTK4 pour piloter switch_capture_core, avec support multi-captures.

Architecture en 5 pages navigables (Gtk.Stack + Gtk.StackSwitcher) reflétant
le cycle de vie réel d'une campagne de capture, potentiellement sur
plusieurs switches/interfaces à la fois (comparaison client/routeur/
serveur, voir CAPTURE-METHODS.md) :

    1. « Configuration »  : liste des captures planifiées (une par point de
                             capture), formulaire d'ajout avec champs
                             conditionnels selon transfer_mode/output_mode.
    2. « Installation »    : prépare TOUTES les captures de la liste
                              (détection modèle, SCP/sshfs, NTP, feature) —
                              préalable obligatoire, aucune capture ne
                              démarre tant que toutes ne sont pas prêtes.
    3. « Démarrage »       : une fois l'installation complète, lance
                              effectivement toutes les captures.
    4. « Journal »         : logs en direct + statut/progression par
                              capture + arrêt global.
    5. « Résultats »       : fichiers .pcap produits, agrégés par capture.

Chaque zone scrollable désactive le mode « overlay » des scrollbars GTK4
(barres flottantes qui se cachent) au profit de scrollbars classiques
toujours visibles quand le contenu déborde.

Prérequis système (non installables via pip) :
    - python3-gi, gir1.2-gtk-4.0 (PyGObject + GTK4)
    - sshfs (mode legacy), wireshark, iproute2 (mode tap) — voir CLAUDE.md

Lancement :
    python3 switch_capture_gtk.py
"""

from __future__ import annotations

import os

# Doit rester avant tout import de gi/Gtk/Gio : évite que le sélecteur de fichiers
# GTK ne sollicite les moniteurs de volumes distants du paquet gvfs (ex. démons
# D-Bus org.gtk.vfs.GoaVolumeMonitor / org.gtk.vfs.UDisks2VolumeMonitor) pour
# peupler sa barre latérale. Sur un poste où ces démons sont absents ou mal
# enregistrés (signalé par l'utilisateur en session RDP/xrdp — voir features.md,
# bugs GVFS/GOA), cette tentative d'activation peut produire un « Erreur creating
# proxy … GoaVolumeMonitor », l'avertissement « Gtk-CRITICAL **: thaw_updates:
# assertion 'GTK_IS_FILE_SYSTEM_MODEL (model)' failed », voire une « Erreur de
# segmentation (core dumped) ». Reproduit dans cette session (avertissement
# GVFS-RemoteVolumeMonitor pour org.gtk.vfs.UDisks2VolumeMonitor, sous Xvfb avec
# une session D-Bus réelle mais sans udisks2/GOA) et confirmé disparu une fois ces
# deux variables positionnées.
#
# switch-capture n'a jamais besoin de choisir un emplacement distant
# (sftp://, google-drive://…) dans ses sélecteurs de fichiers/dossiers (dossier de
# la feature .bin, dossier d'archivage, fichier KeePass) : n'utiliser que
# l'implémentation VFS/moniteur de volumes locale (mécanismes GIO documentés,
# https://docs.gtk.org/gio/overview.html) supprime cette dépendance à gvfs pour
# tout le processus, sans changer le comportement pour la seule chose que cet
# outil demande à ces sélecteurs : un chemin local. `setdefault` : ne jamais
# écraser un réglage explicite déjà présent dans l'environnement de qui lance
# l'outil.
os.environ.setdefault("GIO_USE_VFS", "local")
os.environ.setdefault("GIO_USE_VOLUME_MONITOR", "unix")

import gettext
import queue
import signal
import sys
import threading
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango
from loguru import logger

# i18n (features.md, point 13) : même domaine/dossier que la CLI (voir
# switch_capture_cli.py) — un seul `switch-capture.pot`/`.po` partagé
# entre CLI et GUI, puisque les deux fichiers vivent dans `src/`. Seuls
# les libellés statiques de l'interface (label/title/placeholder_text/
# secondary_text/text de dialogues, add_button) sont passés en `_()` ;
# les messages dynamiques du Journal (`_set_journal_status`, souvent des
# f-strings avec IP/nom de capture/etc.) et les corps de boîtes de
# dialogue interpolés restent en français pour l'instant — même choix de
# périmètre que pour `logger.*` côté CLI, à étendre dans une session
# ultérieure si besoin.
_LOCALE_DIR_DEV = Path(__file__).resolve().parent / "locale"
_LOCALE_DIR_INSTALLED = Path("/usr/share/locale")
_LOCALE_DOMAIN = "switch-capture"
_locale_dir = _LOCALE_DIR_DEV if _LOCALE_DIR_DEV.is_dir() else _LOCALE_DIR_INSTALLED
_translation = gettext.translation(_LOCALE_DOMAIN, localedir=str(_locale_dir), fallback=True)
_ = _translation.gettext

from switch_capture_core import (
    CAPTURE_FILTER_PRESETS,
    KEEPASS_AVAILABLE,
    KEYRING_AVAILABLE,
    MODEL_PROFILES,
    CaptureRotationThread,
    Config,
    InspectConfig,
    MirrorConfig,
    MirrorThread,
    SetupAndCaptureThread,
    SharedState,
    UninstallThread,
    compute_average_throughput,
    confirm_ip_matches,
    delete_ssh_password_from_keepass,
    delete_ssh_password_from_keyring,
    format_inspect_report,
    format_scp_progress,
    format_transfer_rate,
    inspect_switch,
    list_capture_templates,
    load_capture_template,
    load_gui_preferences,
    load_ssh_password_from_keepass,
    load_ssh_password_from_keyring,
    save_capture_template,
    save_gui_preferences,
    save_ssh_password_to_keepass,
    save_ssh_password_to_keyring,
)

LOG_QUEUE: queue.Queue[str] = queue.Queue()

# Dossier par défaut des modèles de capture réutilisables (voir
# _on_save_template/_on_load_template). Toujours relatif au dossier de
# lancement, comme spool_dir/mount_point.
DEFAULT_MODELS_DIR = "./models"

# Fichier de préférences GUI (page Préférences, menu hamburger — voir
# CaptureWindow._load_preferences/_open_preferences_window). Même
# convention "relatif au dossier de lancement" que DEFAULT_MODELS_DIR/
# spool_dir/mount_point. Nom volontairement identique à celui documenté
# pour `switch-capture capture --config config.yaml` (voir
# docs/config.yaml.example) : les deux peuvent viser le même fichier sans
# conflit, save_gui_preferences() ne touchant jamais qu'à un sous-ensemble
# de clés dédié (PREFERENCES_FIELDS) et préservant tout le reste.
DEFAULT_PREFS_CONFIG_PATH = "./config.yaml"

# Valeurs par défaut des préférences GUI tant qu'aucun config.yaml n'a
# encore été enregistré depuis la page Préférences — reflètent les
# défauts du formulaire principal d'avant le retrait de ces 3 champs (voir
# features.md, point 1) plus keepass_path vide (comportement identique à
# avant : trousseau système utilisé en priorité, KeePass en repli optionnel).
DEFAULT_PREFERENCES: dict = {
    "slot": 1,
    "model": None,
    "feature_bin_path": "",
    "keepass_path": "",
}

# Identifiant d'application GTK4 (reverse-DNS) ET nom d'icône associé —
# volontairement la même valeur (convention freedesktop/GNOME standard),
# repris dans org.transcende.switch_capture.desktop (clés Icon= et
# StartupWMClass=) et dans le nom du fichier SVG livré sous
# src/icons/hicolor/scalable/apps/.
APP_ID = "org.transcende.switch_capture"

# Racine du dossier d'icônes du dépôt (contient hicolor/, comme
# /usr/share/icons/ côté système — PAS le dossier hicolor/ lui-même, voir
# _register_app_icon). Ajoutée comme chemin de recherche du thème d'icônes
# au démarrage pour que l'icône se résolve même en lancement non installé
# (dev : exécution directe depuis src/, sans être passé par install.sh/
# .deb/.rpm). Une fois installée, la même arborescence hicolor/ est
# fusionnée dans /usr/share/icons/hicolor (déjà couvert par le thème
# système par défaut) — ce chemin supplémentaire ne fait alors que
# doublonner, sans risque.
_ICON_SEARCH_ROOT = Path(__file__).resolve().parent / "icons"


def _register_app_icon() -> None:
    """Rend l'icône de l'app trouvable et la fixe comme icône de fenêtre par défaut.

    Sans effet si l'affichage GDK par défaut n'est pas disponible (l'appelant
    gère déjà ce cas juste après, voir CaptureApp.do_activate) : dans ce cas
    on se contente de l'appel à set_default_icon_name, sans effet visible
    tant qu'aucune fenêtre ne s'ouvre, mais inoffensif.
    """
    display = Gdk.Display.get_default()
    if display is not None and _ICON_SEARCH_ROOT.is_dir():
        Gtk.IconTheme.get_for_display(display).add_search_path(str(_ICON_SEARCH_ROOT))
    Gtk.Window.set_default_icon_name(APP_ID)


def _queue_sink(message) -> None:
    """Sink loguru qui pousse chaque ligne formatée dans LOG_QUEUE.

    Args:
        message: enregistrement loguru (déjà formaté en texte par le sink).
    """
    LOG_QUEUE.put(str(message))


logger.remove()
logger.add(_queue_sink, level="DEBUG", format="{time:HH:mm:ss} | {level: <8} | {message}")
logger.add("switch_capture.log", level="DEBUG", rotation="5 MB", retention="10 days", encoding="utf-8")


def format_size(num_bytes: int) -> str:
    """Formate une taille en octets en unité lisible (o/Ko/Mo/Go/To).

    Args:
        num_bytes: taille en octets.

    Returns:
        La taille formatée, ex: "3.4 Mo".
    """
    size = float(num_bytes)
    for unit in ("o", "Ko", "Mo", "Go"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "o" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} To"


class CaptureSession:
    """Une capture planifiée/en cours : sa config, son état, ses threads.

    Le cycle de vie d'une session traverse 3 statuts d'installation
    (`install_status`) : "pending" (pas encore préparée) -> "running"
    (préparation en cours) -> "ok"/"failed". Le démarrage effectif de la
    capture (`capture_running`) ne peut se faire qu'après "ok".
    """

    _next_id = 1

    def __init__(self, cfg: Config) -> None:
        """Initialise une session à partir d'une configuration validée.

        Args:
            cfg: configuration de capture pour ce point (switch/interface).
        """
        self.id = CaptureSession._next_id
        CaptureSession._next_id += 1
        self.cfg = cfg
        self.state = SharedState()
        self.setup = SetupAndCaptureThread(cfg, self.state)
        self.rotation: CaptureRotationThread | None = None
        self.install_status = "pending"  # pending | running | ok | failed
        self.install_error = ""
        self.capture_running = False

    @property
    def label(self) -> str:
        """Étiquette lisible de la session pour les listes de l'UI."""
        base = self.cfg.capture_label or self.cfg.switch_ip
        return f"#{self.id} {base} — {self.cfg.capture_interface} ({self.cfg.output_mode})"


class CaptureWindow(Gtk.ApplicationWindow):
    """Fenêtre principale : 5 pages reflétant le cycle de vie multi-captures."""

    def __init__(self, app: Gtk.Application) -> None:
        super().__init__(application=app, title=_("switch-capture — HPE Comware"))
        self.set_default_size(960, 780)

        self._sessions: list[CaptureSession] = []
        self._entries: dict[str, Gtk.Widget] = {}
        self._rows: dict[str, Gtk.Widget] = {}
        self._uninstall_threads: list[UninstallThread] = []
        self._mirror_threads: list[MirrorThread] = []
        self._prefs_window: Gtk.Window | None = None
        self._prefs_entries: dict[str, Gtk.Widget] = {}

        # Préférences GUI (slot/modèle/.bin forcé/keepass_path, page
        # Préférences — features.md, point 1) : chargées depuis
        # config.yaml AVANT la construction des pages, puisque
        # _build_config/_maybe_autofill_password/etc. en dépendent dès la
        # première capture ajoutée. Voir _load_preferences pour la
        # tolérance à un fichier absent/invalide.
        self._prefs: dict = dict(DEFAULT_PREFERENCES)
        self._prefs.update(self._load_preferences())

        header = Gtk.HeaderBar()
        self.set_titlebar(header)

        # Menu hamburger (features.md, point 1 « Menu et préférences ») :
        # en haut à gauche, devant le sélecteur de pages — deux entrées,
        # Préférences et Quitter. Actions posées sur la fenêtre (win.*)
        # plutôt que sur CaptureApp (app.*) : leur comportement (ouvrir la
        # page Préférences, fermer proprement via _on_close_request)
        # dépend de l'état de CETTE fenêtre, pas de l'application.
        menu_button = Gtk.MenuButton()
        menu_button.set_icon_name("open-menu-symbolic")
        menu_button.set_tooltip_text("Menu")
        menu_model = Gio.Menu()
        menu_model.append("Préférences", "win.preferences")
        menu_model.append("Quitter", "win.quit-app")
        menu_button.set_menu_model(menu_model)
        header.pack_start(menu_button)

        action_preferences = Gio.SimpleAction.new("preferences", None)
        action_preferences.connect("activate", self._on_open_preferences)
        self.add_action(action_preferences)

        action_quit = Gio.SimpleAction.new("quit-app", None)
        action_quit.connect("activate", lambda _a, _p: self.close())
        self.add_action(action_quit)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(root)

        self._stack = Gtk.Stack()
        self._stack.set_vexpand(True)
        self._stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)

        switcher = Gtk.StackSwitcher()
        switcher.set_stack(self._stack)
        switcher.set_halign(Gtk.Align.CENTER)
        header.set_title_widget(switcher)

        self._stack.add_titled(self._build_config_page(), "config", "Configuration")
        self._stack.add_titled(self._build_install_page(), "install", "Installation")
        self._stack.add_titled(self._build_start_page(), "start", "Démarrage")
        self._stack.add_titled(self._build_journal_page(), "journal", "Journal")
        self._stack.add_titled(self._build_results_page(), "results", "Résultats")
        root.append(self._stack)

        GLib.timeout_add(200, self._drain_log_queue)
        GLib.timeout_add(1000, self._refresh_journal)
        self.connect("close-request", self._on_close_request)

        self._refresh_sessions_list()
        self._refresh_install_list()
        self._refresh_start_list()

    # ------------------------------------------------------------------ #
    # Préférences (menu hamburger — features.md, point 1)
    # ------------------------------------------------------------------ #
    def _load_preferences(self) -> dict:
        """Charge les préférences GUI depuis DEFAULT_PREFS_CONFIG_PATH.

        Ne lève jamais : un config.yaml absent (rien encore enregistré
        depuis la page Préférences) ou invalide (ex. touché à la main,
        YAML mal formé) ne doit pas empêcher le lancement de
        l'application — un avertissement est journalisé et les valeurs
        par défaut (DEFAULT_PREFERENCES) restent en place dans ce cas.
        """
        try:
            return load_gui_preferences(DEFAULT_PREFS_CONFIG_PATH)
        except Exception as exc:  # YAML mal formé, permissions, etc.  # noqa: BLE001
            logger.warning(
                "préférences GUI : lecture de {} impossible, valeurs par défaut conservées | {}",
                DEFAULT_PREFS_CONFIG_PATH,
                exc,
            )
            return {}

    def _on_open_preferences(self, _action: Gio.SimpleAction, _param) -> None:
        self._open_preferences_window()

    def _save_preferences(self, *, slot: int, model: str | None, feature_bin_path: str, keepass_path: str) -> None:
        """Enregistre des préférences déjà lues (valeurs Python simples) et

        met à jour `self._prefs` en conséquence. Séparé du bouton
        « Enregistrer » (fermeture locale à `_open_preferences_window`,
        voir `on_save`) pour rester testable directement, sans avoir à
        parcourir l'arbre de widgets de la fenêtre Préférences.

        Raises:
            Exception: toute erreur d'écriture (permissions, etc.) —
                laissée à l'appelant (`on_save`, qui l'affiche via
                `_show_dialog` plutôt que de la laisser remonter jusqu'à
                GTK4).
        """
        to_save = {
            "slot": slot,
            "model": model,
            "feature_bin_path": feature_bin_path or None,
            "keepass_path": keepass_path or None,
        }
        save_gui_preferences(DEFAULT_PREFS_CONFIG_PATH, to_save)
        self._prefs["slot"] = slot
        self._prefs["model"] = model
        self._prefs["feature_bin_path"] = feature_bin_path
        self._prefs["keepass_path"] = keepass_path

    def _open_preferences_window(self) -> None:
        """Ouvre la fenêtre Préférences (ou refocalise celle déjà ouverte).

        Slot IRF/châssis, Modèle et .bin forcé — retirés du formulaire
        principal, voir features.md point 1 — plus keepass_path (voir
        `_row_remember_password`). Widgets exposés via
        `self._prefs_entries` (même rôle que `self._entries` pour le
        formulaire principal, dict séparé et reconstruit à chaque
        (ré)ouverture) plutôt que capturés uniquement par fermeture,
        pour rester testables sans parcourir l'arbre de widgets.
        """
        if self._prefs_window is not None:
            self._prefs_window.present()
            return

        win = Gtk.Window(transient_for=self, modal=True, title=_("Préférences"))
        win.set_default_size(560, 340)
        win.set_titlebar(Gtk.HeaderBar())

        outer = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=10,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )
        win.set_child(outer)

        outer.append(self._section("Feature packet-capture"))

        slot_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        slot_box.append(Gtk.Label(label=_("Slot IRF/châssis"), xalign=0, width_chars=26))
        slot_adjustment = Gtk.Adjustment(value=self._prefs["slot"], lower=1, upper=16, step_increment=1)
        slot_spin = Gtk.SpinButton(adjustment=slot_adjustment, numeric=True)
        slot_box.append(slot_spin)
        outer.append(slot_box)

        model_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        model_box.append(Gtk.Label(label=_("Modèle"), xalign=0, width_chars=26))
        model_options = ["Auto (détection via 'display version')"] + sorted(MODEL_PROFILES)
        model_dropdown = Gtk.DropDown.new_from_strings(model_options)
        current_model = self._prefs.get("model")
        model_dropdown.set_selected(model_options.index(current_model) if current_model in model_options else 0)
        model_box.append(model_dropdown)
        outer.append(model_box)

        bin_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bin_box.append(Gtk.Label(label=_("Forcer un .bin précis (optionnel)"), xalign=0, width_chars=26))
        bin_entry = Gtk.Entry(text=self._prefs.get("feature_bin_path") or "", hexpand=True)
        bin_box.append(bin_entry)
        bin_browse = Gtk.Button(label="...")
        bin_browse.connect("clicked", self._on_browse, bin_entry, False)
        bin_box.append(bin_browse)
        outer.append(bin_box)

        outer.append(Gtk.Separator())
        outer.append(self._section("Mot de passe SSH"))

        keepass_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        keepass_box.append(Gtk.Label(label=_("Fichier KeePass (.kdbx, repli)"), xalign=0, width_chars=26))
        keepass_entry = Gtk.Entry(text=self._prefs.get("keepass_path") or "", hexpand=True)
        keepass_box.append(keepass_entry)
        keepass_browse = Gtk.Button(label="...")
        keepass_browse.connect("clicked", self._on_browse, keepass_entry, False)
        keepass_box.append(keepass_browse)
        outer.append(keepass_box)

        # Widgets exposés (comme self._entries pour le formulaire
        # principal) pour rester testables sans parcourir l'arbre de la
        # fenêtre — réinitialisé à chaque (ré)ouverture, jamais fusionné
        # avec self._entries (formulaire de capture, sémantique différente).
        self._prefs_entries: dict[str, Gtk.Widget] = {
            "slot": slot_spin,
            "model": model_dropdown,
            "feature_bin_path": bin_entry,
            "keepass_path": keepass_entry,
        }

        keepass_hint = Gtk.Label(
            label=(
                "utilisé uniquement si le trousseau système est indisponible ; mot de passe "
                "maître via la variable d'environnement SWITCH_CAPTURE_KEEPASS_PASSWORD "
                "(jamais dans ce formulaire)"
            ),
            xalign=0,
            wrap=True,
        )
        keepass_hint.add_css_class("dim-label")
        outer.append(keepass_hint)

        if KEYRING_AVAILABLE:
            keepass_entry.set_sensitive(False)
            keepass_browse.set_sensitive(False)
            keepass_entry.set_tooltip_text("trousseau système disponible et utilisé en priorité")
        elif not KEEPASS_AVAILABLE:
            keepass_entry.set_sensitive(False)
            keepass_browse.set_sensitive(False)
            keepass_entry.set_tooltip_text("module 'pykeepass' non installé — repli KeePass indisponible")

        status_label = Gtk.Label(label="", xalign=0)
        status_label.add_css_class("dim-label")
        outer.append(status_label)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, halign=Gtk.Align.END)
        btn_save = Gtk.Button(label=_("Enregistrer"))
        btn_save.add_css_class("suggested-action")
        btn_box.append(btn_save)
        outer.append(btn_box)

        def on_save(_button: Gtk.Button) -> None:
            model_idx = model_dropdown.get_selected()
            model_value = None if model_idx == 0 else model_options[model_idx]
            try:
                self._save_preferences(
                    slot=int(slot_spin.get_value()),
                    model=model_value,
                    feature_bin_path=bin_entry.get_text().strip(),
                    keepass_path=keepass_entry.get_text().strip(),
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("préférences GUI | échec d'enregistrement")
                self._show_dialog(_("Échec de l'enregistrement"), str(exc))
                return
            status_label.set_text(f"Enregistré dans {DEFAULT_PREFS_CONFIG_PATH}.")

        btn_save.connect("clicked", on_save)

        def on_close(_win: Gtk.Window) -> bool:
            self._prefs_window = None
            self._prefs_entries = {}
            return False

        win.connect("close-request", on_close)
        self._prefs_window = win
        win.present()

    # ------------------------------------------------------------------ #
    # Helpers de construction de formulaire (génériques, réutilisés partout)
    # ------------------------------------------------------------------ #
    def _section(self, title: str) -> Gtk.Widget:
        label = Gtk.Label(label=f"<b>{title}</b>", use_markup=True, xalign=0)
        label.set_margin_top(6)
        return label

    def _row(self, key: str, label_text: str, placeholder: str, is_password: bool = False) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.append(Gtk.Label(label=label_text, xalign=0, width_chars=28))
        entry = Gtk.PasswordEntry(show_peek_icon=True) if is_password else Gtk.Entry()
        if not is_password:
            entry.set_placeholder_text(placeholder)
        entry.set_hexpand(True)
        box.append(entry)
        self._entries[key] = entry
        self._rows[key] = box
        return box

    def _row_spin(self, key: str, label_text: str, default: int, low: int, high: int) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.append(Gtk.Label(label=label_text, xalign=0, width_chars=28))
        adjustment = Gtk.Adjustment(value=default, lower=low, upper=high, step_increment=1)
        spin = Gtk.SpinButton(adjustment=adjustment, numeric=True)
        box.append(spin)
        self._entries[key] = spin
        self._rows[key] = box
        return box

    def _row_spin_float(
        self,
        key: str,
        label_text: str,
        default: float,
        low: float,
        high: float,
        step: float,
        digits: int,
    ) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.append(Gtk.Label(label=label_text, xalign=0, width_chars=28))
        adjustment = Gtk.Adjustment(value=default, lower=low, upper=high, step_increment=step)
        spin = Gtk.SpinButton(adjustment=adjustment, numeric=True, digits=digits)
        box.append(spin)
        self._entries[key] = spin
        self._rows[key] = box
        return box

    def _row_path(self, key: str, label_text: str, default: str, select_folder: bool) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.append(Gtk.Label(label=label_text, xalign=0, width_chars=28))
        entry = Gtk.Entry(placeholder_text=default, hexpand=True)
        box.append(entry)
        browse = Gtk.Button(label="...")
        browse.connect("clicked", self._on_browse, entry, select_folder)
        box.append(browse)
        self._entries[key] = entry
        self._rows[key] = box
        return box

    def _row_check(self, key: str, label_text: str, default: bool) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.append(Gtk.Label(label="", xalign=0, width_chars=28))
        check = Gtk.CheckButton(label=label_text)
        check.set_active(default)
        box.append(check)
        self._entries[key] = check
        self._rows[key] = box
        return box

    def _row_remember_password(self) -> Gtk.Widget:
        """Case « mémoriser » + bouton « oublier », adossés au trousseau système.

        Champ transversal, PAS un champ de `Config` : jamais lu par
        `_build_config`/`_collect_raw_form_values`, jamais repeuplé par
        `_apply_form_values` (même principe que `ssh_password` lui-même —
        un modèle importé ne restaure jamais rien qui touche au mot de
        passe, voir plus haut). Coché explicitement par l'utilisateur, ou
        automatiquement lorsque `_maybe_autofill_password` retrouve un mot
        de passe déjà mémorisé (pour refléter l'état réel du trousseau,
        pas une intention pas encore actée).

        Si ni `keyring` ni `pykeepass` ne sont installés, la case et le
        bouton sont désactivés avec une infobulle explicite plutôt que de
        proposer une action qui échouerait silencieusement.

        Repli KeePass (`keepass_path`, fichier `.kdbx`) : réglage de la
        page Préférences (menu ☰, voir `_open_preferences_window`/
        `self._prefs`), utilisé uniquement quand le trousseau système est
        indisponible (`not KEYRING_AVAILABLE`), même priorité que côté CLI
        (voir `switch_capture_cli.py::_apply_password_keyring_actions`) —
        jamais consulté en plus du trousseau système, seulement à sa
        place. Comme le mot de passe SSH lui-même, le mot de passe maître
        de la base n'est jamais un champ GUI (ni ici ni en Préférences) :
        uniquement via la variable d'environnement
        `SWITCH_CAPTURE_KEEPASS_PASSWORD` (voir
        `_resolve_keepass_master_password`). Depuis features.md, point 1
        (« Menu et préférences »), `keepass_path` est persisté dans
        `config.yaml` : il ne se ressaisit plus à chaque lancement,
        contrairement au mot de passe SSH lui-même.
        """
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.append(Gtk.Label(label="", xalign=0, width_chars=28))
        check = Gtk.CheckButton(label=_("mémoriser le mot de passe SSH"))
        row.append(check)
        btn_forget = Gtk.Button(label=_("Oublier le mot de passe mémorisé"))
        btn_forget.connect("clicked", self._on_forget_password)
        row.append(btn_forget)
        outer.append(row)
        self._entries["remember_password"] = check
        self._rows["remember_password"] = outer

        backend_available = KEYRING_AVAILABLE or KEEPASS_AVAILABLE
        if not backend_available:
            tooltip = (
                "ni le module 'keyring' ni 'pykeepass' ne sont installés — mémorisation du mot de passe indisponible"
            )
            check.set_sensitive(False)
            check.set_tooltip_text(tooltip)
            btn_forget.set_sensitive(False)
            btn_forget.set_tooltip_text(tooltip)

        if not KEYRING_AVAILABLE:
            hint_keepass = Gtk.Label(
                label=_("repli KeePass (.kdbx) : voir Préférences (menu ☰, en haut à gauche)"),
                xalign=0,
            )
            hint_keepass.add_css_class("dim-label")
            outer.append(hint_keepass)

        if backend_available:
            for key in ("switch_ip", "ssh_user"):
                focus = Gtk.EventControllerFocus()
                focus.connect("leave", lambda _c: self._maybe_autofill_password())
                self._entries[key].add_controller(focus)

        return outer

    @staticmethod
    def _resolve_keepass_master_password() -> str | None:
        """Mot de passe maître de la base KeePass de repli, jamais un champ GUI.

        Même principe que `switch_capture_cli.py::_resolve_keepass_master_password`
        et que `ssh_password` lui-même : uniquement lu depuis la variable
        d'environnement `SWITCH_CAPTURE_KEEPASS_PASSWORD`, jamais stocké ni
        affiché par cet outil.
        """
        return os.environ.get("SWITCH_CAPTURE_KEEPASS_PASSWORD") or None

    def _maybe_autofill_password(self) -> None:
        """Retrouve un mot de passe déjà mémorisé, sans jamais écraser une saisie.

        Déclenché quand le focus quitte `switch_ip`/`ssh_user` — même
        principe que la résolution automatique côté CLI (« sans flag
        dédié », voir features.md), transposé au formulaire GTK4 : ne
        touche jamais un champ mot de passe déjà rempli par
        l'utilisateur, et reste silencieux en l'absence d'entrée
        mémorisée (une lecture qui échoue ne doit jamais interrompre la
        saisie en cours).

        Le trousseau système est toujours tenté en premier ; le repli
        KeePass n'est consulté que s'il est indisponible et qu'un fichier
        `.kdbx` a été renseigné dans le champ `keepass_path` — même ordre
        de priorité que côté CLI.
        """
        switch_ip = self._entries["switch_ip"].get_text().strip()
        ssh_user = self._entries["ssh_user"].get_text().strip()
        password_entry = self._entries["ssh_password"]
        if not switch_ip or not ssh_user or password_entry.get_text():
            return

        keepass_path = self._prefs.get("keepass_path") or None
        keepass_master_password = self._resolve_keepass_master_password()

        def worker() -> None:
            password = load_ssh_password_from_keyring(switch_ip, ssh_user)
            if not password:
                password = load_ssh_password_from_keepass(switch_ip, ssh_user, keepass_path, keepass_master_password)
            if not password:
                return

            def apply() -> None:
                # Revérifie qu'aucune saisie n'a eu lieu entre-temps, et que les
                # champs switch/utilisateur n'ont pas changé pendant la requête.
                if (
                    not password_entry.get_text()
                    and self._entries["switch_ip"].get_text().strip() == switch_ip
                    and self._entries["ssh_user"].get_text().strip() == ssh_user
                ):
                    password_entry.set_text(password)
                    self._entries["remember_password"].set_active(True)

            GLib.idle_add(apply)

        threading.Thread(target=worker, daemon=True).start()

    def _on_forget_password(self, _button: Gtk.Button) -> None:
        switch_ip = self._entries["switch_ip"].get_text().strip()
        ssh_user = self._entries["ssh_user"].get_text().strip()
        if not switch_ip or not ssh_user:
            self._show_dialog(
                _("Champs manquants"),
                _("Renseignez l'IP du switch et l'utilisateur SSH pour identifier le mot de passe à oublier."),
            )
            return

        keepass_path = self._prefs.get("keepass_path") or None
        keepass_master_password = self._resolve_keepass_master_password()

        def worker() -> None:
            removed = delete_ssh_password_from_keyring(switch_ip, ssh_user)
            if not removed and not KEYRING_AVAILABLE:
                removed = delete_ssh_password_from_keepass(switch_ip, ssh_user, keepass_path, keepass_master_password)
            message = (
                _("Mot de passe mémorisé supprimé.")
                if removed
                else _("Aucun mot de passe mémorisé pour ce couple switch/utilisateur.")
            )
            GLib.idle_add(self._entries["remember_password"].set_active, False)
            GLib.idle_add(self._show_dialog, _("Mot de passe mémorisé"), message)

        threading.Thread(target=worker, daemon=True).start()

    def _row_dropdown(self, key: str, label_text: str, display_options: list[str]) -> Gtk.Widget:
        """Ligne de formulaire générique pour un champ à choix fermé.

        Args:
            key: clé sous laquelle stocker le widget dans `self._entries`.
            label_text: libellé affiché.
            display_options: libellés affichés, dans le même ordre que les
                valeurs réelles associées (stockées séparément par
                l'appelant, ex: `self._output_mode_options`).

        Returns:
            La ligne (Box) prête à être ajoutée au formulaire.
        """
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.append(Gtk.Label(label=label_text, xalign=0, width_chars=28))
        dropdown = Gtk.DropDown.new_from_strings(display_options)
        box.append(dropdown)
        self._entries[key] = dropdown
        self._rows[key] = box
        return box

    def _row_multiline(self, key: str, label_text: str, hint: str = "") -> Gtk.Widget:
        """Ligne de formulaire pour une liste de valeurs saisies une par ligne.

        Pas d'équivalent « liste répétable » simple en GTK4 (contrairement à
        `--acl-rule` côté CLI, `action="append"`) : un `Gtk.TextView`
        multi-lignes fait l'affaire, une ligne du buffer = une valeur de la
        liste (voir `_build_mirror_config`, closure `multiline()`). Choix
        anticipé dans CLAUDE.md, section « Filtrage ACL pour switch-capture
        mirror », « Reste ouvert ».

        Contrairement à `Gtk.Entry`, `Gtk.TextView` n'a pas de
        `placeholder_text` natif en GTK4 : `hint`, si fourni, sert
        d'exemple affiché en permanence sous le champ (`dim-label`, même
        style que `hint_mirror`/`hint_ntp` ci-dessus) plutôt qu'un texte
        qui disparaîtrait à la saisie.

        Args:
            key: clé sous laquelle stocker le widget dans `self._entries`.
            label_text: libellé affiché.
            hint: exemple optionnel affiché sous le champ.

        Returns:
            La ligne (Box vertical : champ + hint) prête à être ajoutée au
            formulaire — un seul widget, pour que `set_visible()` masque
            le champ et son hint ensemble.
        """
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.append(Gtk.Label(label=label_text, xalign=0, width_chars=28))
        text_view = Gtk.TextView()
        text_view.set_hexpand(True)
        text_view.set_wrap_mode(Gtk.WrapMode.NONE)
        text_view.set_top_margin(4)
        text_view.set_bottom_margin(4)
        text_view.set_left_margin(6)
        text_view.set_right_margin(6)
        scroller = Gtk.ScrolledWindow()
        scroller.set_child(text_view)
        scroller.set_hexpand(True)
        scroller.set_min_content_height(70)
        scroller.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        row.append(scroller)
        outer.append(row)
        if hint:
            hint_label = Gtk.Label(label=hint, xalign=0)
            hint_label.add_css_class("dim-label")
            outer.append(hint_label)
        self._entries[key] = text_view
        self._rows[key] = outer
        return outer

    def _row_filter(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.append(Gtk.Label(label=_("Filtre de capture (tcpdump-like)"), xalign=0, width_chars=28))
        entry = Gtk.Entry(placeholder_text=_("ex: host 10.0.0.5 and tcp port 22"), hexpand=True)
        box.append(entry)
        preset_names = ["(aucun préréglage)"] + list(CAPTURE_FILTER_PRESETS)
        presets = Gtk.DropDown.new_from_strings(preset_names)

        def on_preset_changed(dropdown: Gtk.DropDown, _pspec) -> None:
            idx = dropdown.get_selected()
            if idx <= 0:
                return
            name = preset_names[idx]
            entry.set_text(CAPTURE_FILTER_PRESETS[name])

        presets.connect("notify::selected", on_preset_changed)
        box.append(presets)
        self._entries["capture_filter"] = entry
        self._rows["capture_filter"] = box
        return box

    def _row_import_bin(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.append(Gtk.Label(label="", xalign=0, width_chars=28))
        btn = Gtk.Button(label=_("Importer un dépôt .bin..."))
        btn.connect("clicked", self._on_import_bin)
        box.append(btn)
        hint = Gtk.Label(
            label=_("copie <source>/<modèle>/<version>/*.bin vers le dossier ci-dessus"),
            xalign=0,
        )
        hint.add_css_class("dim-label")
        hint.set_ellipsize(Pango.EllipsizeMode.END)
        hint.set_hexpand(True)
        box.append(hint)
        return box

    def _on_browse(self, _button: Gtk.Button, entry: Gtk.Entry, select_folder: bool) -> None:
        dialog = Gtk.FileChooserNative(
            title=_("Choisir"),
            action=Gtk.FileChooserAction.SELECT_FOLDER if select_folder else Gtk.FileChooserAction.OPEN,
            transient_for=self,
        )

        def on_response(dlg: Gtk.FileChooserNative, response: int) -> None:
            if response == Gtk.ResponseType.ACCEPT:
                gfile = dlg.get_file()
                if gfile:
                    entry.set_text(gfile.get_path() or "")
            dlg.destroy()

        dialog.connect("response", on_response)
        dialog.show()

    def _on_import_bin(self, _button: Gtk.Button) -> None:
        dialog = Gtk.FileChooserNative(
            title=_("Choisir le dossier .bin à importer"),
            action=Gtk.FileChooserAction.SELECT_FOLDER,
            transient_for=self,
        )

        def on_response(dlg: Gtk.FileChooserNative, response: int) -> None:
            if response == Gtk.ResponseType.ACCEPT:
                gfile = dlg.get_file()
                source_dir = gfile.get_path() if gfile else None
                if source_dir:
                    target_dir = self._entries["feature_bin_dir"].get_text().strip() or None
                    self._run_import_bin_async(source_dir, target_dir)
            dlg.destroy()

        dialog.connect("response", on_response)
        dialog.show()

    def _run_import_bin_async(self, source_dir: str, target_dir: str | None) -> None:
        def worker() -> None:
            from switch_capture_cli import run_import_bin

            try:
                code = run_import_bin(source_dir, target_dir)
                if code == 0:
                    target_label = target_dir or _("(défaut)")
                    GLib.idle_add(
                        self._show_dialog,
                        _("Import terminé"),
                        f"{source_dir} → {target_label}",
                    )
                else:
                    GLib.idle_add(self._show_dialog, _("Échec de l'import"), _("Voir le journal pour le détail."))
            except Exception as exc:  # noqa: BLE001
                logger.exception("import_bin | échec")
                GLib.idle_add(self._show_dialog, _("Échec de l'import"), str(exc))

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------ #
    # Page 1 : Configuration (liste de sessions + formulaire d'ajout)
    # ------------------------------------------------------------------ #
    def _build_config_page(self) -> Gtk.Widget:
        """Construit la page Configuration : liste de captures + formulaire d'ajout.

        Returns:
            Le widget racine de la page, prêt à être ajouté au Stack.
        """
        scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroller.set_overlay_scrolling(False)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        outer = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=10,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )
        scroller.set_child(outer)

        outer.append(self._section("Captures planifiées"))
        sessions_scroller = Gtk.ScrolledWindow(min_content_height=120, max_content_height=200)
        sessions_scroller.set_overlay_scrolling(False)
        sessions_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._sessions_list = Gtk.ListBox()
        self._sessions_list.set_selection_mode(Gtk.SelectionMode.NONE)
        sessions_scroller.set_child(self._sessions_list)
        outer.append(sessions_scroller)
        hint_sessions = Gtk.Label(
            label=_("pour modifier une capture : supprimez-la puis recréez-la avec le formulaire ci-dessous"),
            xalign=0,
        )
        hint_sessions.add_css_class("dim-label")
        outer.append(hint_sessions)

        outer.append(Gtk.Separator())
        outer.append(self._section("Nouvelle capture"))

        form = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        outer.append(form)

        form.append(self._section("Switch"))
        form.append(self._row("switch_ip", "IP / nom du switch", "10.0.0.1"))
        form.append(self._row("ssh_user", "Utilisateur SSH (RADIUS)", "mathilde"))
        form.append(self._row("ssh_password", "Mot de passe SSH", "", is_password=True))
        form.append(self._row_remember_password())
        form.append(self._row("capture_label", "Étiquette du point de capture", "client / routeur / serveur"))

        # Point 18 (features.md, « Urgences ») : le formulaire ne
        # permettait pas de choisir entre packet-capture (fifo/tap/rpcap,
        # géré en sessions multi-captures via CaptureSession) et le
        # port mirroring (`switch-capture mirror` en CLI, jusqu'ici
        # totalement absent de la GUI). Les deux méthodes sont
        # mutuellement exclusives et affichées dans deux blocs séparés
        # (voir _apply_capture_type_visibility) plutôt que mélangées dans
        # un seul formulaire : le mirroring pousse uniquement une
        # configuration switch en une action, sans fichier local ni
        # session gérée par cet outil (pages Installation/Démarrage/
        # Résultats non pertinentes pour lui).
        form.append(self._section("Type de capture"))
        self._capture_type_options = ("packet-capture", "mirroring")
        form.append(
            self._row_dropdown(
                "capture_type",
                "Méthode",
                [
                    "packet-capture / rpcap (fichier local ou flux réseau direct)",
                    "port mirroring (SPAN local / GRE distant, débit ligne)",
                ],
            )
        )

        # --- Bloc packet-capture (fifo/tap/rpcap) --------------------- #
        self._packet_capture_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        form.append(self._packet_capture_box)
        pc = self._packet_capture_box

        pc.append(self._section("Feature packet-capture"))
        pc.append(
            self._row_path(
                "feature_bin_dir", "Dépôt local des .bin (par modèle/version)", "./feature-bin", select_folder=True
            )
        )
        pc.append(self._row_import_bin())
        hint_prefs = Gtk.Label(
            label=_("slot IRF/châssis, modèle et .bin forcé : voir Préférences (menu ☰, en haut à gauche)"),
            xalign=0,
        )
        hint_prefs.add_css_class("dim-label")
        pc.append(hint_prefs)

        pc.append(self._section("Transfert de fichiers"))
        self._transfer_mode_options = ("scp", "sshfs")
        pc.append(
            self._row_dropdown(
                "transfer_mode",
                "Mode de transfert",
                ["scp (recommandé)", "sshfs (legacy)"],
            )
        )
        pc.append(self._row_path("mount_point", "Point de montage sshfs", "./mount", select_folder=True))

        pc.append(self._section("NTP"))
        hint_ntp = Gtk.Label(
            label=_("nécessaire pour comparer des traces prises à plusieurs points (client/routeur/serveur)"),
            xalign=0,
        )
        hint_ntp.add_css_class("dim-label")
        pc.append(hint_ntp)
        pc.append(self._row("ntp_server", "Serveur NTP (optionnel)", "10.0.0.254"))
        pc.append(self._row_check("ensure_ntp", "vérifier/configurer NTP au démarrage", True))

        pc.append(self._section("Capture"))
        pc.append(self._row("capture_interface", "Interface", "GigabitEthernet1/0/1"))
        pc.append(self._row_filter())
        pc.append(
            self._row_check(
                "hide_capture_traffic",
                "masquer le trafic SSH/SCP outil↔switch dans la capture",
                True,
            )
        )
        self._capture_direction_options = ("bidirection", "inbound", "outbound")
        pc.append(
            self._row_dropdown(
                "capture_direction",
                "Sens de capture",
                [
                    "bidirection (les deux sens, recommandé)",
                    "inbound (entrant uniquement)",
                    "outbound (sortant uniquement)",
                ],
            )
        )

        pc.append(self._section("Sortie live"))
        self._output_mode_options = ("fifo", "tap", "rpcap")
        pc.append(
            self._row_dropdown(
                "output_mode",
                "Mode de sortie",
                ["fifo (Wireshark auto-lancé)", "tap (captures multiples)", "rpcap (natif Comware, réseau direct)"],
            )
        )
        pc.append(self._row("capture_basename", "Nom de base des fichiers", "capture.pcap"))
        pc.append(self._row_spin("rotation_seconds", "Rotation (s)", 20, 5, 3600))
        pc.append(self._row_spin("max_ring_files", "Fichiers ring-buffer switch", 10, 2, 100))
        pc.append(self._row_path("spool_dir", "Dossier de rapatriement (spool)", "./spool", select_folder=True))
        pc.append(self._row_path("archive_dir", "Dossier d'archivage (optionnel)", "", select_folder=True))
        pc.append(
            self._row_check(
                "archive_as_pcapng",
                "convertir les fichiers archivés en pcapng",
                True,
            )
        )
        pc.append(self._row_spin("poll_interval", "Intervalle de scrutation (s)", 5, 1, 300))
        pc.append(self._row("fifo_path", "FIFO Wireshark live", "./capture_live.fifo"))
        pc.append(self._row("tap_interface", "Interface TAP", "vcap1"))
        pc.append(self._row_check("tap_cleanup_on_stop", "supprimer l'interface TAP à l'arrêt", False))
        pc.append(
            self._row_check(
                "tap_pace_playback",
                "lisser la réinjection TAP selon les timestamps d'origine",
                False,
            )
        )
        pc.append(
            self._row_spin_float(
                "tap_pace_max_gap_seconds",
                "Écart max entre trames (s)",
                2.0,
                0.1,
                3600.0,
                0.5,
                1,
            )
        )
        pc.append(
            self._row_check(
                "tap_launch_wireshark",
                "lancer Wireshark automatiquement sur l'interface TAP",
                False,
            )
        )
        pc.append(self._row_spin("rpcap_port", "Port RPCAP", 2002, 1, 65535))

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, margin_top=8)
        btn_test = Gtk.Button(label=_("Tester la connexion"))
        btn_test.connect("clicked", self._on_test_connection)
        btn_row.append(btn_test)
        btn_add = Gtk.Button(label=_("+ Ajouter cette capture à la liste"))
        btn_add.add_css_class("suggested-action")
        btn_add.connect("clicked", self._on_add_session)
        btn_row.append(btn_add)
        btn_save_template = Gtk.Button(label=_("Enregistrer comme modèle"))
        btn_save_template.connect("clicked", self._on_save_template)
        btn_row.append(btn_save_template)
        btn_load_template = Gtk.Button(label=_("Importer un modèle..."))
        btn_load_template.connect("clicked", self._on_load_template)
        btn_row.append(btn_load_template)
        pc.append(btn_row)
        hint_template = Gtk.Label(
            label=f"les modèles sont enregistrés dans {DEFAULT_MODELS_DIR}/ (jamais le mot de passe SSH)",
            xalign=0,
        )
        hint_template.add_css_class("dim-label")
        pc.append(hint_template)

        # --- Bloc port mirroring (SPAN local / ERSPAN GRE distant) ---- #
        self._mirroring_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        form.append(self._mirroring_box)
        mb = self._mirroring_box

        mb.append(self._section("Port mirroring"))
        hint_mirror = Gtk.Label(
            label=(
                "pousse uniquement la configuration de mirroring sur le switch (SPAN/ERSPAN) — "
                "la capture elle-même se fait côté collecteur (Wireshark/tcpdump), hors du "
                "périmètre de cet outil"
            ),
            xalign=0,
        )
        hint_mirror.add_css_class("dim-label")
        hint_mirror.set_wrap(True)
        mb.append(hint_mirror)

        self._mirror_mode_options = ("local", "gre", "vxlan")
        mb.append(
            self._row_dropdown(
                "mirror_mode",
                "Mode",
                [
                    "local (SPAN, câble direct vers l'hôte de capture)",
                    "gre (ERSPAN tunnel, collecteur distant)",
                    "vxlan (VLAN sonde + VXLAN L2, expérimental — 5520 HI)",
                ],
            )
        )
        mb.append(self._row_spin("mirror_group_id", "Groupe de mirroring", 1, 1, 255))
        mb.append(
            self._row(
                "mirror_source_interfaces",
                "Interfaces sources (séparées par des virgules)",
                "GigabitEthernet1/0/1, GigabitEthernet1/0/2",
            )
        )
        self._mirror_direction_options = ("both", "inbound", "outbound")
        mb.append(
            self._row_dropdown(
                "mirror_direction",
                "Sens",
                ["both (les deux sens, recommandé)", "inbound (entrant uniquement)", "outbound (sortant uniquement)"],
            )
        )
        mb.append(
            self._row(
                "mirror_monitor_interface",
                "Interface de destination (mode local)",
                "GigabitEthernet1/0/24",
            )
        )
        mb.append(self._row_spin("mirror_tunnel_id", "Numéro interface Tunnel (mode gre)", 1, 1, 1023))
        mb.append(self._row("mirror_tunnel_local_ip", "IP source du tunnel (mode gre/vxlan)", "10.0.0.1"))
        mb.append(self._row("mirror_tunnel_ip", "IP de l'interface Tunnel (mode gre)", "192.0.2.1"))
        mb.append(self._row("mirror_tunnel_mask", "Masque de l'interface Tunnel (mode gre)", "255.255.255.0"))
        mb.append(self._row("mirror_remote_ip", "IP du collecteur distant (mode gre/vxlan)", "203.0.113.1"))
        mb.append(
            self._row(
                "mirror_loopback_interface",
                "Interface service-loopback (mode gre, optionnel)",
                "GigabitEthernet1/0/23",
            )
        )

        # Filtrage ACL (features.md, section « Filtrage ACL pour
        # switch-capture mirror », core+CLI traités le 01/09/2026 — voir
        # CLAUDE.md pour le détail) : par défaut ("port"), comportement
        # mirroring-group historique inchangé (rien à ajouter ici). En
        # "acl", ne duplique que le trafic qui correspond à acl_rules,
        # via traffic classifier/behavior + qos policy plutôt qu'un
        # mirroring-group entier — voir configure_acl_mirror côté core et
        # CAPTURE-METHODS.md section 4. Les champs ci-dessous ne sont
        # utiles/visibles qu'en filter_mode "acl" (_apply_mirror_mode_visibility).
        self._mirror_filter_mode_options = ("port", "acl")
        mb.append(
            self._row_dropdown(
                "mirror_filter_mode",
                "Mode de filtrage",
                [
                    "port (mirroring-group historique, tout le trafic du port)",
                    "acl (flow mirroring filtré par ACL avancée + QoS)",
                ],
            )
        )
        mb.append(self._row_spin("mirror_acl_number", "Numéro ACL avancée (mode acl)", 3000, 3000, 3999))
        mb.append(
            self._row_multiline(
                "mirror_acl_rules",
                "Règles ACL, une par ligne (mode acl)",
                hint="ex. : rule 0 permit ip source 10.0.0.5 0",
            )
        )
        mb.append(
            self._row(
                "mirror_classifier_name",
                "Nom du traffic classifier (mode acl, optionnel)",
                "SWCAP_CLS_1 (déduit du Groupe de mirroring si vide)",
            )
        )
        mb.append(
            self._row(
                "mirror_behavior_name",
                "Nom du traffic behavior (mode acl, optionnel)",
                "SWCAP_BEH_1 (déduit du Groupe de mirroring si vide)",
            )
        )
        mb.append(
            self._row(
                "mirror_qos_policy_name",
                "Nom de la qos policy (mode acl, optionnel)",
                "SWCAP_POL_1 (déduit du Groupe de mirroring si vide)",
            )
        )

        # Mode vxlan (features.md, point 20 : mirroring vers VLAN sonde +
        # VXLAN L2, implémentation core+CLI le 05/09/2026 — voir
        # CLAUDE.md/CAPTURE-METHODS.md section 5) ⚠️ expérimental, jamais
        # vérifié contre un switch réel dans ce dépôt. Non combinable avec
        # filter_mode == "acl" côté core (MirrorConfig.__post_init__) :
        # ces champs restent donc masqués dès que filter_mode == "acl",
        # quel que soit mode (voir _apply_mirror_mode_visibility).
        hint_vxlan = Gtk.Label(
            label=(
                "⚠️ expérimental : combinaison non officiellement documentée par H3C, "
                "jamais vérifiée contre un switch réel dans ce dépôt — voir CAPTURE-METHODS.md"
            ),
            xalign=0,
        )
        hint_vxlan.add_css_class("dim-label")
        hint_vxlan.set_wrap(True)
        mb.append(hint_vxlan)
        self._rows["mirror_vxlan_hint"] = hint_vxlan
        mb.append(
            self._row_spin(
                "mirror_remote_probe_vlan",
                "VLAN sonde (mode vxlan)",
                666,
                1,
                4094,
            )
        )
        mb.append(
            self._row(
                "mirror_vsi_name",
                "Nom de la VSI (mode vxlan)",
                "mirror",
            )
        )
        mb.append(
            self._row_spin(
                "mirror_vxlan_vni",
                "VNI VXLAN (mode vxlan)",
                666,
                0,
                16777215,
            )
        )
        mb.append(
            self._row(
                "mirror_service_instance_id",
                "Numéro service-instance (mode vxlan, optionnel)",
                "déduit du Groupe de mirroring si vide",
            )
        )
        mb.append(
            self._row(
                "mirror_reflector_interface",
                "Interface réflecteur (mode vxlan)",
                "GigabitEthernet1/0/23",
            )
        )

        mirror_btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, margin_top=8)
        btn_mirror_push = Gtk.Button(label=_("Pousser la configuration de mirroring"))
        btn_mirror_push.add_css_class("suggested-action")
        btn_mirror_push.connect("clicked", self._on_push_mirror)
        mirror_btn_row.append(btn_mirror_push)
        btn_mirror_teardown = Gtk.Button(label=_("Retirer le mirroring"))
        btn_mirror_teardown.connect("clicked", self._on_teardown_mirror)
        mirror_btn_row.append(btn_mirror_teardown)
        mb.append(mirror_btn_row)

        # Visibilité conditionnelle : n'afficher que les champs pertinents
        # pour le mode choisi (capture_type / transfer_mode / output_mode /
        # mirror_mode).
        self._entries["capture_type"].connect("notify::selected", lambda *_a: self._apply_capture_type_visibility())
        self._entries["transfer_mode"].connect("notify::selected", lambda *_a: self._apply_transfer_mode_visibility())
        self._entries["output_mode"].connect("notify::selected", lambda *_a: self._apply_output_mode_visibility())
        self._entries["mirror_mode"].connect("notify::selected", lambda *_a: self._apply_mirror_mode_visibility())
        self._entries["mirror_filter_mode"].connect(
            "notify::selected", lambda *_a: self._apply_mirror_mode_visibility()
        )
        self._apply_capture_type_visibility()
        self._apply_transfer_mode_visibility()
        self._apply_output_mode_visibility()
        self._apply_mirror_mode_visibility()

        return scroller

    def _apply_capture_type_visibility(self) -> None:
        """Bascule entre le bloc packet-capture et le bloc mirroring.

        Les deux méthodes sont mutuellement exclusives dans le formulaire
        (voir commentaire au-dessus du dropdown `capture_type`).
        """
        capture_type = self._capture_type_options[self._entries["capture_type"].get_selected()]
        self._packet_capture_box.set_visible(capture_type == "packet-capture")
        self._mirroring_box.set_visible(capture_type == "mirroring")

    def _apply_mirror_mode_visibility(self) -> None:
        """N'affiche que les champs pertinents pour `mirror_mode`/`mirror_filter_mode`.

        Les deux réglages interagissent : en `filter_mode == "acl"`,
        `configure_acl_mirror()` (core) encapsule l'ERSPAN inline dans le
        `mirror-to` et ne lit que `tunnel_local_ip`/`remote_ip` — aucune
        interface Tunnel n'est créée, contrairement à
        `configure_gre_mirror()` (`filter_mode == "port"` seul), qui est
        la seule à utiliser `tunnel_id`/`tunnel_ip`/`tunnel_mask`/
        `loopback_interface` (voir `MirrorConfig`, docstring de
        `loopback_interface`, et le corps de `configure_acl_mirror` côté
        core). Les masquer en `filter_mode == "acl"` évite de laisser
        croire qu'ils sont pris en compte alors qu'ils seraient
        silencieusement ignorés.
        """
        mode = self._mirror_mode_options[self._entries["mirror_mode"].get_selected()]
        filter_mode = self._mirror_filter_mode_options[self._entries["mirror_filter_mode"].get_selected()]

        self._rows["mirror_monitor_interface"].set_visible(mode == "local")
        for key in ("mirror_tunnel_local_ip", "mirror_remote_ip"):
            # Communs aux modes "gre" et "vxlan" (voir MirrorConfig.__post_init__ :
            # tous deux exigent tunnel_local_ip/remote_ip, contrairement aux
            # champs "gre"-uniquement ci-dessous, ex. tunnel_id/tunnel_ip).
            self._rows[key].set_visible(mode in ("gre", "vxlan"))
        for key in (
            "mirror_tunnel_id",
            "mirror_tunnel_ip",
            "mirror_tunnel_mask",
            "mirror_loopback_interface",
        ):
            self._rows[key].set_visible(mode == "gre" and filter_mode == "port")

        for key in (
            "mirror_acl_number",
            "mirror_acl_rules",
            "mirror_classifier_name",
            "mirror_behavior_name",
            "mirror_qos_policy_name",
        ):
            self._rows[key].set_visible(filter_mode == "acl")

        # Mode vxlan : non combinable avec filter_mode == "acl" côté core
        # (MirrorConfig.__post_init__ refuse cette combinaison) — masqué
        # dans ce cas plutôt que de laisser croire à une combinaison
        # acceptée. Voir commentaire au-dessus de l'ajout de ces champs.
        for key in (
            "mirror_vxlan_hint",
            "mirror_remote_probe_vlan",
            "mirror_vsi_name",
            "mirror_vxlan_vni",
            "mirror_service_instance_id",
            "mirror_reflector_interface",
        ):
            self._rows[key].set_visible(mode == "vxlan" and filter_mode == "port")

    def _apply_transfer_mode_visibility(self) -> None:
        """N'affiche `mount_point` que si le mode de transfert est 'sshfs'."""
        mode = self._transfer_mode_options[self._entries["transfer_mode"].get_selected()]
        self._rows["mount_point"].set_visible(mode == "sshfs")

    def _apply_output_mode_visibility(self) -> None:
        """N'affiche que les champs pertinents pour le mode de sortie choisi.

        - fifo : fichiers rapatriés (rotation/spool/archive/poll) + FIFO.
        - tap  : fichiers rapatriés (rotation/spool/archive/poll) + interface TAP.
        - rpcap : aucun fichier local — masque tout ce qui concerne le
          ring-buffer/rapatriement, ne garde que le port RPCAP.
        """
        mode = self._output_mode_options[self._entries["output_mode"].get_selected()]

        file_based_keys = (
            "capture_basename",
            "rotation_seconds",
            "max_ring_files",
            "spool_dir",
            "archive_dir",
            "archive_as_pcapng",
            "poll_interval",
        )
        for key in file_based_keys:
            self._rows[key].set_visible(mode in ("fifo", "tap"))

        self._rows["fifo_path"].set_visible(mode == "fifo")
        self._rows["tap_interface"].set_visible(mode == "tap")
        self._rows["tap_cleanup_on_stop"].set_visible(mode == "tap")
        self._rows["tap_pace_playback"].set_visible(mode == "tap")
        self._rows["tap_pace_max_gap_seconds"].set_visible(mode == "tap")
        self._rows["tap_launch_wireshark"].set_visible(mode == "tap")
        self._rows["rpcap_port"].set_visible(mode == "rpcap")

    def _on_test_connection(self, _button: Gtk.Button) -> None:
        try:
            cfg = self._build_config()
        except ValueError as exc:
            self._show_dialog(_("Configuration incomplète"), str(exc))
            return

        def worker() -> None:
            from switch_capture_core import (
                connect_switch,
                detect_model,
                detect_software_version,
            )

            try:
                conn = connect_switch(cfg)
                try:
                    version_output = conn.send_command("display version")
                finally:
                    conn.disconnect()
                model = detect_model(version_output) or "non reconnu"
                version = detect_software_version(version_output) or "?"
                message = f"Connexion OK — modèle détecté : {model}, version : {version}"
                GLib.idle_add(self._show_dialog, _("Connexion réussie"), message)
            except Exception as exc:  # noqa: BLE001
                logger.exception("test_connection | échec")
                GLib.idle_add(self._show_dialog, _("Échec de la connexion"), str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _on_add_session(self, _button: Gtk.Button) -> None:
        try:
            cfg = self._build_config()
        except ValueError as exc:
            self._show_dialog(_("Configuration incomplète"), str(exc))
            return

        session = CaptureSession(cfg)
        self._sessions.append(session)
        self._refresh_sessions_list()
        self._refresh_install_list()
        self._refresh_start_list()
        self._set_journal_status(f"Capture ajoutée : {session.label}")
        self._maybe_remember_password(cfg)

    def _build_mirror_config(self) -> MirrorConfig:
        """Construit un MirrorConfig à partir de l'état courant du bloc mirroring.

        Réutilise directement la validation déjà faite par
        `MirrorConfig.__post_init__` (champs obligatoires selon `mode`)
        plutôt que de la dupliquer ici.

        Returns:
            L'objet MirrorConfig validé.

        Raises:
            ValueError: si un champ obligatoire est manquant ou invalide
                (propagé depuis `MirrorConfig.__post_init__`).
        """

        def text(key: str) -> str:
            widget = self._entries[key]
            if isinstance(widget, Gtk.PasswordEntry):
                return widget.get_text()
            return widget.get_text().strip()

        def spin(key: str) -> int:
            return int(self._entries[key].get_value())

        def dropdown_value(key: str, values: tuple[str, ...]) -> str:
            dropdown: Gtk.DropDown = self._entries[key]
            return values[dropdown.get_selected()]

        def multiline(key: str) -> list[str]:
            """Une valeur par ligne non vide du `Gtk.TextView` (`acl_rules`).

            Équivalent GUI de `--acl-rule` répétable côté CLI
            (`action="append"`) — voir `_row_multiline`.
            """
            buffer = self._entries[key].get_buffer()
            start, end = buffer.get_bounds()
            raw = buffer.get_text(start, end, False)
            return [line.strip() for line in raw.splitlines() if line.strip()]

        source_interfaces = [iface.strip() for iface in text("mirror_source_interfaces").split(",") if iface.strip()]

        return MirrorConfig(
            switch_ip=text("switch_ip"),
            ssh_user=text("ssh_user"),
            ssh_password=text("ssh_password"),
            mode=dropdown_value("mirror_mode", self._mirror_mode_options),
            group_id=spin("mirror_group_id"),
            source_interfaces=source_interfaces,
            direction=dropdown_value("mirror_direction", self._mirror_direction_options),
            monitor_interface=text("mirror_monitor_interface") or None,
            tunnel_id=spin("mirror_tunnel_id"),
            tunnel_local_ip=text("mirror_tunnel_local_ip") or None,
            tunnel_ip=text("mirror_tunnel_ip") or None,
            tunnel_mask=text("mirror_tunnel_mask") or "255.255.255.0",
            remote_ip=text("mirror_remote_ip") or None,
            loopback_interface=text("mirror_loopback_interface") or None,
            filter_mode=dropdown_value("mirror_filter_mode", self._mirror_filter_mode_options),
            acl_number=spin("mirror_acl_number"),
            acl_rules=multiline("mirror_acl_rules"),
            classifier_name=text("mirror_classifier_name") or None,
            behavior_name=text("mirror_behavior_name") or None,
            qos_policy_name=text("mirror_qos_policy_name") or None,
            remote_probe_vlan=spin("mirror_remote_probe_vlan"),
            vsi_name=text("mirror_vsi_name") or None,
            vxlan_vni=spin("mirror_vxlan_vni"),
            service_instance_id=(
                int(text("mirror_service_instance_id")) if text("mirror_service_instance_id") else None
            ),
            reflector_interface=text("mirror_reflector_interface") or None,
        )

    def _on_push_mirror(self, _button: Gtk.Button) -> None:
        self._run_mirror_thread(teardown=False)

    def _on_teardown_mirror(self, _button: Gtk.Button) -> None:
        self._run_mirror_thread(teardown=True)

    def _run_mirror_thread(self, teardown: bool) -> None:
        """Pousse (ou retire) la configuration de mirroring en tâche de fond.

        Même schéma que `_on_uninstall_session`/`UninstallThread` :
        `MirrorThread` déjà existant côté core (utilisé jusqu'ici
        uniquement par le CLI `switch-capture mirror`), simplement câblé
        ici sur le bloc mirroring du formulaire GTK.
        """
        try:
            mirror_cfg = self._build_mirror_config()
        except ValueError as exc:
            self._show_dialog(_("Configuration de mirroring incomplète"), str(exc))
            return

        def on_done(success: bool, message: str) -> None:
            if success:
                title = _("Mirroring retiré") if teardown else _("Mirroring configuré")
            else:
                title = _("Échec du retrait du mirroring") if teardown else _("Échec de la configuration du mirroring")
            GLib.idle_add(self._show_dialog, title, message)
            GLib.idle_add(self._set_journal_status, message)

        thread = MirrorThread(mirror_cfg, teardown=teardown, on_done=on_done)
        self._mirror_threads.append(thread)
        thread.start()
        action = "Retrait" if teardown else "Configuration"
        self._set_journal_status(f"{action} du mirroring en cours pour {mirror_cfg.switch_ip} ...")

    def _maybe_remember_password(self, cfg: Config) -> None:
        """Mémorise le mot de passe SSH si la case « mémoriser » est cochée.

        Appelée après un ajout de capture réussi (`cfg` déjà validé par
        `_build_config`). Ne fait rien si la case n'est pas cochée. Le
        trousseau système est toujours prioritaire quand il est
        disponible ; le repli KeePass (`keepass_path` + variable
        d'environnement `SWITCH_CAPTURE_KEEPASS_PASSWORD`) n'est utilisé
        que si `keyring` est indisponible — même priorité que côté CLI
        (voir `switch_capture_cli.py::_apply_password_keyring_actions`).
        L'échec d'écriture — trousseau verrouillé, service Secret Service
        absent, fichier KeePass introuvable ou mot de passe maître
        incorrect — est signalé explicitement plutôt qu'avalé,
        l'utilisateur ayant coché la case volontairement.
        """
        if not self._entries["remember_password"].get_active():
            return

        if KEYRING_AVAILABLE:

            def worker() -> None:
                try:
                    save_ssh_password_to_keyring(cfg.switch_ip, cfg.ssh_user, cfg.ssh_password)
                except RuntimeError as exc:
                    GLib.idle_add(self._show_dialog, _("Échec de la mémorisation"), str(exc))

            threading.Thread(target=worker, daemon=True).start()
            return

        keepass_path = self._prefs.get("keepass_path") or ""
        keepass_master_password = self._resolve_keepass_master_password()
        if not KEEPASS_AVAILABLE or not keepass_path or not keepass_master_password:
            self._show_dialog(
                _("Mémorisation impossible"),
                _(
                    "Ni le trousseau système ni le repli KeePass ne sont utilisables : installez "
                    "le module 'keyring', ou renseignez le fichier KeePass dans Préférences (menu ☰) "
                    "et la variable d'environnement SWITCH_CAPTURE_KEEPASS_PASSWORD avant d'ajouter "
                    "cette capture."
                ),
            )
            return

        def worker() -> None:
            try:
                save_ssh_password_to_keepass(
                    cfg.switch_ip, cfg.ssh_user, cfg.ssh_password, keepass_path, keepass_master_password
                )
            except RuntimeError as exc:
                GLib.idle_add(self._show_dialog, _("Échec de la mémorisation (KeePass)"), str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _on_remove_session(self, _button: Gtk.Button, session: CaptureSession) -> None:
        if session in self._sessions:
            self._sessions.remove(session)
        self._refresh_sessions_list()
        self._refresh_install_list()
        self._refresh_start_list()

    @staticmethod
    def _config_to_raw_dict(cfg: Config) -> dict:
        """Convertit un `Config` existant vers le format attendu par `_apply_form_values`.

        Mêmes clés que `_collect_raw_form_values` (donc `ssh_password`
        volontairement absent de ce dict, même si `_on_edit_session`
        le reporte séparément sur le widget mot de passe : on garde le
        principe déjà en place pour les modèles de capture — le mot de
        passe ne transite jamais par le mécanisme générique
        `_apply_form_values`/sérialisation). `slot`/`model`/
        `feature_bin_path` également absents, pour la même raison que côté
        `_collect_raw_form_values` : ce ne sont plus des champs du
        formulaire mais des préférences globales (`self._prefs`, page
        Préférences, features.md point 1) — `_on_edit_session` les
        resynchronise séparément sur `self._prefs` directement depuis
        `cfg`, sans passer par ce dict.
        """
        return {
            "switch_ip": cfg.switch_ip,
            "ssh_user": cfg.ssh_user,
            "capture_label": cfg.capture_label,
            "feature_bin_dir": cfg.feature_bin_dir,
            "transfer_mode": cfg.transfer_mode,
            "mount_point": cfg.mount_point,
            "ntp_server": cfg.ntp_server,
            "ensure_ntp": cfg.ensure_ntp,
            "capture_interface": cfg.capture_interface,
            "capture_basename": cfg.capture_basename,
            "rotation_seconds": cfg.rotation_seconds,
            "max_ring_files": cfg.max_ring_files,
            "capture_filter": cfg.capture_filter,
            "hide_capture_traffic": cfg.hide_capture_traffic,
            "capture_direction": cfg.capture_direction,
            "output_mode": cfg.output_mode,
            "tap_interface": cfg.tap_interface,
            "tap_cleanup_on_stop": cfg.tap_cleanup_on_stop,
            "tap_pace_playback": cfg.tap_pace_playback,
            "tap_pace_max_gap_seconds": cfg.tap_pace_max_gap_seconds,
            "tap_launch_wireshark": cfg.tap_launch_wireshark,
            "rpcap_port": cfg.rpcap_port,
            "spool_dir": cfg.spool_dir,
            "archive_dir": cfg.archive_dir,
            "archive_as_pcapng": cfg.archive_as_pcapng,
            "fifo_path": cfg.fifo_path,
            "poll_interval": cfg.poll_interval,
        }

    def _on_edit_session(self, _button: Gtk.Button, session: CaptureSession) -> None:
        """Bascule une capture déjà ajoutée vers le formulaire pour modification.

        Il ne s'agit pas d'une édition in-place au sens strict : la
        session est retirée de `self._sessions` (comme « Supprimer »)
        puis le formulaire d'ajout est entièrement repeuplé avec ses
        valeurs, mot de passe SSH compris (contrairement à l'import d'un
        modèle depuis le disque, ce mot de passe n'a jamais quitté la
        mémoire du processus, donc le reporter ici ne l'expose pas plus
        qu'il ne l'était déjà). L'utilisateur ajuste les champs voulus
        puis clique de nouveau « + Ajouter cette capture à la liste » —
        ce qui supprime le geste manuel de ressaisie complète qui
        constituait la limite documentée (« supprimer puis recréer »,
        voir features.md).

        Ignoré si la capture est déjà en cours (`capture_running`), pour
        ne pas modifier sous le tapis la config d'un thread actif — le
        bouton est d'ailleurs désactivé dans ce cas dans
        `_refresh_sessions_list`.
        """
        if session.capture_running:
            return
        if session in self._sessions:
            self._sessions.remove(session)
        # slot/modèle/.bin forcé ne sont plus des champs du formulaire
        # (page Préférences, features.md point 1) : resynchronise
        # self._prefs sur les valeurs de CETTE session avant repeuplement,
        # pour qu'un nouvel ajout après modification ne fasse pas glisser
        # silencieusement ces 3 réglages vers ceux actuellement en
        # Préférences (qui ont pu changer depuis l'ajout de cette
        # session) — voir _config_to_raw_dict.
        self._prefs["slot"] = session.cfg.slot
        self._prefs["model"] = session.cfg.model
        self._prefs["feature_bin_path"] = session.cfg.feature_bin_path or ""
        self._apply_form_values(self._config_to_raw_dict(session.cfg))
        self._entries["ssh_password"].set_text(session.cfg.ssh_password or "")
        self._refresh_sessions_list()
        self._refresh_install_list()
        self._refresh_start_list()
        self._stack.set_visible_child_name("config")
        self._set_journal_status(
            f"Capture {session.label} retirée de la liste et chargée dans le formulaire pour modification."
        )

    def _refresh_sessions_list(self) -> None:
        self._clear_listbox(self._sessions_list)
        if not self._sessions:
            row = Gtk.ListBoxRow()
            row.set_child(
                Gtk.Label(label=_("Aucune capture ajoutée pour l'instant."), xalign=0, margin_top=6, margin_bottom=6)
            )
            self._sessions_list.append(row)
            return
        for session in self._sessions:
            row_box = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL,
                spacing=8,
                margin_top=4,
                margin_bottom=4,
                margin_start=8,
                margin_end=8,
            )
            row_box.append(Gtk.Label(label=session.label, xalign=0, hexpand=True))
            btn_inspect = Gtk.Button(label=_("Inspecter (dry run)"))
            btn_inspect.connect("clicked", self._on_inspect_session, session)
            row_box.append(btn_inspect)
            btn_uninstall = Gtk.Button(label=_("Désinstaller la feature"))
            btn_uninstall.add_css_class("destructive-action")
            btn_uninstall.connect("clicked", self._on_uninstall_session, session)
            row_box.append(btn_uninstall)
            btn_edit = Gtk.Button(label=_("Modifier"))
            btn_edit.set_sensitive(not session.capture_running)
            btn_edit.connect("clicked", self._on_edit_session, session)
            row_box.append(btn_edit)
            btn_remove = Gtk.Button(label=_("Supprimer"))
            btn_remove.connect("clicked", self._on_remove_session, session)
            row_box.append(btn_remove)
            row = Gtk.ListBoxRow()
            row.set_child(row_box)
            self._sessions_list.append(row)

    def _on_inspect_session(self, _button: Gtk.Button, session: CaptureSession) -> None:
        """Lance le mode dry run (lecture seule) pour `session`, en tâche de fond.

        Réutilise les paramètres de connexion déjà saisis pour cette
        capture (session.cfg) mais via `InspectConfig`, plus léger : aucune
        commande de configuration n'est jamais envoyée, seulement des
        'display' (voir `inspect_switch`).
        """
        self._set_journal_status(f"Inspection (dry run) en cours pour {session.label} ...")

        def worker() -> None:
            try:
                inspect_cfg = InspectConfig(
                    switch_ip=session.cfg.switch_ip,
                    ssh_user=session.cfg.ssh_user,
                    ssh_password=session.cfg.ssh_password,
                    model=session.cfg.model,
                    feature_bin_path=session.cfg.feature_bin_path,
                    feature_bin_dir=session.cfg.feature_bin_dir,
                    transfer_mode=session.cfg.transfer_mode,
                )
                report = inspect_switch(inspect_cfg)
                message = format_inspect_report(session.cfg.switch_ip, inspect_cfg.transfer_mode, report)
                GLib.idle_add(self._show_dialog, _("Inspection de {ip}").format(ip=session.cfg.switch_ip), message)
                GLib.idle_add(self._set_journal_status, f"Inspection terminée pour {session.label}")
            except Exception as exc:  # noqa: BLE001
                logger.exception("inspect | échec pour {label}", label=session.label)
                GLib.idle_add(self._show_dialog, _("Échec de l'inspection"), str(exc))
                GLib.idle_add(self._set_journal_status, f"Inspection en échec pour {session.label} : {exc}")

        threading.Thread(target=worker, daemon=True, name=f"inspect-{session.id}").start()

    def _on_uninstall_session(self, _button: Gtk.Button, session: CaptureSession) -> None:
        confirm = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE,
            text=f"Désinstaller packet-capture sur {session.cfg.switch_ip} ?",
            secondary_text=(
                f"Slot {session.cfg.slot}. Sans lien avec la suppression de cette capture "
                "de la liste ci-dessus.\n"
                f"Pour confirmer, retapez l'IP du switch ({session.cfg.switch_ip}) ci-dessous."
            ),
        )
        confirm.add_button(_("Annuler"), Gtk.ResponseType.CANCEL)
        chk_remove_bin = Gtk.CheckButton(label=_("supprimer aussi le .bin de la flash"))
        confirm.get_message_area().append(chk_remove_bin)
        entry_confirm_ip = Gtk.Entry(placeholder_text=session.cfg.switch_ip, hexpand=True)
        confirm.get_message_area().append(entry_confirm_ip)
        btn_uninstall = confirm.add_button(_("Désinstaller"), Gtk.ResponseType.OK)
        btn_uninstall.set_sensitive(False)

        def _on_confirm_ip_changed(entry: Gtk.Entry) -> None:
            btn_uninstall.set_sensitive(confirm_ip_matches(entry.get_text(), session.cfg.switch_ip))

        entry_confirm_ip.connect("changed", _on_confirm_ip_changed)

        def on_response(dlg: Gtk.MessageDialog, response: int) -> None:
            remove_bin = chk_remove_bin.get_active()
            ip_confirmed = confirm_ip_matches(entry_confirm_ip.get_text(), session.cfg.switch_ip)
            dlg.destroy()
            if response != Gtk.ResponseType.OK or not ip_confirmed:
                return

            def on_done(success: bool, message: str) -> None:
                GLib.idle_add(
                    self._show_dialog,
                    _("Désinstallation terminée") if success else _("Échec de la désinstallation"),
                    message,
                )
                GLib.idle_add(self._set_journal_status, message)

            thread = UninstallThread(session.cfg, session.state, remove_bin, on_done)
            self._uninstall_threads.append(thread)
            thread.start()
            self._set_journal_status(f"Désinstallation en cours pour {session.label} ...")

        confirm.connect("response", on_response)
        confirm.show()

    # ------------------------------------------------------------------ #
    # Lecture du formulaire -> Config
    # ------------------------------------------------------------------ #
    def _build_config(self) -> Config:
        """Construit un Config à partir de l'état courant du formulaire d'ajout.

        `slot`/`model`/`feature_bin_path` ne sont plus des champs de ce
        formulaire (page Préférences, features.md point 1) : lus depuis
        `self._prefs`, à jour au démarrage (config.yaml) ou après un
        « Enregistrer » en Préférences pendant la session.

        Returns:
            L'objet Config validé.

        Raises:
            ValueError: si un champ obligatoire est manquant ou invalide.
        """

        def text(key: str) -> str:
            widget = self._entries[key]
            if isinstance(widget, Gtk.PasswordEntry):
                return widget.get_text()
            return widget.get_text().strip()

        def spin(key: str) -> int:
            return int(self._entries[key].get_value())

        def check(key: str) -> bool:
            return self._entries[key].get_active()

        def dropdown_value(key: str, values: tuple[str, ...]) -> str:
            dropdown: Gtk.DropDown = self._entries[key]
            return values[dropdown.get_selected()]

        return Config(
            switch_ip=text("switch_ip"),
            ssh_user=text("ssh_user"),
            ssh_password=text("ssh_password"),
            slot=self._prefs["slot"],
            model=self._prefs["model"],
            capture_label=text("capture_label"),
            feature_bin_path=self._prefs["feature_bin_path"] or None,
            feature_bin_dir=text("feature_bin_dir") or "./feature-bin",
            transfer_mode=dropdown_value("transfer_mode", self._transfer_mode_options),
            mount_point=text("mount_point") or "./mount",
            ntp_server=text("ntp_server") or None,
            ensure_ntp=check("ensure_ntp"),
            capture_interface=text("capture_interface"),
            capture_basename=text("capture_basename") or "capture.pcap",
            rotation_seconds=spin("rotation_seconds"),
            max_ring_files=spin("max_ring_files"),
            capture_filter=text("capture_filter"),
            hide_capture_traffic=check("hide_capture_traffic"),
            capture_direction=dropdown_value("capture_direction", self._capture_direction_options),
            output_mode=dropdown_value("output_mode", self._output_mode_options),
            tap_interface=text("tap_interface") or None,
            tap_cleanup_on_stop=check("tap_cleanup_on_stop"),
            tap_pace_playback=check("tap_pace_playback"),
            tap_pace_max_gap_seconds=self._entries["tap_pace_max_gap_seconds"].get_value(),
            tap_launch_wireshark=check("tap_launch_wireshark"),
            rpcap_port=spin("rpcap_port"),
            spool_dir=text("spool_dir") or "./spool",
            archive_dir=text("archive_dir") or None,
            archive_as_pcapng=check("archive_as_pcapng"),
            fifo_path=text("fifo_path") or "./capture_live.fifo",
            poll_interval=spin("poll_interval"),
        )

    # ------------------------------------------------------------------ #
    # Modèles de capture réutilisables (Enregistrer/Importer)
    # ------------------------------------------------------------------ #
    def _collect_raw_form_values(self) -> dict:
        """Lit tous les champs du formulaire d'ajout, sans validation.

        Contrairement à `_build_config`, ne lève jamais d'exception sur un
        champ obligatoire manquant (un modèle peut être enregistré
        partiellement rempli) et n'inclut **jamais** `ssh_password` : le
        mot de passe reste uniquement dans le widget `Gtk.PasswordEntry`
        en mémoire, jamais transmis à la couche de sérialisation.
        `slot`/`model`/`feature_bin_path` non plus : ce ne sont plus des
        champs de ce formulaire mais des préférences globales à l'outil
        (`self._prefs`, page Préférences, features.md point 1) — un modèle
        de capture réutilisable n'a pas à les embarquer (voir aussi
        `TEMPLATE_EXCLUDED_FIELDS` côté `switch_capture_core.py`).

        Returns:
            Un dict brut key -> valeur, aux mêmes clés que les champs de
            `Config` (hors `ssh_password`/`slot`/`model`/`feature_bin_path`).
        """

        def text(key: str) -> str:
            return self._entries[key].get_text().strip()

        def spin(key: str) -> int:
            return int(self._entries[key].get_value())

        def check(key: str) -> bool:
            return self._entries[key].get_active()

        def dropdown_value(key: str, values: tuple[str, ...]) -> str:
            dropdown: Gtk.DropDown = self._entries[key]
            return values[dropdown.get_selected()]

        return {
            "switch_ip": text("switch_ip"),
            "ssh_user": text("ssh_user"),
            "capture_label": text("capture_label"),
            "feature_bin_dir": text("feature_bin_dir") or "./feature-bin",
            "transfer_mode": dropdown_value("transfer_mode", self._transfer_mode_options),
            "mount_point": text("mount_point") or "./mount",
            "ntp_server": text("ntp_server") or None,
            "ensure_ntp": check("ensure_ntp"),
            "capture_interface": text("capture_interface"),
            "capture_basename": text("capture_basename") or "capture.pcap",
            "rotation_seconds": spin("rotation_seconds"),
            "max_ring_files": spin("max_ring_files"),
            "capture_filter": text("capture_filter"),
            "hide_capture_traffic": check("hide_capture_traffic"),
            "capture_direction": dropdown_value("capture_direction", self._capture_direction_options),
            "output_mode": dropdown_value("output_mode", self._output_mode_options),
            "tap_interface": text("tap_interface") or None,
            "tap_cleanup_on_stop": check("tap_cleanup_on_stop"),
            "tap_pace_playback": check("tap_pace_playback"),
            "tap_pace_max_gap_seconds": self._entries["tap_pace_max_gap_seconds"].get_value(),
            "tap_launch_wireshark": check("tap_launch_wireshark"),
            "rpcap_port": spin("rpcap_port"),
            "spool_dir": text("spool_dir") or "./spool",
            "archive_dir": text("archive_dir") or None,
            "archive_as_pcapng": check("archive_as_pcapng"),
            "fifo_path": text("fifo_path") or "./capture_live.fifo",
            "poll_interval": spin("poll_interval"),
        }

    def _apply_form_values(self, data: dict) -> None:
        """Applique un dict de valeurs (issu d'un modèle) sur le formulaire d'ajout.

        Le widget `ssh_password` n'est jamais touché — `data` n'en
        contient de toute façon jamais (voir `save_capture_template`,
        `load_capture_template`), un modèle importé exige toujours de
        ressaisir le mot de passe manuellement. Idem pour `slot`/`model`/
        `feature_bin_path` : plus des champs de ce formulaire (page
        Préférences, features.md point 1) — silencieusement ignorés s'ils
        sont présents dans `data` (ex: modèle enregistré avant ce
        changement).

        Args:
            data: dict key -> valeur, mêmes clés que les champs de
                `Config` (les clés absentes ou inconnues sont ignorées).
        """
        text_keys = (
            "switch_ip",
            "ssh_user",
            "capture_label",
            "feature_bin_dir",
            "mount_point",
            "ntp_server",
            "capture_interface",
            "capture_basename",
            "capture_filter",
            "tap_interface",
            "spool_dir",
            "archive_dir",
            "fifo_path",
        )
        for key in text_keys:
            if key in data:
                self._entries[key].set_text(data[key] or "")

        spin_keys = (
            "rotation_seconds",
            "max_ring_files",
            "rpcap_port",
            "poll_interval",
            "tap_pace_max_gap_seconds",
        )
        for key in spin_keys:
            if key in data and data[key] is not None:
                self._entries[key].set_value(float(data[key]))

        check_keys = (
            "ensure_ntp",
            "tap_cleanup_on_stop",
            "tap_pace_playback",
            "hide_capture_traffic",
            "archive_as_pcapng",
            "tap_launch_wireshark",
        )
        for key in check_keys:
            if key in data:
                self._entries[key].set_active(bool(data[key]))

        if data.get("transfer_mode") in self._transfer_mode_options:
            self._entries["transfer_mode"].set_selected(self._transfer_mode_options.index(data["transfer_mode"]))
        if data.get("output_mode") in self._output_mode_options:
            self._entries["output_mode"].set_selected(self._output_mode_options.index(data["output_mode"]))
        if data.get("capture_direction") in self._capture_direction_options:
            self._entries["capture_direction"].set_selected(
                self._capture_direction_options.index(data["capture_direction"])
            )

        self._apply_transfer_mode_visibility()
        self._apply_output_mode_visibility()

    def _on_save_template(self, _button: Gtk.Button) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.NONE,
            text=_("Enregistrer comme modèle"),
            secondary_text=_("Nom du modèle (le mot de passe SSH n'est jamais enregistré) :"),
        )
        dialog.add_button(_("Annuler"), Gtk.ResponseType.CANCEL)
        dialog.add_button(_("Enregistrer"), Gtk.ResponseType.OK)
        name_entry = Gtk.Entry(placeholder_text=_("ex: labo-5130-client"))
        dialog.get_message_area().append(name_entry)

        def on_response(dlg: Gtk.MessageDialog, response: int) -> None:
            name = name_entry.get_text()
            dlg.destroy()
            if response != Gtk.ResponseType.OK:
                return
            try:
                values = self._collect_raw_form_values()
                target = save_capture_template(DEFAULT_MODELS_DIR, name, values)
            except ValueError as exc:
                self._show_dialog(_("Échec de l'enregistrement"), str(exc))
                return
            self._set_journal_status(f"Modèle enregistré : {target}")

        dialog.connect("response", on_response)
        dialog.show()

    def _on_load_template(self, _button: Gtk.Button) -> None:
        names = list_capture_templates(DEFAULT_MODELS_DIR)
        if not names:
            self._show_dialog(
                _("Aucun modèle"),
                _("Aucun modèle trouvé dans {dir}/. Utilisez d'abord « Enregistrer comme modèle ».").format(
                    dir=DEFAULT_MODELS_DIR
                ),
            )
            return

        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.NONE,
            text=_("Importer un modèle"),
            secondary_text=_("Le mot de passe SSH n'est jamais enregistré : ressaisissez-le après l'import."),
        )
        dialog.add_button(_("Annuler"), Gtk.ResponseType.CANCEL)
        dialog.add_button(_("Importer"), Gtk.ResponseType.OK)
        dropdown = Gtk.DropDown.new_from_strings(names)
        dialog.get_message_area().append(dropdown)

        def on_response(dlg: Gtk.MessageDialog, response: int) -> None:
            idx = dropdown.get_selected()
            dlg.destroy()
            if response != Gtk.ResponseType.OK:
                return
            name = names[idx]
            try:
                data = load_capture_template(DEFAULT_MODELS_DIR, name)
            except (FileNotFoundError, OSError) as exc:
                logger.exception("chargement du modèle {} | échec", name)
                self._show_dialog(_("Échec de l'import"), str(exc))
                return
            self._apply_form_values(data)
            self._set_journal_status(f"Modèle « {name} » importé dans le formulaire.")

        dialog.connect("response", on_response)
        dialog.show()

    # ------------------------------------------------------------------ #
    # Page 2 : Installation (préalable obligatoire à toute capture)
    # ------------------------------------------------------------------ #
    def _build_install_page(self) -> Gtk.Widget:
        """Construit la page Installation.

        Returns:
            Le widget racine de la page.
        """
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=10,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )

        hint = Gtk.Label(
            label=_(
                "Prépare toutes les captures de la liste (modèle, SCP/sshfs, NTP, feature). "
                "Aucune capture ne peut démarrer tant que cette étape n'est pas terminée pour toutes."
            ),
            xalign=0,
            wrap=True,
        )
        hint.add_css_class("dim-label")
        box.append(hint)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._btn_install = Gtk.Button(label=_("Lancer l'installation de toutes les captures"))
        self._btn_install.add_css_class("suggested-action")
        self._btn_install.connect("clicked", self._on_install_all)
        btn_row.append(self._btn_install)
        box.append(btn_row)

        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_overlay_scrolling(False)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._install_list = Gtk.ListBox()
        self._install_list.set_selection_mode(Gtk.SelectionMode.NONE)
        scroller.set_child(self._install_list)
        box.append(scroller)

        return box

    def _refresh_install_list(self) -> None:
        any_running = any(s.capture_running for s in self._sessions)
        self._btn_install.set_sensitive(not any_running)
        self._btn_install.set_tooltip_text(
            "Une capture est en cours : arrêtez-la avant de relancer une installation." if any_running else None,
        )

        self._clear_listbox(self._install_list)
        if not self._sessions:
            row = Gtk.ListBoxRow()
            row.set_child(Gtk.Label(label=_("Aucune capture à installer."), xalign=0, margin_top=6, margin_bottom=6))
            self._install_list.append(row)
            return

        status_labels = {
            "pending": "en attente",
            "running": "installation en cours...",
            "ok": "prête",
            "failed": "échec",
        }
        for session in self._sessions:
            row_box = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL,
                spacing=8,
                margin_top=4,
                margin_bottom=4,
                margin_start=8,
                margin_end=8,
            )
            row_box.append(Gtk.Label(label=session.label, xalign=0, hexpand=True))
            status_text = status_labels.get(session.install_status, session.install_status)
            if session.install_status == "failed" and session.install_error:
                status_text += f" ({session.install_error})"
            status_label = Gtk.Label(label=status_text, xalign=1)
            if session.install_status == "ok":
                status_label.add_css_class("success")
            elif session.install_status == "failed":
                status_label.add_css_class("error")
            row_box.append(status_label)
            row = Gtk.ListBoxRow()
            row.set_child(row_box)
            self._install_list.append(row)

    def _on_install_all(self, _button: Gtk.Button) -> None:
        running = [s for s in self._sessions if s.capture_running]
        if running:
            self._show_dialog(
                _("Installation impossible"),
                _(
                    "Une capture est déjà en cours ({count}). Arrêtez-la (page « Journal ») "
                    "avant de lancer une nouvelle installation."
                ).format(count=", ".join(s.label for s in running)),
            )
            return

        pending = [s for s in self._sessions if s.install_status in ("pending", "failed")]
        if not pending:
            self._show_dialog(_("Rien à installer"), _("Toutes les captures sont déjà prêtes (ou la liste est vide)."))
            return

        for session in pending:
            session.install_status = "running"
            self._start_prepare(session)
        self._refresh_install_list()

    def _start_prepare(self, session: CaptureSession) -> None:
        def worker() -> None:
            try:
                session.setup.prepare()
                session.install_status = "ok"
            except Exception as exc:  # noqa: BLE001
                logger.exception("install | échec pour {label}", label=session.label)
                session.install_status = "failed"
                session.install_error = str(exc)
            GLib.idle_add(self._refresh_install_list)
            GLib.idle_add(self._refresh_start_list)

        threading.Thread(target=worker, daemon=True, name=f"install-{session.id}").start()

    # ------------------------------------------------------------------ #
    # Page 3 : Démarrage (gated par l'installation complète)
    # ------------------------------------------------------------------ #
    def _build_start_page(self) -> Gtk.Widget:
        """Construit la page Démarrage.

        Returns:
            Le widget racine de la page.
        """
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=10,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )

        hint = Gtk.Label(
            label=_("Disponible une fois toutes les captures installées avec succès (page Installation)."),
            xalign=0,
            wrap=True,
        )
        hint.add_css_class("dim-label")
        box.append(hint)

        self._btn_start_all = Gtk.Button(label=_("Démarrer toutes les captures"))
        self._btn_start_all.add_css_class("suggested-action")
        self._btn_start_all.set_sensitive(False)
        self._btn_start_all.connect("clicked", self._on_start_all)
        box.append(self._btn_start_all)

        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_overlay_scrolling(False)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._start_list = Gtk.ListBox()
        self._start_list.set_selection_mode(Gtk.SelectionMode.NONE)
        scroller.set_child(self._start_list)
        box.append(scroller)

        return box

    def _refresh_start_list(self) -> None:
        self._clear_listbox(self._start_list)
        if not self._sessions:
            row = Gtk.ListBoxRow()
            row.set_child(Gtk.Label(label=_("Aucune capture."), xalign=0, margin_top=6, margin_bottom=6))
            self._start_list.append(row)
            self._btn_start_all.set_sensitive(False)
            return

        for session in self._sessions:
            row_box = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL,
                spacing=8,
                margin_top=4,
                margin_bottom=4,
                margin_start=8,
                margin_end=8,
            )
            row_box.append(Gtk.Label(label=session.label, xalign=0, hexpand=True))
            state_text = _("en cours") if session.capture_running else session.install_status
            row_box.append(Gtk.Label(label=state_text, xalign=1))
            row = Gtk.ListBoxRow()
            row.set_child(row_box)
            self._start_list.append(row)

        all_ready = all(s.install_status == "ok" for s in self._sessions)
        none_running = not any(s.capture_running for s in self._sessions)
        self._btn_start_all.set_sensitive(all_ready and none_running)

    def _on_start_all(self, _button: Gtk.Button) -> None:
        ready = [s for s in self._sessions if s.install_status == "ok" and not s.capture_running]
        if not ready:
            return

        for session in ready:
            if session.cfg.output_mode != "rpcap":
                session.rotation = CaptureRotationThread(session.cfg, session.state)
                session.rotation.start()
            threading.Thread(
                target=session.setup.start_capture_blocking,
                daemon=True,
                name=f"capture-{session.id}",
            ).start()
            session.capture_running = True

        self._refresh_start_list()
        self._refresh_install_list()
        self._set_journal_status(f"{len(ready)} capture(s) démarrée(s).")
        self._stack.set_visible_child_name("journal")

    # ------------------------------------------------------------------ #
    # Page 4 : Journal (logs + progression + arrêt global)
    # ------------------------------------------------------------------ #
    def _build_journal_page(self) -> Gtk.Widget:
        """Construit la page Journal.

        Returns:
            Le widget racine de la page.
        """
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=10,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )

        top_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._journal_status = Gtk.Label(label=_("Aucune capture en cours."), xalign=0, hexpand=True)
        top_row.append(self._journal_status)
        self._btn_stop_all = Gtk.Button(label=_("Arrêter toutes les captures"))
        self._btn_stop_all.add_css_class("destructive-action")
        self._btn_stop_all.connect("clicked", self._on_stop_all)
        top_row.append(self._btn_stop_all)
        box.append(top_row)

        progress_scroller = Gtk.ScrolledWindow(min_content_height=140, max_content_height=220)
        progress_scroller.set_overlay_scrolling(False)
        progress_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._progress_list = Gtk.ListBox()
        self._progress_list.set_selection_mode(Gtk.SelectionMode.NONE)
        progress_scroller.set_child(self._progress_list)
        box.append(progress_scroller)

        box.append(Gtk.Separator())
        box.append(Gtk.Label(label=_("<b>Logs</b>"), use_markup=True, xalign=0))

        log_scroller = Gtk.ScrolledWindow(vexpand=True)
        log_scroller.set_overlay_scrolling(False)
        log_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._log_view = Gtk.TextView(editable=False, monospace=True)
        self._log_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._log_buffer = self._log_view.get_buffer()
        log_scroller.set_child(self._log_view)
        box.append(log_scroller)

        return box

    def _set_journal_status(self, text: str) -> None:
        self._journal_status.set_label(text)

    def _on_stop_all(self, _button: Gtk.Button) -> None:
        running = [s for s in self._sessions if s.capture_running]
        if not running:
            self._set_journal_status("Aucune capture en cours à arrêter.")
            return
        for session in running:
            session.state.stop_event.set()
        self._set_journal_status(f"Arrêt de {len(running)} capture(s) en cours ...")

    def _refresh_journal(self) -> bool:
        """Rafraîchit la liste de progression par session (appelé par GLib).

        Returns:
            True pour que GLib continue d'appeler ce callback.
        """
        self._clear_listbox(self._progress_list)
        active_count = 0
        for session in self._sessions:
            if not session.capture_running:
                continue
            still_running = session.setup.is_alive() or (session.rotation is not None and session.rotation.is_alive())
            if still_running:
                active_count += 1
            elif session.capture_running:
                session.capture_running = False

            row_box = Gtk.Box(
                orientation=Gtk.Orientation.HORIZONTAL,
                spacing=12,
                margin_top=4,
                margin_bottom=4,
                margin_start=8,
                margin_end=8,
            )
            row_box.append(Gtk.Label(label=session.label, xalign=0, hexpand=True))
            if session.cfg.output_mode == "rpcap":
                detail = _("streaming réseau direct (rpcap)")
            else:
                rate = compute_average_throughput(session.state.bytes_merged, session.state.started_at, time.time())
                detail = (
                    f"{session.state.files_merged} fichier(s), {format_size(session.state.bytes_merged)}"
                    f" — {format_transfer_rate(rate)}"
                )
            # Issue #70 : dernier palier SCP publié par le thread de
            # transfert dans l'état partagé ; lu ici, sur le thread GTK, à
            # chaque rafraîchissement (1 s) — aucun appel GTK hors thread.
            scp_text = format_scp_progress(session.state.scp_progress)
            if scp_text:
                detail = f"{detail} — {scp_text}"
            state_text = _("en cours") if still_running else _("arrêtée")
            row_box.append(Gtk.Label(label=f"{state_text} — {detail}", xalign=1))
            row = Gtk.ListBoxRow()
            row.set_child(row_box)
            self._progress_list.append(row)

        if active_count == 0 and any(not s.capture_running and s.install_status == "ok" for s in self._sessions):
            pass  # rien à forcer : le statut textuel reste géré par _set_journal_status
        self._refresh_start_list()
        self._refresh_install_list()
        return True

    # ------------------------------------------------------------------ #
    # Page 5 : Résultats
    # ------------------------------------------------------------------ #
    def _build_results_page(self) -> Gtk.Widget:
        """Construit la page Résultats.

        Returns:
            Le widget racine de la page.
        """
        box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=10,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )

        header_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._results_summary = Gtk.Label(
            label=_("Aucune capture terminée pour l'instant."),
            xalign=0,
            hexpand=True,
        )
        header_row.append(self._results_summary)
        btn_refresh = Gtk.Button(label=_("Rafraîchir"))
        btn_refresh.connect("clicked", lambda _b: self._refresh_results())
        header_row.append(btn_refresh)
        box.append(header_row)

        results_scroller = Gtk.ScrolledWindow(vexpand=True)
        results_scroller.set_overlay_scrolling(False)
        results_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self._results_list = Gtk.ListBox()
        self._results_list.set_selection_mode(Gtk.SelectionMode.NONE)
        results_scroller.set_child(self._results_list)
        box.append(results_scroller)

        return box

    @staticmethod
    def _clear_listbox(listbox: Gtk.ListBox) -> None:
        child = listbox.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            listbox.remove(child)
            child = next_child

    def _refresh_results(self) -> None:
        """Reliste les .pcap de spool_dir/archive_dir de toutes les sessions."""
        self._clear_listbox(self._results_list)

        total_files = 0
        total_bytes = 0
        for session in self._sessions:
            candidates = []
            spool = session.cfg.spool_dir
            archive = session.cfg.archive_dir
            for kind, path in (("Spool", spool), ("Archive", archive)):
                if path and Path(path).is_dir():
                    candidates.append((kind, Path(path)))

            for kind, dir_path in candidates:
                for pcap_file in sorted(dir_path.glob("*.pcap")):
                    try:
                        st = pcap_file.stat()
                    except OSError:
                        continue
                    total_files += 1
                    total_bytes += st.st_size

                    row_box = Gtk.Box(
                        orientation=Gtk.Orientation.HORIZONTAL,
                        spacing=12,
                        margin_top=4,
                        margin_bottom=4,
                        margin_start=8,
                        margin_end=8,
                    )
                    tag = Gtk.Label(label=f"[{session.cfg.capture_label or session.cfg.switch_ip}/{kind}]", xalign=0)
                    tag.set_ellipsize(Pango.EllipsizeMode.END)
                    tag.set_max_width_chars(24)
                    row_box.append(tag)
                    filename_label = Gtk.Label(label=pcap_file.name, hexpand=True, xalign=0)
                    filename_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
                    row_box.append(filename_label)
                    row_box.append(Gtk.Label(label=format_size(st.st_size), xalign=1))
                    row = Gtk.ListBoxRow()
                    row.set_child(row_box)
                    self._results_list.append(row)

        if total_files:
            self._results_summary.set_label(f"{total_files} fichier(s), {format_size(total_bytes)} au total")
        else:
            self._results_summary.set_label("Aucun fichier .pcap trouvé pour l'instant.")

    # ------------------------------------------------------------------ #
    # Fermeture / utilitaires UI
    # ------------------------------------------------------------------ #
    def _on_close_request(self, _window: Gtk.ApplicationWindow) -> bool:
        for session in self._sessions:
            if session.capture_running:
                session.state.stop_event.set()
        if self._prefs_window is not None:
            self._prefs_window.destroy()
            self._prefs_window = None
        return False

    def _show_dialog(self, title: str, body: str) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=title,
            secondary_text=body,
        )
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.show()

    def _drain_log_queue(self) -> bool:
        """Vide LOG_QUEUE dans la console de logs (appelé périodiquement par GLib).

        Returns:
            True pour que GLib continue d'appeler ce callback.
        """
        end_iter = self._log_buffer.get_end_iter()
        drained = False
        while True:
            try:
                line = LOG_QUEUE.get_nowait()
            except queue.Empty:
                break
            self._log_buffer.insert(end_iter, line + "\n")
            drained = True
        if drained:
            mark = self._log_buffer.create_mark(None, self._log_buffer.get_end_iter(), False)
            self._log_view.scroll_to_mark(mark, 0.0, False, 0.0, 0.0)
        return True


# Marqueur exact du message levé par l'override PyGObject de Gtk.Window
# quand gtk_init_check() a échoué en amont (ex. affichage X11/Wayland
# inaccessible) — voir gi/overrides/Gtk.py dans PyGObject. Sert à isoler
# précisément CE cas dans do_activate, sans masquer sous ce diagnostic un
# RuntimeError différent qui surviendrait par ailleurs dans la
# construction de CaptureWindow.
_DISPLAY_INIT_ERROR_MARKER = "Gtk couldn't be initialized"


def _print_display_error(exc: Exception) -> None:
    """Affiche un diagnostic actionnable quand GTK4 ne peut pas ouvrir l'affichage.

    Cas le plus fréquent, reproduit et confirmé lors du diagnostic de ce
    message : lancement via `sudo` (nécessaire pour le mode tap, qui a
    besoin de root/CAP_NET_ADMIN — voir CLAUDE.md) sur une session
    graphique en RDP (xrdp). `sudo` réinitialise HOME par défaut (et donc
    XAUTHORITY) : root ne trouve alors plus le cookie d'autorisation X11
    de la session en cours — et contrairement à certaines sessions
    console locales, une session xrdp n'accorde pas automatiquement à
    root l'accès au serveur X (pas de xhost implicite). D'où l'écart
    observé entre « marche sans sudo » et « échoue avec sudo, uniquement
    en RDP ». Voir aussi USAGE.md, section « Dépannage ».
    """
    sys.stderr.write(
        "\nImpossible d'ouvrir la fenêtre : GTK4 n'a pas pu se connecter à "
        "l'affichage graphique (X11/Wayland).\n"
        f"Erreur d'origine : {exc}\n\n"
    )
    if os.geteuid() == 0:
        sys.stderr.write(
            "Cause la plus probable : lancement avec sudo (ou en tant que "
            "root) sur une session distante (RDP/xrdp notamment). sudo "
            "réinitialise HOME par défaut, donc XAUTHORITY — root ne trouve "
            "alors plus le cookie d'autorisation X11 de votre session "
            "graphique.\n\n"
            "Solutions, de la plus simple à la plus propre :\n"
            "  1. Autoriser root une fois, avant sudo (à exécuter en tant\n"
            "     qu'utilisateur normal, PAS avec sudo) :\n"
            "       xhost +si:localuser:root\n"
            "       sudo ./switch-capture\n"
            "  2. Transmettre explicitement DISPLAY/XAUTHORITY à sudo :\n"
            "       sudo --preserve-env=DISPLAY,XAUTHORITY ./switch-capture\n"
            "  3. Si seul le mode tap en ligne de commande est nécessaire,\n"
            "     pas la fenêtre : la CLI seule n'a pas ce problème (aucun\n"
            "     accès X11 requis) :\n"
            "       sudo ./switch-capture -c capture --output-mode tap ...\n\n"
            "Détails : USAGE.md, section « Dépannage : sudo + fenêtre + RDP ».\n"
        )
    else:
        sys.stderr.write(
            "Vérifiez que DISPLAY (et XAUTHORITY si nécessaire) sont bien "
            "définis pour cette session, et que le serveur X/Wayland est "
            "accessible.\n"
        )


class CaptureApp(Gtk.Application):
    """Application GTK4 minimale hébergeant CaptureWindow."""

    def __init__(self) -> None:
        super().__init__(application_id=APP_ID)
        # Positionné à 1 par do_activate si l'affichage graphique n'a pas pu
        # être ouvert — voir _print_display_error. Consulté par main().
        self.exit_code = 0
        # Renseignés par do_activate une fois la fenêtre créée avec succès
        # (jamais dans le cas d'échec d'affichage ci-dessus, seul cas où ils
        # restent à None) — voir _install_sigint_handler/_on_sigint.
        self._window: CaptureWindow | None = None
        self._sigint_source_id: int | None = None

    def do_activate(self) -> None:
        _register_app_icon()
        try:
            window = CaptureWindow(self)
        except RuntimeError as exc:
            if _DISPLAY_INIT_ERROR_MARKER not in str(exc):
                raise  # autre bug : ne pas le masquer sous ce diagnostic
            self.exit_code = 1
            _print_display_error(exc)
            self.quit()
            return
        self._window = window
        self._install_sigint_handler()
        window.present()

    def _install_sigint_handler(self) -> None:
        """Intercepte Ctrl+C (SIGINT) proprement, via la boucle GLib plutôt
        que `signal.signal` (features.md, point 10, reformulé le
        28/08/2026 : « Ctrl+C remonte toujours un Traceback/
        KeyboardInterrupt brut au lieu d'une sortie propre »).

        Le gestionnaire Python standard (`signal.signal`, déjà utilisé côté
        CLI dans `run_capture` — voir switch_capture_cli.py) ne s'exécute
        qu'au retour à la boucle d'évaluation de bytecode. Or tant que
        `Gtk.Application.run()` tourne, le contrôle reste dans la boucle
        événementielle GLib (implémentée en C), qui ne rend la main à
        l'interpréteur Python que ponctuellement, via les callbacks déjà en
        place (`GLib.timeout_add(_drain_log_queue)`,
        `GLib.timeout_add(_refresh_journal)`, ...). En pratique, Ctrl+C
        finissait par lever un `KeyboardInterrupt` brut à l'intérieur d'un
        de ces callbacks, sans jamais passer par `_on_close_request` — d'où
        le traceback observé plutôt qu'une fermeture propre.

        `GLib.unix_signal_add()` s'intègre nativement à cette même boucle
        (source GLib dédiée, indépendante du mécanisme `signal` de Python) :
        Ctrl+C déclenche alors `_on_sigint` dans le contexte normal de la
        boucle événementielle, exactement comme n'importe quel autre
        callback GLib déjà présent dans ce fichier — plus de traceback.

        Idempotent (`_sigint_source_id` évite d'empiler une deuxième source
        si `do_activate` était un jour appelé plus d'une fois, ex.
        réactivation D-Bus d'une instance déjà lancée).
        """
        if self._sigint_source_id is not None:
            return
        self._sigint_source_id = GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self._on_sigint)

    def _on_sigint(self) -> bool:
        """Callback GLib déclenché par Ctrl+C (voir _install_sigint_handler).

        Ferme la fenêtre principale exactement comme le ferait un clic sur
        son bouton de fermeture natif ou sur « Quitter » du menu hamburger
        (`self.close()` sur la fenêtre → signal `close-request` déjà
        connecté → `_on_close_request`, qui arrête proprement les captures
        en cours et ferme la fenêtre Préférences si elle est ouverte) —
        même chemin de fermeture partout, pas de logique dupliquée ici
        (même principe que l'action `win.quit-app`, voir
        CaptureWindow.__init__). La fenêtre étant la seule que
        `CaptureApp` possède, sa fermeture met fin à `Gtk.Application.run()`
        sans appel explicite à `self.quit()` (même mécanisme, déjà en place,
        que pour la fermeture par la souris).

        Returns:
            False (`GLib.SOURCE_REMOVE`) : ce callback n'a besoin de
            s'exécuter qu'une fois, la fermeture étant déjà engagée dès le
            premier Ctrl+C.
        """
        logger.info("gtk | Ctrl+C reçu, fermeture propre en cours ...")
        if self._window is not None:
            self._window.close()
        return False


def main() -> int:
    """Point d'entrée de l'app GTK4.

    Returns:
        Code de sortie du processus : 1 si l'affichage graphique n'a pas pu
        être ouvert (voir CaptureApp.do_activate/_print_display_error —
        Gtk.Application.run() retournerait 0 dans ce cas malgré l'échec,
        d'où ce contrôle explicite), sinon le code retourné par
        Gtk.Application.run().
    """
    app = CaptureApp()
    run_result = app.run(sys.argv[:1])
    return app.exit_code or run_result


if __name__ == "__main__":
    sys.exit(main())
