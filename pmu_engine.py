#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
X1000 PHOENIX - MOTEUR PMU UNIFIE 5.0

Collecte officielle des donnees disponibles
depuis l'API PMU configuree.

- Reunions et courses
- Partants et non-partants
- Filtrage France
- Horaires Europe/Paris
- Controle des donnees
- Reessais reseau
- JSON atomique
- Historique preserve en cas d'echec
- Diagnostic exploitable
- Aucune donnee hippique inventee

Commandes :
 python pmu_engine.py
 python pmu_engine.py --date 2026-10-29
 python pmu_engine.py --self-test
"""

import argparse
import datetime as dt
import json
import math
import os
import random
import re
import socket
import sys
import tempfile
import time
import urllib.error
import urllib.request

from pathlib import Path
from zoneinfo import ZoneInfo


# ==========================================
# CONFIGURATION
# ==========================================

VERSION = "5.0"

PARIS = ZoneInfo("Europe/Paris")

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

API = os.getenv(
    "PMU_API_BASE",
    "https://online.turfinfo.api.pmu.fr/rest/client/7"
).rstrip("/")

TIMEOUT = 15
TENTATIVES = 3
PAUSE = 0.15

TAILLE_MAX = 8_000_000

RETRY_HTTP = {
    408, 429, 500, 502, 503, 504
}

USER_AGENT = (
    "Mozilla/5.0 "
    "(compatible; X1000-PHOENIX/5.0)"
)


# ==========================================
# OUTILS GENERAUX
# ==========================================

def maintenant():
    return dt.datetime.now(PARIS)


def entier(valeur):
    if valeur is None or isinstance(valeur, bool):
        return None

    try:
        if isinstance(valeur, float):
            if not math.isfinite(valeur):
                return None
            if not valeur.is_integer():
                return None

        if isinstance(valeur, str):
            valeur = valeur.strip()
            if not re.fullmatch(r"\d+", valeur):
                return None

        n = int(valeur)
        return n if n >= 0 else None

    except (TypeError, ValueError, OverflowError):
        return None


def entier_positif(valeur):
    n = entier(valeur)
    return n if n is not None and n > 0 else None


def nombre(valeur):
    if valeur is None or isinstance(valeur, bool):
        return None

    try:
        if isinstance(valeur, str):
            valeur = re.sub(
                r"[\s\u00a0\u202f€]",
                "",
                valeur
            ).replace(",", ".")

        n = float(valeur)

        if not math.isfinite(n) or n < 0:
            return None

        return n

    except (TypeError, ValueError, OverflowError):
        return None


def texte(valeur):
    if isinstance(valeur, str):
        return valeur.strip()

    if isinstance(valeur, dict):
        for cle in (
            "nom",
            "libelleLong",
            "libelle",
            "name"
        ):
            v = valeur.get(cle)
            if isinstance(v, str) and v.strip():
                return v.strip()

    return ""


def premier(objet, *cles):
    if not isinstance(objet, dict):
        return None

    for cle in cles:
        valeur = objet.get(cle)
        if valeur is not None and valeur != "":
            return valeur

    return None


def musique(valeur):
    if isinstance(valeur, str):
        return valeur.strip()

    if isinstance(valeur, list):
        return " ".join(
            str(x) for x in valeur
            if x is not None
        )

    return ""


# ==========================================
# HORAIRES PARIS
# ==========================================

def depart_paris(valeur, jour=None):
    if valeur is None or isinstance(valeur, bool):
        return None

    try:
        if isinstance(valeur, (int, float)):
            n = float(valeur)

            if not math.isfinite(n) or n <= 0:
                return None

            if n > 100_000_000_000:
                n /= 1000

            return dt.datetime.fromtimestamp(
                n, PARIS
            ).isoformat()

        if isinstance(valeur, str):
            valeur = valeur.strip()

            if valeur.isdigit():
                return depart_paris(int(valeur), jour)

            try:
                instant = dt.datetime.fromisoformat(
                    valeur.replace("Z", "+00:00")
                )

                if instant.tzinfo is not None:
                    return instant.astimezone(
                        PARIS
                    ).isoformat()

            except ValueError:
                pass

            if jour is not None:
                heure = dt.time.fromisoformat(valeur)

                if heure.tzinfo is not None:
                    return None

                return dt.datetime.combine(
                    jour,
                    heure,
                    tzinfo=PARIS
                ).isoformat()

    except (
        ValueError,
        OverflowError,
        OSError,
        TypeError
    ):
        pass

    return None


# ==========================================
# API PMU
# ==========================================

def obtenir(url):
    derniere_erreur = None

    for tentative in range(TENTATIVES):
        attente = 0

        requete = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Accept-Language": "fr-FR,fr;q=0.9"
            }
        )

        try:
            with urllib.request.urlopen(
                requete,
                timeout=TIMEOUT
            ) as reponse:

                if reponse.status != 200:
                    raise RuntimeError(
                        f"HTTP {reponse.status}"
                    )

                contenu = reponse.read(
                    TAILLE_MAX + 1
                )

                if not contenu:
                    raise ValueError(
                        "Reponse API vide"
                    )

                if len(contenu) > TAILLE_MAX:
                    raise ValueError(
                        "Reponse API trop volumineuse"
                    )

                return json.loads(
                    contenu.decode("utf-8-sig")
                )

        except urllib.error.HTTPError as erreur:
            derniere_erreur = erreur

            if erreur.code not in RETRY_HTTP:
                raise RuntimeError(
                    f"HTTP {erreur.code}: {url}"
                ) from erreur

            if erreur.code == 429:
                retry_after = erreur.headers.get(
                    "Retry-After"
                )

                if retry_after:
                    try:
                        attente = min(
                            30,
                            max(0, int(retry_after))
                        )
                    except ValueError:
                        pass

        except (
            urllib.error.URLError,
            TimeoutError,
            socket.timeout,
            ConnectionError,
            OSError,
            json.JSONDecodeError,
            UnicodeDecodeError,
            ValueError,
            RuntimeError
        ) as erreur:
            derniere_erreur = erreur

        if tentative < TENTATIVES - 1:
            delai = min(
                15,
                2 ** tentative
                + random.uniform(0, 0.5)
            )

            time.sleep(max(delai, attente))

    raise RuntimeError(
        "API inaccessible apres "
        f"{TENTATIVES} tentatives : "
        f"{derniere_erreur}"
    )


# ==========================================
# LOCALISATION
# ==========================================

def reunion_francaise(reunion):
    pays = premier(
        reunion,
        "pays",
        "codePays",
        "paysCode"
    )

    hippo = reunion.get("hippodrome")

    if pays is None and isinstance(hippo, dict):
        pays = premier(
            hippo,
            "pays",
            "codePays",
            "paysCode"
        )

    if pays is None:
        return None

    code = texte(pays).upper()

    if code in ("FR", "FRA", "FRANCE"):
        return True

    return False


# ==========================================
# NORMALISATION DES CHEVAUX
# ==========================================

def normaliser_participant(participant, source):
    if not isinstance(participant, dict):
        raise ValueError(
            "Participant non exploitable"
        )

    numero = entier_positif(
        premier(
            participant,
            "numPmu",
            "numero",
            "num"
        )
    )

    nom = texte(
        premier(
            participant,
            "nom",
            "nomCheval"
        )
    )

    if numero is None or not nom:
        raise ValueError(
            "Numero ou nom de cheval absent"
        )

    statut = texte(
        participant.get("statut")
    ).upper().replace(
        "-", "_"
    ).replace(
        " ", "_"
    )

    non_partant = (
        participant.get("nonPartant") is True
        or statut in (
            "NON_PARTANT",
            "NONPARTANT",
            "NP",
            "FORFAIT"
        )
    )

    return {
        "numero": numero,
        "nom": nom,
        "non_partant": non_partant,
        "statut": statut or "INCONNU",
        "musique": musique(
            participant.get("musique")
        ),
        "gains": nombre(
            premier(
                participant,
                "gainCarriere",
                "gains",
                "gainTotal"
            )
        ),
        "jockey": texte(
            participant.get("jockey")
        ),
        "driver": texte(
            participant.get("driver")
        ),
        "entraineur": texte(
            participant.get("entraineur")
        ),
        "age": entier(
            participant.get("age")
        ),
        "sexe": texte(
            participant.get("sexe")
        ),
        "source": source
    }


# ==========================================
# STRUCTURES PMU
# ==========================================

def extraire_reunions(programme):
    if not isinstance(programme, dict):
        raise ValueError(
            "Programme JSON invalide"
        )

    bloc = programme.get(
        "programme",
        programme
    )

    if not isinstance(bloc, dict):
        raise ValueError(
            "Bloc programme invalide"
        )

    reunions = bloc.get("reunions")

    if not isinstance(reunions, list):
        raise ValueError(
            "Liste des reunions absente"
        )

    return reunions


def extraire_participants(donnees):
    if isinstance(donnees, list):
        return donnees

    if isinstance(donnees, dict):
        participants = donnees.get(
            "participants"
        )

        if isinstance(participants, list):
            return participants

    raise ValueError(
        "Liste des participants absente"
    )


# ==========================================
# COLLECTE
# ==========================================

def collecter(jour=None):
    debut = maintenant()

    if jour is None:
        jour = debut.date()

    if isinstance(jour, str):
        jour = dt.date.fromisoformat(jour)

    if type(jour) is not dt.date:
        raise ValueError("Date invalide")

    date_api = jour.strftime("%d%m%Y")

    programme_url = (
        f"{API}/programme/{date_api}"
    )

    rapport = {
        "version": VERSION,
        "date": jour.isoformat(),
        "collecte_a": debut.isoformat(),
        "source": programme_url,
        "statut": "EN_COURS",
        "courses": [],
        "erreurs": [],
        "avertissements": [],
        "statistiques": {}
    }

    reunions_valides = set()
    courses_prevues = 0

    try:
        programme = obtenir(programme_url)
        reunions = extraire_reunions(programme)

    except Exception as erreur:
        rapport["erreurs"].append(
            f"Programme inaccessible : {erreur}"
        )

        rapport["statut"] = "ECHEC"
        rapport["statistiques"] = {
            "reunions": 0,
            "courses_prevues": 0,
            "courses": 0,
            "partants": 0,
            "non_partants": 0,
            "erreurs": 1
        }

        return rapport

    for reunion in reunions:
        if not isinstance(reunion, dict):
            continue

        localisation = reunion_francaise(
            reunion
        )

        if localisation is not True:
            if localisation is None:
                rapport["avertissements"].append(
                    "Reunion ignoree : "
                    "pays non verifie"
                )
            continue

        nr = entier_positif(
            premier(
                reunion,
                "numOfficiel",
                "numReunion"
            )
        )

        if nr is None:
            rapport["erreurs"].append(
                "Reunion francaise sans numero"
            )
            continue

        reunions_valides.add(nr)

        hippodrome = texte(
            reunion.get("hippodrome")
        )

        courses = reunion.get("courses")

        if not isinstance(courses, list):
            rapport["erreurs"].append(
                f"R{nr}: courses absentes"
            )
            continue

        for info in courses:
            if not isinstance(info, dict):
                continue

            nc = entier_positif(
                premier(
                    info,
                    "numOrdre",
                    "numCourse"
                )
            )

            if nc is None:
                rapport["avertissements"].append(
                    f"R{nr}: numero course absent"
                )
                continue

            courses_prevues += 1

            cid = (
                f"{jour.isoformat()}-R{nr}-C{nc}"
            )

            source = (
                f"{API}/programme/{date_api}"
                f"/R{nr}/C{nc}/participants"
            )

            try:
                donnees = obtenir(source)

                participants = extraire_participants(
                    donnees
                )

                if not participants:
                    raise ValueError(
                        "Liste des participants vide"
                    )

                chevaux = []
                numeros = set()

                for participant in participants:
                    cheval = normaliser_participant(
                        participant,
                        source
                    )

                    numero = cheval["numero"]

                    if numero in numeros:
                        raise ValueError(
                            f"Numero {numero} duplique"
                        )

                    numeros.add(numero)
                    chevaux.append(cheval)

                depart = depart_paris(
                    premier(
                        info,
                        "heureDepart",
                        "heureDepartPrevue"
                    ),
                    jour
                )

                if depart is None:
                    raise ValueError(
                        "Heure de depart indisponible"
                    )

                chevaux.sort(
                    key=lambda c: c["numero"]
                )

                non_partants = [
                    c["numero"]
                    for c in chevaux
                    if c["non_partant"]
                ]

                recu = maintenant().isoformat()

                rapport["courses"].append({
                    "id": cid,
                    "course_id": cid,
                    "reunion": nr,
                    "course": nc,
                    "hippodrome": hippodrome,
                    "localisation_france_verifiee": True,
                    "nom": texte(
                        premier(
                            info,
                            "libelle",
                            "libelleLong"
                        )
                    ),
                    "depart": depart,
                    "depart_verifie": True,
                    "nombre_participants": len(chevaux),
                    "nombre_partants": (
                        len(chevaux)
                        - len(non_partants)
                    ),
                    "non_partants": non_partants,
                    "partants": chevaux,
                    "source": source,
                    "collecte_a": recu,
                    "statut": "PARTANTS_CHARGES",
                    "controle_source": {
                        "programme_url": programme_url,
                        "participants_url": source,
                        "participants_recus_a": recu,
                        "mode": "API_REPONSE_DIRECTE",
                        "structure_validee": True
                    }
                })

                time.sleep(PAUSE)

            except Exception as erreur:
                rapport["erreurs"].append(
                    f"{cid}: {erreur}"
                )

    rapport["courses"].sort(
        key=lambda c: (
            c["depart"],
            c["reunion"],
            c["course"]
        )
    )

    rapport["statistiques"] = {
        "reunions": len(reunions_valides),
        "courses_prevues": courses_prevues,
        "courses": len(rapport["courses"]),
        "partants": sum(
            c["nombre_partants"]
            for c in rapport["courses"]
        ),
        "non_partants": sum(
            len(c["non_partants"])
            for c in rapport["courses"]
        ),
        "erreurs": len(rapport["erreurs"])
    }

    if rapport["courses"]:
        rapport["statut"] = (
            "PARTIEL"
            if rapport["erreurs"]
            else "OK"
        )

    elif rapport["erreurs"]:
        rapport["statut"] = "ECHEC"

    else:
        rapport["statut"] = "AUCUNE_COURSE"

    return rapport


# ==========================================
# SAUVEGARDE ATOMIQUE
# ==========================================

def enregistrer_json(chemin, contenu):
    chemin.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    temporaire = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=chemin.parent,
            prefix=chemin.name + ".",
            suffix=".tmp",
            delete=False
        ) as fichier:

            temporaire = Path(fichier.name)

            json.dump(
                contenu,
                fichier,
                ensure_ascii=False,
                indent=2,
                allow_nan=False
            )

            fichier.write("\n")
            fichier.flush()
            os.fsync(fichier.fileno())

        os.replace(
            temporaire,
            chemin
        )

    finally:
        if (
            temporaire is not None
            and temporaire.exists()
        ):
            temporaire.unlink()


# ==========================================
# TESTS LOCAUX
# ==========================================

def self_test():
    assert entier("12") == 12
    assert entier(-1) is None
    assert entier(True) is None
    assert entier("2.5") is None

    assert nombre("1 234,50 €") == 1234.5
    assert nombre("NaN") is None

    assert depart_paris(
        "2026-10-29T12:00:00+01:00"
    ) is not None

    cheval = normaliser_participant(
        {
            "numPmu": 4,
            "nom": "CHEVAL TEST",
            "statut": "NON_PARTANT"
        },
        "test"
    )

    assert cheval["numero"] == 4
    assert cheval["non_partant"] is True

    assert extraire_participants(
        {"participants": []}
    ) == []

    assert reunion_francaise(
        {"pays": "FR"}
    ) is True

    assert reunion_francaise(
        {"pays": "GB"}
    ) is False

    assert reunion_francaise(
        {}
    ) is None

    print(
        "X1000 PHOENIX 5.0 : "
        "tests locaux OK"
    )


# ==========================================
# EXECUTION
# ==========================================

def main():
    parser = argparse.ArgumentParser(
        description=(
            "X1000 PHOENIX - "
            "Collecte PMU unifiee"
        )
    )

    parser.add_argument(
        "--date",
        default=None,
        help="Date AAAA-MM-JJ"
    )

    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Tests sans reseau"
    )

    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    try:
        rapport = collecter(args.date)

    except (ValueError, TypeError) as erreur:
        print(
            f"ERREUR : {erreur}",
            file=sys.stderr
        )
        return 2

    destination = DATA / "collecte.json"

    if rapport["statut"] == "ECHEC":
        enregistrer_json(
            DATA / "collecte_erreur.json",
            rapport
        )

        print(
            "ECHEC : collecte precedente preservee"
        )

        for erreur in rapport["erreurs"]:
            print("ALERTE :", erreur)

        return 1

    enregistrer_json(
        destination,
        rapport
    )

    statistiques = rapport["statistiques"]

    print("=" * 50)
    print("X1000 PHOENIX - COLLECTE PMU 5.0")
    print("=" * 50)

    print("Date :", rapport["date"])
    print("Statut :", rapport["statut"])
    print(
        "Reunions :",
        statistiques["reunions"]
    )
    print(
        "Courses :",
        statistiques["courses"]
    )
    print(
        "Partants :",
        statistiques["partants"]
    )
    print(
        "Non-partants :",
        statistiques["non_partants"]
    )
    print(
        "Erreurs :",
        statistiques["erreurs"]
    )

    for erreur in rapport["erreurs"]:
        print("ALERTE :", erreur)

    for avertissement in rapport["avertissements"]:
        print("INFO :", avertissement)

    print("Fichier :", destination)
    print("=" * 50)

    return 0


if __name__ == "__main__":
    sys.exit(main())
