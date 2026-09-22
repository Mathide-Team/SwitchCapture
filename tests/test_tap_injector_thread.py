"""Tests du découplage téléchargement / injection TAP (switch_capture_core).

Couvre le point #1 restant de la section « Pas fait » de features.md (hors
mesure réelle contre un switch, qui nécessite du matériel) : « Découpler
téléchargement et lecture/injection via une file d'attente et un thread
dédié (pour ne pas bloquer le polling pendant une éventuelle pause de
lissage) ». Avant ce changement, `_feed_into_tap` (et son éventuel
`time.sleep` de lissage, voir test_tap_pacing.py) tournait de façon
synchrone dans le thread de rotation lui-même (celui qui télécharge aussi
les fichiers suivants) — un fichier au lissage lent retardait donc
d'autant le rapatriement du fichier suivant.

Ce module vérifie :
    - `_dispatch_for_injection` : aiguillage correct par output_mode (tap
      -> file d'attente, sans appeler _feed_into_tap ; fifo -> appel
      direct et synchrone, comportement historique inchangé).
    - `_injector_loop` : dépile et réinjecte dans l'ordre, tolère une
      exception sur un fichier sans s'arrêter, s'arrête proprement sur
      stop_event ou sur la sentinelle None.
    - Le comportement qui motive tout ce découplage : un fichier déposé
      pendant qu'un précédent est encore en cours d'injection (lissage en
      cours) est accepté immédiatement, sans attendre — seul l'ordre final
      d'injection est garanti, pas son immédiateté.
    - `_cleanup` (mode tap) : arrête et attend le thread injecteur avant de
      fermer le writer TAP (ordre important, voir _cleanup).

Ne nécessite ni switch réel ni GTK4 : uniquement switch_capture_core, un
fichier .pcap synthétique construit à la main, et `tmp_path`.
"""

from __future__ import annotations

import queue
import threading
import time as time_module
from pathlib import Path

from test_tap_pacing import make_config, write_synthetic_pcap  # réutilisés tels quels

from switch_capture_core import CaptureRotationThread, Config, SharedState


class FakeTapWriter:
    """Remplace TapFrameWriter : enregistre les trames écrites sans /dev/net/tun.

    Identique à celle de test_tap_pacing.py, plus un flag `closed` : utile
    ici pour vérifier l'ordre d'arrêt dans _cleanup (thread injecteur
    joint avant la fermeture du writer).
    """

    def __init__(self) -> None:
        self.written: list[bytes] = []
        self.closed = False

    def write_frame(self, frame: bytes) -> None:
        self.written.append(frame)

    def close(self) -> None:
        self.closed = True


def make_tap_thread(cfg: Config) -> CaptureRotationThread:
    """CaptureRotationThread minimal en mode tap, prêt pour _dispatch_for_injection.

    N'appelle ni .run() ni _setup_tap (donc pas d'accès réseau/root réel) :
    _tap_writer et _tap_queue sont câblés à la main, comme _setup_tap le
    ferait normalement.
    """
    state = SharedState()
    thread = CaptureRotationThread(cfg, state)
    thread._tap_writer = FakeTapWriter()
    thread._tap_queue = queue.Queue()
    return thread


# --------------------------------------------------------------------- #
# _dispatch_for_injection : aiguillage par output_mode
# --------------------------------------------------------------------- #


def test_dispatch_tap_mode_queues_without_calling_feed(tmp_path, monkeypatch):
    """Mode tap : dépose sur la file, n'appelle PAS _feed_into_tap directement."""
    cfg = make_config(spool_dir=str(tmp_path), archive_dir=str(tmp_path / "archive"))
    thread = make_tap_thread(cfg)

    calls: list[Path] = []
    monkeypatch.setattr(thread, "_feed_into_tap", lambda f: calls.append(f))

    pcap = tmp_path / "capture_00001.pcap"
    thread._dispatch_for_injection(pcap)

    assert calls == []  # pas d'appel synchrone
    assert thread._tap_queue.get_nowait() == pcap


def test_dispatch_fifo_mode_calls_feed_directly(tmp_path, monkeypatch):
    """Mode fifo : comportement historique inchangé — appel direct et synchrone."""
    cfg = make_config(
        spool_dir=str(tmp_path),
        output_mode="fifo",
        fifo_path=str(tmp_path / "live.fifo"),
    )
    state = SharedState()
    thread = CaptureRotationThread(cfg, state)

    calls: list[Path] = []
    monkeypatch.setattr(thread, "_feed_into_fifo", lambda f: calls.append(f))

    pcap = tmp_path / "capture_00001.pcap"
    thread._dispatch_for_injection(pcap)

    assert calls == [pcap]
    assert thread._tap_queue is None  # jamais créée en mode fifo (_setup_tap non appelé)


# --------------------------------------------------------------------- #
# _injector_loop : dépile, réinjecte, tolère les erreurs, s'arrête proprement
# --------------------------------------------------------------------- #


def test_injector_loop_feeds_in_order_then_stops_on_sentinel(tmp_path, monkeypatch):
    cfg = make_config(spool_dir=str(tmp_path), archive_dir=str(tmp_path / "archive"))
    thread = make_tap_thread(cfg)
    monkeypatch.setattr(time_module, "sleep", lambda s: None)

    pcap_a = tmp_path / "capture_00001.pcap"
    pcap_b = tmp_path / "capture_00002.pcap"
    write_synthetic_pcap(pcap_a, [(1000.0, b"a")])
    write_synthetic_pcap(pcap_b, [(2000.0, b"b")])

    injector = threading.Thread(target=thread._injector_loop, daemon=True)
    injector.start()
    thread._tap_queue.put(pcap_a)
    thread._tap_queue.put(pcap_b)
    thread._tap_queue.put(None)  # sentinelle : arrêt propre
    injector.join(timeout=5.0)

    assert not injector.is_alive()
    assert thread._tap_writer.written == [b"a", b"b"]
    assert thread.state.files_merged == 2


def test_injector_loop_stops_on_stop_event_without_sentinel(tmp_path):
    """Sans sentinelle : stop_event seul doit aussi arrêter la boucle (poll borné à 0.5s)."""
    cfg = make_config(spool_dir=str(tmp_path), archive_dir=str(tmp_path / "archive"))
    thread = make_tap_thread(cfg)

    injector = threading.Thread(target=thread._injector_loop, daemon=True)
    injector.start()
    thread.state.stop_event.set()
    injector.join(timeout=2.0)

    assert not injector.is_alive()


def test_injector_loop_survives_bad_file_and_continues(tmp_path, monkeypatch):
    """Un fichier corrompu (ValueError, cas déjà géré par _feed_into_tap) ne casse pas la boucle."""
    cfg = make_config(spool_dir=str(tmp_path), archive_dir=str(tmp_path / "archive"))
    thread = make_tap_thread(cfg)
    monkeypatch.setattr(time_module, "sleep", lambda s: None)

    bad = tmp_path / "corrompu.pcap"
    bad.write_bytes(b"\x00" * 24)  # magic invalide -> _feed_into_tap logue et return (ValueError avalée)
    good = tmp_path / "capture_00001.pcap"
    write_synthetic_pcap(good, [(1000.0, b"ok")])

    injector = threading.Thread(target=thread._injector_loop, daemon=True)
    injector.start()
    thread._tap_queue.put(bad)
    thread._tap_queue.put(good)
    thread._tap_queue.put(None)
    injector.join(timeout=5.0)

    assert not injector.is_alive()
    assert thread._tap_writer.written == [b"ok"]  # le fichier valide suivant est bien traité


def test_injector_loop_survives_unexpected_exception(tmp_path, monkeypatch):
    """Une exception inattendue (pas seulement ValueError) ne doit pas non plus tuer le thread."""
    cfg = make_config(spool_dir=str(tmp_path), archive_dir=str(tmp_path / "archive"))
    thread = make_tap_thread(cfg)

    calls: list[Path] = []

    def flaky_feed(pcap_file):
        calls.append(pcap_file)
        if len(calls) == 1:
            raise RuntimeError("panne simulée")

    monkeypatch.setattr(thread, "_feed_into_tap", flaky_feed)

    injector = threading.Thread(target=thread._injector_loop, daemon=True)
    injector.start()
    thread._tap_queue.put(Path("premier.pcap"))
    thread._tap_queue.put(Path("second.pcap"))
    thread._tap_queue.put(None)
    injector.join(timeout=5.0)

    assert not injector.is_alive()
    assert calls == [Path("premier.pcap"), Path("second.pcap")]


# --------------------------------------------------------------------- #
# Le coeur du découplage : dispatch non bloquant pendant une injection lente
# --------------------------------------------------------------------- #


def test_dispatch_does_not_wait_for_slow_injection_in_progress(tmp_path, monkeypatch):
    """Un 2e fichier peut être déposé (et l'est immédiatement) pendant le lissage du 1er.

    C'est exactement le scénario visé par features.md : avant ce
    découplage, le thread qui dépose (ici simulé directement, à la place
    du thread de polling réel) aurait été le MÊME thread que celui qui
    injecte — donc bloqué jusqu'à la fin du sleep de lissage. Ici, deux
    threads distincts : le dépôt n'attend jamais l'injecteur.
    """
    cfg = make_config(
        spool_dir=str(tmp_path),
        archive_dir=str(tmp_path / "archive"),
        tap_pace_playback=True,
        tap_pace_max_gap_seconds=5.0,
    )
    thread = make_tap_thread(cfg)

    # 2 trames avec un écart : la 1ere s'écrit sans délai (delay=0.0, jamais
    # de sleep, voir _feed_into_tap), la 2e déclenche un sleep(0.5) — c'est
    # CE sleep qu'on bloque nous-mêmes pour simuler un lissage en cours.
    pcap1 = tmp_path / "capture_00001.pcap"
    write_synthetic_pcap(pcap1, [(1000.0, b"a1"), (1000.5, b"a2")])
    pcap2 = tmp_path / "capture_00002.pcap"
    write_synthetic_pcap(pcap2, [(2000.0, b"b1")])

    entered_sleep = threading.Event()
    release_sleep = threading.Event()

    def blocking_sleep(seconds):
        entered_sleep.set()
        assert release_sleep.wait(timeout=5.0), "le test n'a jamais débloqué le sleep simulé"

    monkeypatch.setattr(time_module, "sleep", blocking_sleep)

    injector = threading.Thread(target=thread._injector_loop, daemon=True)
    injector.start()

    thread._tap_queue.put(pcap1)
    assert entered_sleep.wait(timeout=2.0), "l'injecteur n'est jamais entré dans le sleep de lissage"
    # L'injecteur est maintenant bloqué ENTRE les deux trames de pcap1 :
    # seule la 1ere ("a1") a été écrite, la pause de lissage est en cours.
    assert thread._tap_writer.written == [b"a1"]

    # Dépôt du 2e fichier PENDANT que l'injecteur est occupé/bloqué sur le
    # 1er : doit être accepté immédiatement (Queue.put ne bloque jamais
    # côté producteur ici), sans attendre release_sleep.
    start = time_module.monotonic()
    thread._tap_queue.put(pcap2)
    assert time_module.monotonic() - start < 0.5

    # Le 2e fichier ne doit pas encore avoir été touché : l'injecteur est
    # toujours occupé sur le 1er.
    assert thread._tap_writer.written == [b"a1"]

    release_sleep.set()  # débloque la fin de l'injection de pcap1
    thread._tap_queue.put(None)  # sentinelle : arrêt propre une fois pcap2 traité
    injector.join(timeout=5.0)

    assert not injector.is_alive()
    assert thread._tap_writer.written == [b"a1", b"a2", b"b1"]
    assert thread.state.files_merged == 2


# --------------------------------------------------------------------- #
# _cleanup (mode tap) : arrête l'injecteur AVANT de fermer le writer TAP
# --------------------------------------------------------------------- #


def test_cleanup_joins_injector_before_closing_writer(tmp_path, monkeypatch):
    cfg = make_config(
        spool_dir=str(tmp_path),
        archive_dir=str(tmp_path / "archive"),
        tap_cleanup_on_stop=False,
    )
    thread = make_tap_thread(cfg)
    monkeypatch.setattr(time_module, "sleep", lambda s: None)

    thread._injector_thread = threading.Thread(target=thread._injector_loop, daemon=True)
    thread._injector_thread.start()

    pcap = tmp_path / "capture_00001.pcap"
    write_synthetic_pcap(pcap, [(1000.0, b"a")])
    thread._tap_queue.put(pcap)

    thread._cleanup()

    assert not thread._injector_thread.is_alive()  # join() a bien attendu la fin
    assert thread._tap_writer.written == [b"a"]  # traité avant la fermeture
    assert thread._tap_writer.closed is True  # writer fermé après coup


def test_cleanup_without_injector_thread_does_not_crash(tmp_path):
    """_cleanup doit rester robuste si _setup_tap n'a jamais tourné (_injector_thread/_tap_queue à None)."""
    cfg = make_config(spool_dir=str(tmp_path), archive_dir=str(tmp_path / "archive"))
    state = SharedState()
    thread = CaptureRotationThread(cfg, state)
    thread._tap_writer = FakeTapWriter()
    # _tap_queue et _injector_thread restent à None (comme juste après __init__).

    thread._cleanup()  # ne doit lever aucune exception

    assert thread._tap_writer.closed is True
