/* switch-capture-taphelper — aide privilégiée minimale pour le mode "tap".
 *
 * Problème (features.md, priorité 000 — urgente) : créer une interface TAP
 * (`ip tuntap add ... mode tap`) et l'activer (`ip link set ... up`)
 * nécessite CAP_NET_ADMIN. Jusqu'ici, switch-capture devait donc tourner
 * en root en permanence pour le mode "tap", alors que tout le reste de son
 * fonctionnement (connexion SSH au switch, SCP, écriture de fichiers) ne le
 * demande pas.
 *
 * Ce binaire est le SEUL morceau de switch-capture qui a besoin de
 * privilèges. Installé par install.sh/build_deb.sh/build_rpm.sh avec la
 * capability `cap_net_admin+ep` (via `setcap`, PAS de bit setuid : le
 * process garde l'UID réel de l'utilisateur qui l'invoque, il gagne
 * seulement CAP_NET_ADMIN en effectif) :
 *
 *   setcap cap_net_admin+ep /usr/lib/switch-capture/switch-capture-taphelper
 *
 * Trois sous-commandes, chacune agissant sur UNE interface TAP nommée sur
 * la ligne de commande (validée strictement, voir valid_ifname) :
 *
 *   switch-capture-taphelper add <ifname>   crée l'interface TAP si besoin,
 *                                            et en fait le PROPRIETAIRE
 *                                            l'utilisateur réel qui invoque
 *                                            ce programme (TUNSETOWNER) —
 *                                            c'est ce qui permet ensuite à
 *                                            switch_capture_core.py
 *                                            (TapFrameWriter, sans aucun
 *                                            privilège) de s'attacher lui-
 *                                            même à cette même interface
 *                                            pour y injecter des trames :
 *                                            le noyau autorise un
 *                                            utilisateur non privilégié à
 *                                            ouvrir un tap persistant dont
 *                                            il est le propriétaire déclaré.
 *   switch-capture-taphelper up <ifname>    active l'interface (équivalent
 *                                            "ip link set <ifname> up").
 *   switch-capture-taphelper del <ifname>   retire la persistance de
 *                                            l'interface (équivalent
 *                                            "ip tuntap del <ifname> mode
 *                                            tap") ; silencieux si absente.
 *
 * Tout le reste (aucune autre action, aucun argument libre passé à un
 * sous-processus, aucun appel à execve/system) est volontairement hors de
 * portée : ce programme ne fait qu'un ioctl ciblé sur /dev/net/tun ou sur
 * une socket AF_INET, jamais de commande shell — la seule donnée fournie
 * par l'appelant (le nom d'interface) est strictement validée avant tout
 * usage, voir valid_ifname().
 */

#include <errno.h>
#include <linux/if.h>
#include <linux/if_tun.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <unistd.h>

/* Valide un nom d'interface réseau Linux : 1 à IFNAMSIZ-1 caractères,
 * uniquement alphanumérique/'_'/'-'/'.', ne commence pas par '-' (pour ne
 * jamais pouvoir être pris pour une option par un outil qui le relirait).
 * Défense en profondeur : switch_capture_core.py laisse déjà ce nom saisi
 * librement dans le formulaire, ce garde-fou empêche qu'un nom mal formé
 * atteigne un ioctl privilégié. */
static int valid_ifname(const char *name) {
    size_t len = strlen(name);
    if (len == 0 || len >= IFNAMSIZ) {
        return 0;
    }
    if (name[0] == '-') {
        return 0;
    }
    for (size_t i = 0; i < len; i++) {
        char c = name[i];
        int ok = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                 (c >= '0' && c <= '9') || c == '_' || c == '-' || c == '.';
        if (!ok) {
            return 0;
        }
    }
    return 1;
}

/* Ouvre /dev/net/tun et attache/crée l'interface TAP `name` (TUNSETIFF).
 * Retourne le descripteur ouvert (à fermer par l'appelant), ou -1 avec
 * errno positionné. */
static int open_tap(const char *name) {
    int fd = open("/dev/net/tun", O_RDWR);
    if (fd < 0) {
        return -1;
    }
    struct ifreq ifr;
    memset(&ifr, 0, sizeof(ifr));
    ifr.ifr_flags = IFF_TAP | IFF_NO_PI;
    strncpy(ifr.ifr_name, name, IFNAMSIZ - 1);
    if (ioctl(fd, TUNSETIFF, &ifr) < 0) {
        int saved_errno = errno;
        close(fd);
        errno = saved_errno;
        return -1;
    }
    return fd;
}

static int cmd_add(const char *name) {
    int fd = open_tap(name);
    if (fd < 0) {
        fprintf(stderr, "add %s : ouverture/attachement échoué : %s\n", name, strerror(errno));
        return 1;
    }
    /* Propriétaire = UID réel de l'appelant (pas root : ce process n'est
     * pas setuid, seulement porteur de CAP_NET_ADMIN en effectif) — c'est
     * ce qui permettra ensuite à switch_capture_core.py de s'attacher à
     * cette même interface sans privilège. */
    if (ioctl(fd, TUNSETOWNER, getuid()) < 0) {
        fprintf(stderr, "add %s : TUNSETOWNER échoué : %s\n", name, strerror(errno));
        close(fd);
        return 1;
    }
    if (ioctl(fd, TUNSETPERSIST, 1) < 0) {
        fprintf(stderr, "add %s : TUNSETPERSIST échoué : %s\n", name, strerror(errno));
        close(fd);
        return 1;
    }
    close(fd);
    return 0;
}

static int cmd_del(const char *name) {
    int fd = open_tap(name);
    if (fd < 0) {
        /* Interface déjà absente : non bloquant, même politique que
         * delete_tap_interface() côté Python. */
        fprintf(stderr, "del %s : %s (ignoré)\n", name, strerror(errno));
        return 0;
    }
    if (ioctl(fd, TUNSETPERSIST, 0) < 0) {
        fprintf(stderr, "del %s : TUNSETPERSIST(0) échoué : %s\n", name, strerror(errno));
        close(fd);
        return 1;
    }
    close(fd);
    return 0;
}

static int cmd_up(const char *name) {
    int sock = socket(AF_INET, SOCK_DGRAM, 0);
    if (sock < 0) {
        fprintf(stderr, "up %s : socket() échoué : %s\n", name, strerror(errno));
        return 1;
    }
    struct ifreq ifr;
    memset(&ifr, 0, sizeof(ifr));
    strncpy(ifr.ifr_name, name, IFNAMSIZ - 1);
    if (ioctl(sock, SIOCGIFFLAGS, &ifr) < 0) {
        fprintf(stderr, "up %s : SIOCGIFFLAGS échoué : %s\n", name, strerror(errno));
        close(sock);
        return 1;
    }
    ifr.ifr_flags |= IFF_UP | IFF_RUNNING;
    if (ioctl(sock, SIOCSIFFLAGS, &ifr) < 0) {
        fprintf(stderr, "up %s : SIOCSIFFLAGS échoué : %s\n", name, strerror(errno));
        close(sock);
        return 1;
    }
    close(sock);
    return 0;
}

int main(int argc, char **argv) {
    if (argc != 3) {
        fprintf(stderr, "usage : %s {add|up|del} <interface-tap>\n", argv[0]);
        return 2;
    }
    const char *action = argv[1];
    const char *name = argv[2];
    if (!valid_ifname(name)) {
        fprintf(stderr, "nom d'interface invalide : %s\n", name);
        return 2;
    }
    if (strcmp(action, "add") == 0) {
        return cmd_add(name);
    }
    if (strcmp(action, "up") == 0) {
        return cmd_up(name);
    }
    if (strcmp(action, "del") == 0) {
        return cmd_del(name);
    }
    fprintf(stderr, "action inconnue : %s (attendu : add|up|del)\n", action);
    return 2;
}
