"""Tests unitaires de `TapFrameWriter` (switch_capture_core).

Repéré à 0 % par l'audit `coverage.py` de session 54 : les tests existants
(`test_tap_pacing.py`, `test_tap_injector_thread.py`) remplacent
systématiquement `TapFrameWriter` par un `FakeTapWriter` pour tester
`_feed_into_tap` sans dépendre de `/dev/net/tun`, donc la classe elle-même
n'était jamais exercée directement — seul un test d'intégration réel, gaté
`root`, la couvre de bout en bout (`test_tap_helper_nonroot.py::
test_taphelper_end_to_end_as_real_nonroot_user`, ignoré si l'environnement
ne s'y prête pas).

Vérifié réellement en sandbox avant d'écrire ces tests (session 54) :
`/dev/net/tun` existe et est accessible en root dans ce sandbox, et
`os.open` + l'ioctl `TUNSETIFF` réussissent bien (l'interface TAP est créée
côté noyau) — mais `write_frame` échoue ensuite avec `OSError: [Errno 5]
Input/output error`, l'interface n'étant jamais passée "up" faute du
binaire `ip` dans ce sandbox (même absence que le seul échec préexistant
sans rapport de la suite, voir CLAUDE.md). Tester `write_frame`/`close`
réellement nécessiterait donc soit `ip` (absent ici), soit une syscall
netlink directe rien que pour ce test — hors de portée raisonnable pour 3
lignes. Choix retenu, cohérent avec le reste de la suite (`subprocess.run`
mocké partout ailleurs pour les mêmes raisons) : mocker `os.open`/
`fcntl.ioctl`/`os.write`/`os.close` au niveau du module, sans toucher au
device réel ni nécessiter root.
"""

from __future__ import annotations

import os

import pytest

import switch_capture_core as core
from switch_capture_core import IFF_NO_PI, IFF_TAP, TUNSETIFF, TapFrameWriter


@pytest.fixture()
def mocked_tun(monkeypatch):
    """Remplace os.open/fcntl.ioctl/os.write/os.close pour TapFrameWriter, sans /dev/net/tun réel."""
    calls: dict[str, list] = {"open": [], "ioctl": [], "write": [], "close": []}

    def fake_open(path, flags):
        calls["open"].append((path, flags))
        return 42  # fd factice

    def fake_ioctl(fd, request, arg):
        calls["ioctl"].append((fd, request, arg))
        return 0

    def fake_write(fd, data):
        calls["write"].append((fd, data))
        return len(data)

    def fake_close(fd):
        calls["close"].append(fd)

    monkeypatch.setattr(core.os, "open", fake_open)
    monkeypatch.setattr(core.fcntl, "ioctl", fake_ioctl)
    monkeypatch.setattr(core.os, "write", fake_write)
    monkeypatch.setattr(core.os, "close", fake_close)
    return calls


def test_init_opens_dev_net_tun_and_attaches_interface(mocked_tun):
    writer = TapFrameWriter("vcap1")

    assert mocked_tun["open"] == [("/dev/net/tun", os.O_RDWR)]
    assert writer._fd == 42
    assert writer.ifname == "vcap1"


def test_init_ioctl_uses_tunsetiff_with_tap_and_no_pi_flags(mocked_tun):
    TapFrameWriter("vcap1")

    assert len(mocked_tun["ioctl"]) == 1
    fd, request, ifr = mocked_tun["ioctl"][0]
    assert fd == 42
    assert request == TUNSETIFF
    # ifr est le struct pack("16sH", ...) : nom de l'interface (16 octets,
    # complété de zéros) suivi des flags IFF_TAP|IFF_NO_PI (little-endian).
    assert ifr[:6] == b"vcap1\x00"
    assert ifr[16:18] == (IFF_TAP | IFF_NO_PI).to_bytes(2, "little")


def test_write_frame_writes_raw_bytes_to_fd(mocked_tun):
    writer = TapFrameWriter("vcap1")
    frame = b"\x00" * 12 + b"\x08\x00" + b"payload"

    writer.write_frame(frame)

    assert mocked_tun["write"] == [(42, frame)]


def test_close_closes_the_fd(mocked_tun):
    writer = TapFrameWriter("vcap1")
    writer.close()

    assert mocked_tun["close"] == [42]


def test_close_swallows_oserror(mocked_tun, monkeypatch):
    """`close()` ne doit jamais lever, même si le fd est déjà invalide/fermé."""

    def raising_close(fd):
        raise OSError("Bad file descriptor")

    monkeypatch.setattr(core.os, "close", raising_close)

    writer = TapFrameWriter("vcap1")
    writer.close()  # ne doit pas lever


def test_ioctl_failure_propagates(mocked_tun, monkeypatch):
    """Un échec d'ioctl (nom d'interface déjà pris par un autre type, etc.)
    remonte tel quel — aucun avalage silencieux à la création."""

    def raising_ioctl(fd, request, arg):
        raise OSError("Device or resource busy")

    monkeypatch.setattr(core.fcntl, "ioctl", raising_ioctl)

    with pytest.raises(OSError, match="busy"):
        TapFrameWriter("vcap1")
