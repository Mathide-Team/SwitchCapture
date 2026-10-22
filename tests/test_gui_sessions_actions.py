"""Tests GTK4 des actions de la fenêtre principale (issue #86).

Sessions (ajout, modification, suppression, inspection, test de connexion),
mémorisation du mot de passe, installation, démarrage et arrêt, journal,
résultats, modèles de formulaire et fermeture — sur une vraie
`CaptureWindow` (Xvfb), avec de vrais `Gtk.ListBox`.

Seuls les effets de bord externes sont remplacés : connexion SSH au switch
(`connect_switch`, `inspect_switch`), threads de capture/installation, et
`threading.Thread`/`GLib.idle_add` du module GTK rendus synchrones pour que
chaque test observe le résultat sans boucle d'évènements. Même politique de
saut que les autres `test_gui_*` (pas de PyGObject ou pas d'affichage).
"""

from __future__ import annotations

import types
from pathlib import Path
from typing import ClassVar

import pytest
from conftest import require_gtk4

gi = require_gtk4()

from gi.repository import GLib, Gtk
from test_model_detection import VERSION_5130EI

import switch_capture_core as core
import switch_capture_gtk as gtk_app


class _ThreadSynchrone:
    """Remplace `threading.Thread` du module GTK : `start()` exécute la cible tout de suite."""

    lances: ClassVar[list[str]] = []

    def __init__(self, target=None, daemon=None, name=None, args=(), kwargs=None) -> None:
        self._target, self._args, self._kwargs, self.name = target, args, kwargs or {}, name

    def start(self) -> None:
        _ThreadSynchrone.lances.append(self.name or "")
        self._target(*self._args, **self._kwargs)


class _GLibIdleImmediat:
    """Vrai GLib, sauf `idle_add` qui exécute la fonction tout de suite."""

    @staticmethod
    def idle_add(fonction, *args):
        fonction(*args)

    def __getattr__(self, nom: str):
        return getattr(GLib, nom)


@pytest.fixture
def win(tmp_path, monkeypatch):
    monkeypatch.setattr(gtk_app, "DEFAULT_PREFS_CONFIG_PATH", str(tmp_path / "config.yaml"))
    app = Gtk.Application(application_id="org.transcende.switch_capture.tests.sessions")
    holder: dict = {}

    def on_activate(a):
        try:
            holder["win"] = gtk_app.CaptureWindow(a)
        except RuntimeError as exc:
            holder["error"] = exc
        a.quit()

    app.connect("activate", on_activate)
    app.run([])
    if "error" in holder:
        pytest.skip(f"pas d'affichage graphique disponible : {holder['error']}")
    fenetre = holder["win"]

    _ThreadSynchrone.lances = []
    monkeypatch.setattr(gtk_app, "threading", types.SimpleNamespace(Thread=_ThreadSynchrone))
    monkeypatch.setattr(gtk_app, "GLib", _GLibIdleImmediat())
    fenetre.dialogues = []
    monkeypatch.setattr(fenetre, "_show_dialog", lambda titre, corps: fenetre.dialogues.append((titre, corps)))
    return fenetre


def _remplir(win, switch_ip: str = "10.0.0.1") -> None:
    win._entries["switch_ip"].set_text(switch_ip)
    win._entries["ssh_user"].set_text("mathilde")
    win._entries["ssh_password"].set_text("secret")
    win._entries["capture_interface"].set_text("GigabitEthernet1/0/1")


def _textes(listbox: Gtk.ListBox) -> list[str]:
    """Libellés de chaque ligne d'un Gtk.ListBox (hors boutons), joints par « | »."""
    lignes = []
    ligne = listbox.get_first_child()
    while ligne is not None:
        morceaux = []
        pile = [ligne]
        while pile:
            widget = pile.pop()
            if isinstance(widget, Gtk.Label):
                morceaux.append(widget.get_label())
            if isinstance(widget, Gtk.Button):
                continue
            enfant = widget.get_last_child()
            while enfant is not None:
                pile.append(enfant)
                enfant = enfant.get_prev_sibling()
        lignes.append(" | ".join(morceaux))
        ligne = ligne.get_next_sibling()
    return lignes


def _boutons(listbox: Gtk.ListBox, rang: int) -> dict[str, Gtk.Button]:
    ligne = listbox.get_row_at_index(rang)
    boite = ligne.get_child()
    boutons = {}
    enfant = boite.get_first_child()
    while enfant is not None:
        if isinstance(enfant, Gtk.Button):
            boutons[enfant.get_label()] = enfant
        enfant = enfant.get_next_sibling()
    return boutons


def _ajouter(win, switch_ip: str = "10.0.0.1"):
    _remplir(win, switch_ip)
    win._on_add_session(None)
    return win._sessions[-1]


# ───────────────────────────── sessions ─────────────────────────────


class TestSessions:
    def test_liste_vide_puis_ajout(self, win) -> None:
        win._refresh_sessions_list()
        assert _textes(win._sessions_list) == ["Aucune capture ajoutée pour l'instant."]
        session = _ajouter(win)
        assert _textes(win._sessions_list) == [session.label]
        assert win._journal_status.get_label() == f"Capture ajoutée : {session.label}"
        assert set(_boutons(win._sessions_list, 0)) == {
            "Inspecter (dry run)",
            "Désinstaller la feature",
            "Modifier",
            "Supprimer",
        }

    def test_ajout_formulaire_incomplet(self, win) -> None:
        win._on_add_session(None)
        assert win._sessions == []
        assert win.dialogues[0][0] == "Configuration incomplète"

    def test_supprimer_par_le_bouton(self, win) -> None:
        _ajouter(win)
        _boutons(win._sessions_list, 0)["Supprimer"].emit("clicked")
        assert win._sessions == []
        assert _textes(win._sessions_list) == ["Aucune capture ajoutée pour l'instant."]

    def test_supprimer_une_session_deja_retiree(self, win) -> None:
        session = _ajouter(win)
        win._sessions.clear()
        win._on_remove_session(None, session)
        assert win._sessions == []

    def test_modifier_recharge_le_formulaire(self, win) -> None:
        session = _ajouter(win, "10.0.0.9")
        _remplir(win, "192.0.2.1")
        win._entries["ssh_password"].set_text("")
        _boutons(win._sessions_list, 0)["Modifier"].emit("clicked")
        assert win._sessions == []
        assert win._entries["switch_ip"].get_text() == "10.0.0.9"
        assert win._entries["ssh_password"].get_text() == "secret"
        assert win._stack.get_visible_child_name() == "config"
        assert win._prefs["slot"] == session.cfg.slot
        assert "chargée dans le formulaire" in win._journal_status.get_label()

    def test_modifier_ignore_une_capture_en_cours(self, win) -> None:
        session = _ajouter(win)
        session.capture_running = True
        win._refresh_sessions_list()
        assert _boutons(win._sessions_list, 0)["Modifier"].get_sensitive() is False
        win._on_edit_session(None, session)
        assert win._sessions == [session]

    @pytest.mark.parametrize("deja_retiree", [False, True])
    def test_modifier_session_absente_de_la_liste(self, win, deja_retiree: bool) -> None:
        session = _ajouter(win)
        if deja_retiree:
            win._sessions.clear()
        win._on_edit_session(None, session)
        assert win._sessions == []


class TestInspectionEtTestConnexion:
    def test_inspection_reussie(self, win, monkeypatch) -> None:
        session = _ajouter(win)
        vus = []
        monkeypatch.setattr(gtk_app, "inspect_switch", lambda cfg: vus.append(cfg) or {"rapport": 1})
        monkeypatch.setattr(gtk_app, "format_inspect_report", lambda ip, mode, rapport: f"{ip}/{mode}/{rapport}")
        _boutons(win._sessions_list, 0)["Inspecter (dry run)"].emit("clicked")
        assert vus[0].switch_ip == "10.0.0.1" and vus[0].ssh_password == "secret"
        assert win.dialogues == [("Inspection de 10.0.0.1", f"10.0.0.1/{session.cfg.transfer_mode}/{{'rapport': 1}}")]
        assert win._journal_status.get_label() == f"Inspection terminée pour {session.label}"
        assert _ThreadSynchrone.lances == [f"inspect-{session.id}"]

    def test_inspection_en_echec(self, win, monkeypatch) -> None:
        session = _ajouter(win)

        def panne(cfg):
            raise ConnectionError("switch injoignable")

        monkeypatch.setattr(gtk_app, "inspect_switch", panne)
        win._on_inspect_session(None, session)
        assert win.dialogues == [("Échec de l'inspection", "switch injoignable")]
        assert win._journal_status.get_label() == f"Inspection en échec pour {session.label} : switch injoignable"

    def test_connexion_reussie_modele_et_version(self, win, monkeypatch) -> None:
        commandes, fermetures = [], []

        class Connexion:
            def send_command(self, commande):
                commandes.append(commande)
                return VERSION_5130EI

            def disconnect(self):
                fermetures.append(True)

        monkeypatch.setattr(core, "connect_switch", lambda cfg: Connexion())
        _remplir(win)
        win._on_test_connection(None)
        assert commandes == ["display version"] and fermetures == [True]
        titre, message = win.dialogues[0]
        assert titre == "Connexion réussie"
        assert message == "Connexion OK — modèle détecté : 5130EI, version : 6555P05"

    def test_connexion_modele_inconnu(self, win, monkeypatch) -> None:
        class Connexion:
            def send_command(self, commande):
                return "rien d'identifiable"

            def disconnect(self):
                pass

        monkeypatch.setattr(core, "connect_switch", lambda cfg: Connexion())
        _remplir(win)
        win._on_test_connection(None)
        assert win.dialogues == [("Connexion réussie", "Connexion OK — modèle détecté : non reconnu, version : ?")]

    def test_connexion_deconnecte_meme_si_la_commande_echoue(self, win, monkeypatch) -> None:
        fermetures = []

        class Connexion:
            def send_command(self, commande):
                raise TimeoutError("pas de réponse")

            def disconnect(self):
                fermetures.append(True)

        monkeypatch.setattr(core, "connect_switch", lambda cfg: Connexion())
        _remplir(win)
        win._on_test_connection(None)
        assert fermetures == [True]
        assert win.dialogues == [("Échec de la connexion", "pas de réponse")]

    def test_connexion_formulaire_incomplet(self, win) -> None:
        win._on_test_connection(None)
        assert win.dialogues[0][0] == "Configuration incomplète"
        assert _ThreadSynchrone.lances == []


class TestMemorisationMotDePasse:
    def test_case_non_cochee(self, win, monkeypatch) -> None:
        monkeypatch.setattr(gtk_app, "save_ssh_password_to_keyring", lambda *a: pytest.fail("ne doit pas mémoriser"))
        _ajouter(win)
        assert _ThreadSynchrone.lances == []

    def test_trousseau(self, win, monkeypatch) -> None:
        enregistres = []
        monkeypatch.setattr(gtk_app, "KEYRING_AVAILABLE", True)
        monkeypatch.setattr(gtk_app, "save_ssh_password_to_keyring", lambda *a: enregistres.append(a))
        win._entries["remember_password"].set_active(True)
        _ajouter(win)
        assert enregistres == [("10.0.0.1", "mathilde", "secret")]
        assert win.dialogues == []

    def test_trousseau_verrouille_signale(self, win, monkeypatch) -> None:
        def verrouille(*a):
            raise RuntimeError("trousseau verrouillé")

        monkeypatch.setattr(gtk_app, "KEYRING_AVAILABLE", True)
        monkeypatch.setattr(gtk_app, "save_ssh_password_to_keyring", verrouille)
        win._entries["remember_password"].set_active(True)
        _ajouter(win)
        assert win.dialogues == [("Échec de la mémorisation", "trousseau verrouillé")]

    def test_keepass_en_echec_signale(self, win, monkeypatch) -> None:
        def illisible(*a):
            raise RuntimeError("mot de passe maître incorrect")

        monkeypatch.setattr(gtk_app, "KEYRING_AVAILABLE", False)
        monkeypatch.setattr(gtk_app, "KEEPASS_AVAILABLE", True)
        monkeypatch.setenv("SWITCH_CAPTURE_KEEPASS_PASSWORD", "maitre")
        monkeypatch.setattr(gtk_app, "save_ssh_password_to_keepass", illisible)
        win._prefs["keepass_path"] = "/tmp/base.kdbx"
        win._entries["remember_password"].set_active(True)
        _ajouter(win)
        assert win.dialogues == [("Échec de la mémorisation (KeePass)", "mot de passe maître incorrect")]


# ─────────────────────── installation, démarrage, arrêt ───────────────────────


class _Setup:
    def __init__(self, erreur: Exception | None = None, vivant: bool = False) -> None:
        self.erreur, self.vivant, self.prepares, self.captures = erreur, vivant, 0, 0

    def prepare(self) -> None:
        self.prepares += 1
        if self.erreur:
            raise self.erreur

    def start_capture_blocking(self) -> None:
        self.captures += 1

    def is_alive(self) -> bool:
        return self.vivant


class TestInstallationDemarrageArret:
    def test_installation_reussie_et_en_echec(self, win) -> None:
        ok, ko = _ajouter(win, "10.0.0.1"), _ajouter(win, "10.0.0.2")
        ok.setup, ko.setup = _Setup(), _Setup(RuntimeError("flash pleine"))
        win._on_install_all(None)
        assert (ok.install_status, ko.install_status) == ("ok", "failed")
        assert ko.install_error == "flash pleine"
        lignes = _textes(win._install_list)
        assert lignes[1].endswith("(flash pleine)")
        assert win._btn_start_all.get_sensitive() is False  # une capture n'est pas prête

    def test_rien_a_installer(self, win) -> None:
        win._on_install_all(None)
        assert win.dialogues[0][0] == "Rien à installer"
        session = _ajouter(win)
        session.install_status = "ok"
        win._on_install_all(None)
        assert [t for t, _ in win.dialogues] == ["Rien à installer", "Rien à installer"]

    def test_installation_refusee_pendant_une_capture(self, win) -> None:
        session = _ajouter(win)
        session.capture_running = True
        win._on_install_all(None)
        assert win.dialogues[0][0] == "Installation impossible"
        assert session.label in win.dialogues[0][1]

    def test_demarrer_toutes(self, win, monkeypatch) -> None:
        rotations = []

        class Rotation:
            def __init__(self, cfg, state):
                rotations.append(cfg.switch_ip)

            def start(self):
                pass

            def is_alive(self):
                return False

        monkeypatch.setattr(gtk_app, "CaptureRotationThread", Rotation)
        fichier, rpcap = _ajouter(win, "10.0.0.1"), _ajouter(win, "10.0.0.2")
        rpcap.cfg.output_mode = "rpcap"
        for session in (fichier, rpcap):
            session.setup, session.install_status = _Setup(), "ok"
        win._refresh_start_list()
        assert win._btn_start_all.get_sensitive() is True
        win._on_start_all(None)
        assert rotations == ["10.0.0.1"]  # pas de rotation de fichiers en rpcap
        assert rpcap.rotation is None
        assert fichier.setup.captures == rpcap.setup.captures == 1
        assert fichier.capture_running and rpcap.capture_running
        assert win._journal_status.get_label() == "2 capture(s) démarrée(s)."
        assert win._stack.get_visible_child_name() == "journal"
        assert win._btn_start_all.get_sensitive() is False
        assert all(texte.endswith("en cours") for texte in _textes(win._start_list))

    def test_demarrer_sans_capture_prete(self, win) -> None:
        _ajouter(win)
        win._on_start_all(None)
        assert win._sessions[0].capture_running is False

    def test_arreter(self, win) -> None:
        win._on_stop_all(None)
        assert win._journal_status.get_label() == "Aucune capture en cours à arrêter."
        active, inactive = _ajouter(win, "10.0.0.1"), _ajouter(win, "10.0.0.2")
        active.capture_running = True
        win._on_stop_all(None)
        assert active.state.stop_event.is_set() and not inactive.state.stop_event.is_set()
        assert win._journal_status.get_label() == "Arrêt de 1 capture(s) en cours ..."

    def test_fermeture_arrete_les_captures_et_les_preferences(self, win) -> None:
        session = _ajouter(win)
        session.capture_running = True
        detruites = []
        win._prefs_window = types.SimpleNamespace(destroy=lambda: detruites.append(True))
        assert win._on_close_request(win) is False
        assert session.state.stop_event.is_set() and detruites == [True]
        assert win._prefs_window is None


class TestJournalEtResultats:
    def test_journal_progression_et_fin_de_capture(self, win) -> None:
        fichier, rpcap, finie = _ajouter(win, "10.0.0.1"), _ajouter(win, "10.0.0.2"), _ajouter(win, "10.0.0.3")
        rpcap.cfg.output_mode = "rpcap"
        fichier.setup, rpcap.setup, finie.setup = _Setup(vivant=True), _Setup(vivant=True), _Setup(vivant=False)
        for session in (fichier, rpcap, finie):
            session.capture_running = True
        fichier.state.files_merged, fichier.state.bytes_merged = 3, 2048
        fichier.state.scp_progress = core.ScpProgress("push", "cap_1.pcap", 50, 512, 1024)
        assert win._refresh_journal() is True
        lignes = _textes(win._progress_list)
        assert len(lignes) == 3
        assert "en cours — 3 fichier(s), 2.0 Ko — " in lignes[0]
        assert lignes[0].endswith("— SCP cap_1.pcap : 50 % (512 o / 1.0 Ko)")
        assert "en cours — streaming réseau direct (rpcap)" in lignes[1]
        assert "arrêtée" in lignes[2]
        assert finie.capture_running is False  # thread terminé : la session repasse à l'arrêt
        win._refresh_journal()
        assert len(_textes(win._progress_list)) == 2

    def test_journal_rotation_encore_active(self, win) -> None:
        session = _ajouter(win)
        session.setup = _Setup(vivant=False)
        session.rotation = types.SimpleNamespace(is_alive=lambda: True)
        session.capture_running = True
        win._refresh_journal()
        assert "en cours" in _textes(win._progress_list)[0] and session.capture_running

    def test_resultats(self, win, tmp_path: Path, monkeypatch) -> None:
        spool, archive = tmp_path / "spool", tmp_path / "archive"
        spool.mkdir()
        archive.mkdir()
        (spool / "b.pcap").write_bytes(b"x" * 1024)
        (archive / "a.pcap").write_bytes(b"x" * 2048)
        (archive / "ignore.txt").write_text("pas un pcap")
        win._refresh_results()
        assert win._results_summary.get_label() == "Aucun fichier .pcap trouvé pour l'instant."
        session = _ajouter(win)
        session.cfg.spool_dir, session.cfg.archive_dir = str(spool), str(archive)
        session.cfg.capture_label = ""
        _ajouter(win, "10.0.0.2").cfg.spool_dir = str(tmp_path / "absent")
        win._refresh_results()
        assert win._results_summary.get_label() == "2 fichier(s), 3.0 Ko au total"
        assert _textes(win._results_list) == [
            "[10.0.0.1/Spool] | b.pcap | 1.0 Ko",
            "[10.0.0.1/Archive] | a.pcap | 2.0 Ko",
        ]

    def test_resultats_fichier_disparu(self, win, tmp_path: Path, monkeypatch) -> None:
        spool = tmp_path / "spool"
        spool.mkdir()
        (spool / "disparu.pcap").write_bytes(b"x")
        session = _ajouter(win)
        session.cfg.spool_dir, session.cfg.archive_dir = str(spool), ""
        vrai_stat = Path.stat

        def stat(self, *args, **kwargs):
            if self.name == "disparu.pcap":
                raise FileNotFoundError(self)
            return vrai_stat(self, *args, **kwargs)

        monkeypatch.setattr(Path, "stat", stat)
        win._refresh_results()
        assert win._results_summary.get_label() == "Aucun fichier .pcap trouvé pour l'instant."


# ───────────────────────────── modèles de formulaire ─────────────────────────────


@pytest.fixture
def formulaire(monkeypatch, tmp_path):
    """Remplace `_open_form_dialog` : mémorise les widgets et la fonction de réponse."""
    monkeypatch.setattr(gtk_app, "DEFAULT_MODELS_DIR", str(tmp_path / "models"))
    ouvert: dict = {}

    def ouvrir(parent, titre, texte, widgets, annuler, valider, on_response):
        ouvert.update(titre=titre, widgets=widgets, repondre=on_response)

    monkeypatch.setattr(gtk_app, "_open_form_dialog", ouvrir)
    return ouvert


class TestModeles:
    def test_enregistrer_puis_importer(self, win, formulaire) -> None:
        _remplir(win, "10.0.0.7")
        win._on_save_template(None)
        assert formulaire["titre"] == "Enregistrer comme modèle"
        formulaire["widgets"][0].set_text("labo")
        formulaire["repondre"](True)
        assert win._journal_status.get_label().startswith("Modèle enregistré : ")
        assert "secret" not in (Path(gtk_app.DEFAULT_MODELS_DIR) / "labo.yaml").read_text()

        _remplir(win, "192.0.2.1")
        win._on_load_template(None)
        assert formulaire["titre"] == "Importer un modèle"
        formulaire["repondre"](True)
        assert win._entries["switch_ip"].get_text() == "10.0.0.7"
        assert win._journal_status.get_label() == "Modèle « labo » importé dans le formulaire."

    def test_enregistrer_annule_ou_nom_invalide(self, win, formulaire) -> None:
        win._on_save_template(None)
        formulaire["repondre"](False)
        assert not Path(gtk_app.DEFAULT_MODELS_DIR).exists()
        formulaire["widgets"][0].set_text("../hors-du-dossier")
        formulaire["repondre"](True)
        assert win.dialogues[0][0] == "Échec de l'enregistrement"

    def test_importer_sans_modele(self, win, formulaire) -> None:
        win._on_load_template(None)
        assert win.dialogues[0][0] == "Aucun modèle"
        assert "titre" not in formulaire

    def test_importer_annule_ou_fichier_disparu(self, win, formulaire) -> None:
        _remplir(win, "10.0.0.7")
        win._on_save_template(None)
        formulaire["widgets"][0].set_text("labo")
        formulaire["repondre"](True)
        win._on_load_template(None)
        formulaire["repondre"](False)
        assert win._entries["switch_ip"].get_text() == "10.0.0.7"
        (Path(gtk_app.DEFAULT_MODELS_DIR) / "labo.yaml").unlink()
        formulaire["repondre"](True)
        assert win.dialogues[0][0] == "Échec de l'import"
