"""Tests des fonctions de transfert SCP (`open_scp_ssh_client`/`scp_get`/
`scp_put`/`list_remote_pcap_files`/`delete_remote_file`/
`delete_remote_all_file_capture`).

Constat de départ (session du 08/09/2026) : malgré les affirmations de
`features.md` sur des vérifications « réelles, pas mockées » contre un
`sshd` local lors de sessions précédentes (correctif du 23/08/2026 sur le
préfixe `flash:` et la réouverture de connexion par fichier), aucune de ces
six fonctions n'apparaissait, même indirectement, dans `tests/` : les
vérifications de l'époque ont visiblement été faites de façon ponctuelle
(scripts jetables contre un `sshd` de session), sans laisser de test
persistant dans la suite. Confirmé par recherche exhaustive (aucune
occurrence de leurs noms, ni de `sshd`/`paramiko`/`SSHClient`, dans aucun
fichier de `tests/` avant ce fichier).

Aucun `sshd` réel ni le paquet `openssh-server` n'étaient installables dans
CE sandbox précis (miroir Ubuntu renvoyant 404 au moment de cette session)
— ces tests utilisent donc le même principe que `test_inspect.py`
(`FakeConn`) pour les deux fonctions basées sur une session netmiko
(`list_remote_pcap_files`/`delete_remote_file`/
`delete_remote_all_file_capture`), et un remplacement in-memory de
`paramiko`/`SCPClient` (mêmes noms de globals que ceux testés à
l'exécution par `open_scp_ssh_client`/`scp_get`/`scp_put` dans
`switch_capture_core.py`) pour les trois fonctions basées sur paramiko —
pas une preuve de bon fonctionnement contre un vrai switch/serveur SCP
(qui reste, comme documenté dans `features.md`, la seule vérification
manquante), mais un filet de non-régression qui n'existait pas du tout
avant cette session : un renommage de paramètre, une inversion
get/put, un mauvais chemin (oubli du retrait du préfixe `flash:`) ou une
régression sur le ré-armement de connexion feraient désormais échouer la
suite au lieu de passer inaperçus jusqu'à un usage réel.
"""

from __future__ import annotations

from typing import ClassVar

import pytest
from loguru import logger

import switch_capture_core as core

# --------------------------------------------------------------------------- #
# open_scp_ssh_client / scp_get / scp_put — couche paramiko
# --------------------------------------------------------------------------- #


class FakeTransport:
    """Objet renvoyé par `get_transport()`, jamais inspecté au-delà de son
    identité (juste transmis tel quel à `SCPClient`)."""


class FakeSSHClient:
    """Remplace `paramiko.SSHClient` : enregistre les appels plutôt que
    d'ouvrir une vraie connexion TCP."""

    def __init__(self):
        self.policy = None
        self.connect_kwargs = None

    def set_missing_host_key_policy(self, policy):
        self.policy = policy

    def connect(self, host, **kwargs):
        self.connect_kwargs = {"host": host, **kwargs}

    def get_transport(self):
        return FakeTransport()


class FakeAutoAddPolicy:
    """Remplace `paramiko.AutoAddPolicy` (jamais instanciée pour de vrai
    dans ces tests, juste vérifiée par type)."""


class FakeParamikoModule:
    """Remplace le global `paramiko` du module `switch_capture_core`."""

    SSHClient = FakeSSHClient
    AutoAddPolicy = FakeAutoAddPolicy


class FakeSCPClient:
    """Remplace `scp.SCPClient` : `get`/`put` enregistrent leurs arguments
    au lieu de toucher le réseau. Utilisable comme context manager, comme
    le fait le vrai `SCPClient` dans `scp_get`/`scp_put`.

    `progress` accepté et mémorisé (jamais appelé par ce faux backend —
    le vrai `scp.SCPClient` l'appellerait pendant le transfert, mais
    aucun octet n'est réellement transféré ici) : suffisant pour vérifier
    que `scp_get`/`scp_put` le transmettent bien à `SCPClient(...)`, ce
    que `make_scp_progress_logger` fait ensuite avec est testé séparément,
    en isolation, sans passer par `SCPClient` du tout.
    """

    instances: ClassVar[list[FakeSCPClient]] = []

    def __init__(self, transport, progress=None):
        self.transport = transport
        self.progress = progress
        self.get_calls: list[tuple[str, str]] = []
        self.put_calls: list[tuple[str, str]] = []
        self.closed = False
        FakeSCPClient.instances.append(self)

    def get(self, remote_path, local_path):
        self.get_calls.append((remote_path, local_path))

    def put(self, local_path, remote_path):
        self.put_calls.append((local_path, remote_path))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.closed = True
        return False


@pytest.fixture(autouse=True)
def _reset_fake_scp_instances():
    FakeSCPClient.instances = []
    yield
    FakeSCPClient.instances = []


@pytest.fixture
def debug_log_messages():
    """Capture les messages `loguru` au niveau DEBUG le temps d'un test.

    Le sink est retiré à la fin (`logger.remove`), qu'importe l'issue du
    test — jamais laissé enregistré pour le reste de la suite. Même
    préoccupation que la fuite d'état `sys.modules`/`importlib.reload`
    corrigée en session 58 (`test_optional_imports_absent.py`) : un sink
    de test oublié continuerait à recevoir tous les messages DEBUG émis
    par le reste de la suite, pour rien (personne ne relit plus la liste
    `calls` associée) et pour toujours (jusqu'à la fin du process pytest).
    Seul le message déjà formaté (pas le niveau/horodatage) est capturé,
    pour des assertions `in` simples sur le contenu métier de la ligne.
    """
    messages: list[str] = []
    sink_id = logger.add(lambda message: messages.append(message.record["message"]), level="DEBUG")
    try:
        yield messages
    finally:
        logger.remove(sink_id)


@pytest.fixture
def fake_paramiko(monkeypatch):
    """Remplace `paramiko`/`SCPClient` (globals du module) pour toute la
    durée d'un test, puis restaure automatiquement (monkeypatch)."""
    monkeypatch.setattr(core, "paramiko", FakeParamikoModule)
    monkeypatch.setattr(core, "SCPClient", FakeSCPClient)


def test_open_scp_ssh_client_raises_without_paramiko(monkeypatch):
    """Sans paramiko/scp installés (globals à None, cas réel documenté en
    tête de `open_scp_ssh_client`), lever RuntimeError plutôt que planter
    plus loin avec un AttributeError obscur sur `None.SSHClient`."""
    monkeypatch.setattr(core, "paramiko", None)
    monkeypatch.setattr(core, "SCPClient", None)
    cfg = core.Config(
        switch_ip="10.0.0.1",
        ssh_user="admin",
        ssh_password="secret",
        capture_interface="GigabitEthernet1/0/1",
    )
    with pytest.raises(RuntimeError, match="paramiko"):
        core.open_scp_ssh_client(cfg)


def test_open_scp_ssh_client_connects_with_expected_arguments(fake_paramiko):
    """Vérifie précisément les paramètres de connexion attendus :
    `look_for_keys=False`/`allow_agent=False` (pas d'agent SSH ni de clé
    locale — mot de passe RADIUS explicite uniquement, cf. docstring
    `Config.ssh_user`), `timeout=15`, et une politique de clé hôte
    permissive (`AutoAddPolicy`, un switch de terrain n'a pas de clé hôte
    connue à l'avance)."""
    cfg = core.Config(
        switch_ip="10.0.0.42",
        ssh_user="admin",
        ssh_password="hunter2",
        capture_interface="GigabitEthernet1/0/1",
    )

    client = core.open_scp_ssh_client(cfg)

    assert isinstance(client, FakeSSHClient)
    assert isinstance(client.policy, FakeAutoAddPolicy)
    assert client.connect_kwargs == {
        "host": "10.0.0.42",
        "username": "admin",
        "password": "hunter2",
        "timeout": 15,
        "look_for_keys": False,
        "allow_agent": False,
    }


def test_scp_get_uses_transport_and_forwards_paths(fake_paramiko, tmp_path):
    """`scp_get` doit construire le `SCPClient` à partir de
    `ssh_client.get_transport()` (pas d'une nouvelle connexion), l'utiliser
    comme context manager (fermeture garantie), et transmettre le chemin
    local tel quel converti en `str` — pas un `Path` brut, `scp` attend une
    chaîne."""
    ssh_client = FakeSSHClient()
    local_path = tmp_path / "capture2_00001.pcap"

    core.scp_get(ssh_client, "/capture2_00001.pcap", local_path)

    assert len(FakeSCPClient.instances) == 1
    scp_instance = FakeSCPClient.instances[0]
    assert isinstance(scp_instance.transport, FakeTransport)
    assert scp_instance.get_calls == [("/capture2_00001.pcap", str(local_path))]
    assert scp_instance.put_calls == []
    assert scp_instance.closed is True


def test_scp_get_remote_path_has_no_flash_prefix_by_construction(fake_paramiko, tmp_path):
    """Non-régression directe du bug corrigé le 23/08/2026 (voir
    features.md, section « Transfert de fichiers ») : le chemin distant
    passé à `scp_get` ne doit jamais porter le préfixe `flash:`, qui
    n'existe que côté syntaxe CLI Comware (`dir flash:/...`), pas côté
    serveur SCP dont la racine EST déjà la flash. `scp_get` elle-même ne
    fait aucune manipulation de préfixe — c'est à l'appelant de fournir un
    chemin déjà nettoyé — donc ce test fige le contrat : ce qui est passé
    en argument est transmis tel quel, sans ajout ni retrait implicite. Le
    bug historique était dans l'appelant (`_process_closed_file_scp`), pas
    ici, mais un futur appelant qui recommencerait à passer `flash:/...`
    ferait échouer un test d'intégration explicite plutôt que ce silence.
    """
    ssh_client = FakeSSHClient()
    remote_path_without_prefix = "/capture2_00002.pcap"

    core.scp_get(ssh_client, remote_path_without_prefix, tmp_path / "out.pcap")

    remote_arg = FakeSCPClient.instances[0].get_calls[0][0]
    assert not remote_arg.startswith("flash:")
    assert remote_arg == remote_path_without_prefix


def test_scp_put_uses_transport_and_forwards_paths(fake_paramiko, tmp_path):
    """Symétrique de `test_scp_get_uses_transport_and_forwards_paths` :
    `scp_put` convertit le chemin *local* en `str` (`scp_get` convertit le
    chemin local, `scp_put` — sens inverse — doit le faire aussi, seul le
    chemin distant reste une chaîne native des deux côtés)."""
    ssh_client = FakeSSHClient()
    local_path = tmp_path / "feature.bin"
    local_path.write_bytes(b"\x00")

    core.scp_put(ssh_client, local_path, "/feature.bin")

    assert len(FakeSCPClient.instances) == 1
    scp_instance = FakeSCPClient.instances[0]
    assert scp_instance.put_calls == [(str(local_path), "/feature.bin")]
    assert scp_instance.get_calls == []
    assert scp_instance.closed is True


def test_scp_get_and_put_each_open_their_own_scp_client(fake_paramiko, tmp_path):
    """Non-régression du second bug corrigé le 23/08/2026 : chaque appel
    doit ouvrir/fermer son propre `SCPClient` plutôt que d'en réutiliser un
    déjà existant après un premier transfert (cause du `Bad file
    descriptor` historique sur le deuxième fichier rapatrié)."""
    ssh_client = FakeSSHClient()

    core.scp_get(ssh_client, "/a.pcap", tmp_path / "a.pcap")
    core.scp_get(ssh_client, "/b.pcap", tmp_path / "b.pcap")

    assert len(FakeSCPClient.instances) == 2
    assert FakeSCPClient.instances[0] is not FakeSCPClient.instances[1]
    assert all(inst.closed for inst in FakeSCPClient.instances)


# --------------------------------------------------------------------------- #
# progress_callback / make_scp_progress_logger (candidat #6, audit Context7
# session 56) — voir docstring de make_scp_progress_logger.
# --------------------------------------------------------------------------- #


def test_scp_get_without_progress_callback_passes_none_by_default(fake_paramiko, tmp_path):
    """Non-régression explicite : le paramètre est optionnel, et son absence
    doit atteindre `SCPClient(progress=None)` — pas de valeur implicite
    différente qui romprait un futur appelant s'y fiant."""
    core.scp_get(FakeSSHClient(), "/a.pcap", tmp_path / "a.pcap")

    assert FakeSCPClient.instances[0].progress is None


def test_scp_get_forwards_progress_callback_to_scpclient(fake_paramiko, tmp_path):
    def sentinel(filename, size, sent):
        """Juste une identité à vérifier — jamais réellement appelée ici (`FakeSCPClient` ne simule pas de transfert)."""

    core.scp_get(FakeSSHClient(), "/a.pcap", tmp_path / "a.pcap", progress_callback=sentinel)

    assert FakeSCPClient.instances[0].progress is sentinel


def test_scp_put_forwards_progress_callback_to_scpclient(fake_paramiko, tmp_path):
    def sentinel(filename, size, sent):
        """Voir `test_scp_get_forwards_progress_callback_to_scpclient`."""

    local_path = tmp_path / "feature.bin"
    local_path.write_bytes(b"\x00")

    core.scp_put(FakeSSHClient(), local_path, "/feature.bin", progress_callback=sentinel)

    assert FakeSCPClient.instances[0].progress is sentinel


def test_progress_logger_does_not_log_below_first_threshold(debug_log_messages):
    progress = core.make_scp_progress_logger("ctx")

    progress(b"a.pcap", 1000, 50)  # 5 % : sous le premier palier de 10 %

    assert debug_log_messages == []


def test_progress_logger_logs_at_each_new_threshold_crossed(debug_log_messages):
    progress = core.make_scp_progress_logger("ctx")

    progress(b"a.pcap", 1000, 100)  # 10 %
    progress(b"a.pcap", 1000, 350)  # 35 % -> palier 30 %
    progress(b"a.pcap", 1000, 1000)  # 100 %

    assert len(debug_log_messages) == 3
    assert "10%" in debug_log_messages[0]
    assert "30%" in debug_log_messages[1]
    assert "100%" in debug_log_messages[2]


def test_progress_logger_does_not_repeat_same_threshold(debug_log_messages):
    """Plusieurs appels dans le même palier de 10 points (cas réel : `scp`
    rappelle son callback à chaque bloc, pas seulement à chaque dizaine de
    pourcent franchie) ne doivent produire qu'une seule ligne de log."""
    progress = core.make_scp_progress_logger("ctx")

    for sent in (101, 105, 109, 115, 119):
        progress(b"a.pcap", 1000, sent)  # tous dans [10 %, 20 %[

    assert len(debug_log_messages) == 1
    assert "10%" in debug_log_messages[0]


def test_progress_logger_never_logs_more_than_100_percent(debug_log_messages):
    progress = core.make_scp_progress_logger("ctx")

    progress(b"a.pcap", 1000, 1500)  # sent > size : ne doit jamais arriver en pratique, mais ne doit pas planter

    assert len(debug_log_messages) == 1
    assert "100%" in debug_log_messages[0]
    assert "150%" not in debug_log_messages[0]


def test_progress_logger_decodes_bytes_filename(debug_log_messages):
    """`filename` est `bytes` selon la version de `paramiko`/`scp` (voir
    docstring) : doit apparaître décodé en `str` dans le message de log,
    jamais sous la forme `b'...'`."""
    progress = core.make_scp_progress_logger("ctx")

    progress(b"capture2_00001.pcap", 1000, 500)

    assert "capture2_00001.pcap" in debug_log_messages[0]
    assert "b'" not in debug_log_messages[0]


def test_progress_logger_accepts_str_filename_too(debug_log_messages):
    progress = core.make_scp_progress_logger("ctx")

    progress("capture2_00001.pcap", 1000, 500)  # str plutôt que bytes

    assert "capture2_00001.pcap" in debug_log_messages[0]


def test_progress_logger_zero_size_is_a_silent_noop(debug_log_messages):
    """Fichier vide (`size=0`) : aucun pourcentage n'a de sens, et surtout
    pas de `ZeroDivisionError`."""
    progress = core.make_scp_progress_logger("ctx")

    progress(b"empty.pcap", 0, 0)  # ne doit pas lever

    assert debug_log_messages == []


def test_progress_logger_tracks_each_filename_independently(debug_log_messages):
    """Un même callback réutilisé pour plusieurs fichiers (cas réel :
    `CaptureRotationThread._scp_progress_logger`, un seul par thread pour
    toute sa durée de vie) ne doit pas mélanger leurs paliers respectifs."""
    progress = core.make_scp_progress_logger("ctx")

    progress(b"a.pcap", 1000, 900)  # a.pcap : palier 90 %
    progress(b"b.pcap", 1000, 100)  # b.pcap, nouveau fichier : palier 10 %, doit tout de même logger

    assert len(debug_log_messages) == 2
    assert "a.pcap" in debug_log_messages[0] and "90%" in debug_log_messages[0]
    assert "b.pcap" in debug_log_messages[1] and "10%" in debug_log_messages[1]


def test_progress_logger_custom_threshold_percent(debug_log_messages):
    progress = core.make_scp_progress_logger("ctx", threshold_percent=25)

    progress(b"a.pcap", 1000, 200)  # 20 % : sous le premier palier de 25 %
    progress(b"a.pcap", 1000, 260)  # 26 % -> palier 25 %

    assert len(debug_log_messages) == 1
    assert "25%" in debug_log_messages[0]


def test_scp_get_wired_to_progress_logger_end_to_end(fake_paramiko, tmp_path):
    """Bout en bout, sans mock de `logger` : un `make_scp_progress_logger`
    passé en `progress_callback` à `scp_get` doit atteindre `SCPClient`
    inchangé (même callable), prêt à être appelé par un vrai `scp.SCPClient`."""
    progress = core.make_scp_progress_logger("process_closed_file_scp")

    core.scp_get(FakeSSHClient(), "/a.pcap", tmp_path / "a.pcap", progress_callback=progress)

    assert FakeSCPClient.instances[0].progress is progress


# --------------------------------------------------------------------------- #
# list_remote_pcap_files / delete_remote_file / delete_remote_all_file_capture
# — couche netmiko (commandes CLI Comware, pas de SCP)
# --------------------------------------------------------------------------- #


class FakeConn:
    """Simule une session netmiko en écriture limitée : `send_command`
    pour le listing (lecture seule), `send_command_timing` pour la
    suppression (avec confirmation optionnelle). Journalise tous les
    appels pour vérification, comme `FakeConn` dans `test_inspect.py`."""

    def __init__(self, dir_output: str = "", confirm_prompt: bool = False):
        self.dir_output = dir_output
        self.confirm_prompt = confirm_prompt
        self.sent_commands: list[str] = []
        self.timing_commands: list[str] = []

    def send_command(self, cmd):
        self.sent_commands.append(cmd)
        return self.dir_output

    def send_command_timing(self, cmd, read_timeout=15):
        self.timing_commands.append(cmd)
        if cmd == "y":
            return ""
        return "Continue? [Y/N]" if self.confirm_prompt else "Deleted successfully."


DIR_OUTPUT_TYPICAL = (
    "Directory of flash:/\n"
    "\n"
    "   0 -rw-        1024 Sep 07 2026 10:00:00   capture2_00001.pcap\n"
    "   1 -rw-        2048 Sep 07 2026 10:00:20   capture2_00003.pcap\n"
    "   2 -rw-        1536 Sep 07 2026 10:00:40   capture2_00002.pcap\n"
    "   3 -rw-           0 Sep 07 2026 09:00:00   startup.cfg\n"
    "\n"
    "255488 KB total (204800 KB free)\n"
)


def test_list_remote_pcap_files_sends_expected_dir_command():
    """La commande envoyée doit être un `dir flash:/<prefix>*.pcap`
    (lecture seule, jamais une commande de configuration) — vérifié
    littéralement, pas juste indirectement via le résultat."""
    conn = FakeConn(dir_output=DIR_OUTPUT_TYPICAL)

    core.list_remote_pcap_files(conn, "capture2_")

    assert conn.sent_commands == ["dir flash:/capture2_*.pcap"]


def test_list_remote_pcap_files_parses_and_sorts():
    """Seules les lignes se terminant par `.pcap` sont retenues (le
    fichier `startup.cfg` de la sortie `dir` doit être ignoré), le nom de
    fichier est le dernier token de la ligne, et le résultat est trié
    alphabétiquement — donc chronologiquement grâce à l'horodatage Comware
    dans le nom, même si l'ordre de sortie `dir` ne l'était pas ici
    (00003 avant 00002 dans `DIR_OUTPUT_TYPICAL`)."""
    conn = FakeConn(dir_output=DIR_OUTPUT_TYPICAL)

    result = core.list_remote_pcap_files(conn, "capture2_")

    assert result == [
        "capture2_00001.pcap",
        "capture2_00002.pcap",
        "capture2_00003.pcap",
    ]


def test_list_remote_pcap_files_empty_when_no_match():
    conn = FakeConn(dir_output="No files found.\n")

    assert core.list_remote_pcap_files(conn, "capture2_") == []


def test_delete_remote_file_sends_expected_delete_command():
    conn = FakeConn(confirm_prompt=False)

    core.delete_remote_file(conn, "capture2_00001.pcap")

    assert conn.timing_commands == ["delete flash:/capture2_00001.pcap"]


def test_delete_remote_file_confirms_when_switch_prompts():
    """Quand le switch répond par une invite de confirmation (`Continue?`/
    `[Y/N]`), un second envoi de `y` doit suivre automatiquement — sans
    quoi la suppression resterait bloquée en attente d'une confirmation
    jamais donnée."""
    conn = FakeConn(confirm_prompt=True)

    core.delete_remote_file(conn, "capture2_00001.pcap")

    assert conn.timing_commands == ["delete flash:/capture2_00001.pcap", "y"]


def test_delete_remote_file_no_extra_confirmation_when_not_prompted():
    """Contrepartie du test précédent : si le switch supprime directement
    sans rien demander, aucun `y` parasite ne doit être envoyé."""
    conn = FakeConn(confirm_prompt=False)

    core.delete_remote_file(conn, "capture2_00001.pcap")

    assert "y" not in conn.timing_commands


def test_delete_remote_all_file_capture_deletes_each_listed_file():
    conn = FakeConn(dir_output=DIR_OUTPUT_TYPICAL, confirm_prompt=False)

    core.delete_remote_all_file_capture(conn, "capture2_")

    delete_commands = [cmd for cmd in conn.timing_commands if cmd.startswith("delete ")]
    assert delete_commands == [
        "delete flash:/capture2_00001.pcap",
        "delete flash:/capture2_00002.pcap",
        "delete flash:/capture2_00003.pcap",
    ]


def test_delete_remote_all_file_capture_noop_when_nothing_to_delete():
    """Aucun fichier trouvé -> aucun appel de suppression, et surtout pas
    d'appel avec un nom de fichier vide/`None`."""
    conn = FakeConn(dir_output="No files found.\n")

    core.delete_remote_all_file_capture(conn, "capture2_")

    assert conn.timing_commands == []


def test_delete_remote_all_file_capture_swallows_listing_failure(monkeypatch):
    """Le `try/except Exception` autour de `list_remote_pcap_files` (voir
    docstring de la fonction) doit avaler l'échec et retourner
    silencieusement plutôt que remonter l'exception à l'appelant — c'est
    un nettoyage best-effort en fin de capture, pas une étape critique qui
    doit faire échouer tout le reste."""

    def _boom(conn, prefix):
        raise RuntimeError("switch injoignable")

    monkeypatch.setattr(core, "list_remote_pcap_files", _boom)
    conn = FakeConn()

    core.delete_remote_all_file_capture(conn, "capture2_")  # ne doit pas lever

    assert conn.timing_commands == []
