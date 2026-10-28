Python

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
X1000 PHOENIX - Moteur de collecte PMU 3.0

- Collecte des reunions et courses
- Recuperation des partants PMU
- Detection des non-partants
- Gestion des erreurs reseau
- Reessais automatiques
- Horaires Europe/Paris
- Publication atomique JSON
- Diagnostic de collecte
- Aucune donnee hippique inventee

Execution :
    python pmu_engine.py

Date particuliere :
    python pmu_engine.py --date 2026-10-28

Test sans reseau :
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
import time
import urllib.error
import urllib.request

from pathlib import Path
from zoneinfo import ZoneInfo


# ==========================================
# CONFIGURATION
# ==========================================

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

RETRY_HTTP = {408, 429, 500, 502, 503, 504}

USER_AGENT = (
    "Mozilla/5.0 "
    "(compatible; X1000-PHOENIX/3.0)"
)


# ==========================================
# OUTILS
# ==========================================

def maintenant():
    return dt.datetime.now(PARIS)


def entier(valeur):
    if valeur is None or isinstance(valeur, bool):
        return None

    try:
        n = int(valeur)
        return n if n >= 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def nombre(valeur):
    if valeur is None or isinstance(valeur, bool):
        return None

    try:
        if isinstance(valeur, str):
            valeur = re.sub(
                r"[\s\u00a0\u202f€]",
                "",
                valeur
            )
            valeur = valeur.replace(",", ".")

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
            resultat = valeur.get(cle)

            if isinstance(resultat, str):
                return resultat.strip()

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


def depart_paris(valeur, jour=None):
    if valeur is None or isinstance(valeur, bool):
        return None

    if isinstance(valeur, (int, float)):
        try:
            timestamp = float(valeur)

            if not math.isfinite(timestamp):
                return None

            if timestamp <= 0:
                return None

            if timestamp > 100000000000:
                timestamp /= 1000

            return dt.datetime.fromtimestamp(
                timestamp,
                PARIS
            ).isoformat()

        except (ValueError, OverflowError, OSError):
            return None

    if isinstance(valeur, str):
        valeur = valeur.strip()

        if valeur.isdigit():
            return depart_paris(int(valeur), jour)

        try:
            instant = dt.datetime.fromisoformat(
                valeur.replace("Z", "+00:00")
            )

            if instant.tzinfo is None:
                return None

            return instant.astimezone(PARIS).isoformat()

        except ValueError:
            pass

        if jour is not None:
            try:
                heure = dt.time.fromisoformat(valeur)
                instant = dt.datetime.combine(
                    jour,
                    heure,
                    tzinfo=PARIS
                )
                return instant.isoformat()
            except ValueError:
                pass

    return None


# ==========================================
# REQUETES API
# ==========================================

def obtenir(url):
    derniere_erreur = None

    for tentative in range(1, TENTATIVES + 1):
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
                    raise ValueError(
                        f"HTTP {reponse.status}"
                    )

                contenu = reponse.read()

                if not contenu:
                    raise ValueError(
                        "Reponse API vide"
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

            attente = 0

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
            json.JSONDecodeError,
            UnicodeDecodeError,
            ValueError
        ) as erreur:
            derniere_erreur = erreur
            attente = 0

        if tentative < TENTATIVES:
            delai = min(
                15,
                2 ** (tentative - 1)
                + random.uniform(0, 0.5)
            )

            time.sleep(max(delai, attente))

    raise RuntimeError(
        f"API inaccessible apres {TENTATIVES} "
        f"tentatives: {derniere_erreur}"
    )


# ==========================================
# NORMALISATION DES PARTANTS
# ==========================================

def normaliser_participant(participant, source):
    if not isinstance(participant, dict):
        return None

    numero = entier(
        premier(
            participant,
            "numPmu",
            "numero",
            "num"
        )
    )

    if numero is None or numero < 1:
        return None

    nom = texte(
        premier(
            participant,
            "nom",
            "nomCheval"
        )
    )

    if not nom:
        return None

    statut = texte(
        participant.get("statut")
    ).upper().replace(" ", "_").replace("-", "_")

    non_partant = (
        statut in (
            "NON_PARTANT",
            "NONPARTANT",
            "NP",
            "FORFAIT"
        )
        or participant.get("nonPartant") is True
    )

    gains = nombre(
        premier(
            participant,
            "gainCarriere",
            "gains",
            "gainTotal"
        )
    )

    jockey = texte(
        participant.get("jockey")
    )

    driver = texte(
        participant.get("driver")
    )

    entraineur = texte(
        participant.get("entraineur")
    )

    return {
        "numero": numero,
        "nom": nom,
        "non_partant": non_partant,
        "statut": statut or "NON_RENSEIGNE",
        "musique": musique(
            participant.get("musique")
        ),
        "gains": gains,
        "jockey": jockey,
        "driver": driver,
        "entraineur": entraineur,
        "age": entier(
            participant.get("age")
        ),
        "sexe": texte(
            participant.get("sexe")
        ),
        "source": source
    }


# ==========================================
# LECTURE DES STRUCTURES PMU
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
        participants = donnees.get("participants")

        if isinstance(participants, list):
            return participants

    raise ValueError(
        "Liste des participants absente"
    )


def reunion_francaise(reunion):
    """
    Filtrage prudent :
    on exclut seulement les reunions explicitement
    identifiees comme etrangeres.

    Une localisation inconnue reste non verifiee.
    """

    pays = premier(
        reunion,
        "pays",
        "codePays",
        "paysCode"
    )

    if pays is None:
        hippo = reunion.get("hippodrome")

        if isinstance(hippo, dict):
            pays = premier(
                hippo,
                "pays",
                "codePays",
                "paysCode"
            )

    if pays is None:
        return None

    code = texte(pays).upper()

    if code in (
        "FR",
        "FRA",
        "FRANCE"
    ):
        return True

    return False


# ==========================================
# COLLECTE PRINCIPALE
# ==========================================

def collecter(jour=None):
    debut = maintenant()

    if jour is None:
        jour = debut.date()

    if isinstance(jour, str):
        jour = dt.date.fromisoformat(jour)

    if not isinstance(jour, dt.date):
        raise ValueError("Date invalide")

    date_api = jour.strftime("%d%m%Y")

    programme_url = (
        f"{API}/programme/{date_api}"
    )

    rapport = {
        "version": "3.0",
        "date": jour.isoformat(),
        "collecte_a": debut.isoformat(),
        "source": programme_url,
        "statut": "EN_COURS",
        "courses": [],
        "erreurs": [],
        "avertissements": [],
        "statistiques": {}
    }

    try:
        programme = obtenir(programme_url)
        reunions = extraire_reunions(programme)

    except Exception as erreur:
        rapport["erreurs"].append(
            f"Programme inaccessible: {erreur}"
        )

        rapport["statut"] = "ECHEC"

        rapport["statistiques"] = {
            "reunions": 0,
            "courses": 0,
            "partants": 0,
            "non_partants": 0,
            "erreurs": len(rapport["erreurs"])
        }

        return rapport

    nb_reunions = 0
    nb_courses_vues = 0

    for reunion in reunions:
        if not isinstance(reunion, dict):
            continue

        nr = entier(
            premier(
                reunion,
                "numOfficiel",
                "numReunion"
            )
        )

        if nr is None or nr < 1:
            rapport["avertissements"].append(
                "Reunion sans numero exploitable"
            )
            continue

        localisation = reunion_francaise(reunion)

        # Seules les reunions explicitement
        # etrangeres sont exclues.
        if localisation is False:
            continue

        nb_reunions += 1

        hippodrome = texte(
            reunion.get("hippodrome")
        )

        courses = reunion.get("courses")

        if not isinstance(courses, list):
            rapport["erreurs"].append(
                f"R{nr}: liste des courses invalide"
            )
            continue

        for info in courses:
            if not isinstance(info, dict):
                continue

            nc = entier(
                premier(
                    info,
                    "numOrdre",
                    "numCourse"
                )
            )

            if nc is None or nc < 1:
                continue

            nb_courses_vues += 1

            identifiant = (
                f"{jour.isoformat()}-R{nr}-C{nc}"
            )

            url = (
                f"{API}/programme/{date_api}"
                f"/R{nr}/C{nc}/participants"
            )

            try:
                donnees = obtenir(url)

                participants = extraire_participants(
                    donnees
                )

                chevaux = []
                numeros = set()

                for participant in participants:
                    cheval = normaliser_participant(
                        participant,
                        url
                    )

                    if cheval is None:
                        continue

                    numero = cheval["numero"]

                    if numero in numeros:
                        rapport["avertissements"].append(
                            f"{identifiant}: "
                            f"numero {numero} duplique"
                        )
                        continue

                    numeros.add(numero)
                    chevaux.append(cheval)

                if not chevaux:
                    raise ValueError(
                        "Aucun partant exploitable"
                    )

                chevaux.sort(
                    key=lambda cheval: cheval["numero"]
                )

                depart = depart_paris(
                    premier(
                        info,
                        "heureDepart",
                        "heureDepartPrevue"
                    ),
                    jour
                )

                if depart is None:
                    rapport["avertissements"].append(
                        f"{identifiant}: "
                        "heure de depart indisponible"
                    )

                non_partants = [
                    cheval["numero"]
                    for cheval in chevaux
                    if cheval["non_partant"]
                ]

                rapport["courses"].append({
                    "id": identifiant,
                    "reunion": nr,
                    "course": nc,
                    "hippodrome": hippodrome,
                    "localisation_france_verifiee": (
                        localisation is True
                    ),
                    "nom": texte(
                        premier(
                            info,
                            "libelle",
                            "libelleLong"
                        )
                    ),
                    "depart": depart,
                    "depart_verifie": depart is not None,
                    "nombre_participants": len(chevaux),
                    "nombre_partants": (
                        len(chevaux) - len(non_partants)
                    ),
                    "non_partants": non_partants,
                    "partants": chevaux,
                    "source": url,
                    "collecte_a": maintenant().isoformat(),
                    "statut": "PARTANTS_CHARGES"
                })

                time.sleep(PAUSE)

            except Exception as erreur:
                rapport["erreurs"].append(
                    f"{identifiant}: {erreur}"
                )

    rapport["courses"].sort(
        key=lambda course: (
            course["depart"] is None,
            course["depart"] or "",
            course["reunion"],
            course["course"]
        )
    )

    total_partants = sum(
        course["nombre_partants"]
        for course in rapport["courses"]
    )

    total_np = sum(
        len(course["non_partants"])
        for course in rapport["courses"]
    )

    rapport["statistiques"] = {
        "reunions": nb_reunions,
        "courses_prevues": nb_courses_vues,
        "courses": len(rapport["courses"]),
        "partants": total_partants,
        "non_partants": total_np,
        "erreurs": len(rapport["erreurs"])
    }

    if rapport["courses"]:
        if rapport["erreurs"]:
            rapport["statut"] = "PARTIEL"
        else:
            rapport["statut"] = "OK"

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

    temporaire = chemin.with_name(
        chemin.name + ".tmp"
    )

    try:
        temporaire.write_text(
            json.dumps(
                contenu,
                ensure_ascii=False,
                indent=2,
                allow_nan=False
            ),
            encoding="utf-8"
        )

        os.replace(
            temporaire,
            chemin
        )

    finally:
        if temporaire.exists():
            temporaire.unlink()


# ==========================================
# TESTS LOCAUX
# ==========================================

def self_test():
    assert entier("12") == 12
    assert entier(-1) is None
    assert entier(True) is None

    assert nombre("1 234,50 €") == 1234.5
    assert nombre("NaN") is None

    assert depart_paris(
        "2026-10-28T12:00:00+01:00"
    ) is not None

    cheval = normaliser_participant(
        {
            "numPmu": 4,
            "nom": "CHEVAL TEST",
            "statut": "NON_PARTANT"
        },
        "test"
    )

    assert cheval is not None
    assert cheval["numero"] == 4
    assert cheval["non_partant"] is True

    assert extraire_participants(
        {"participants": []}
    ) == []

    print("X1000 PHOENIX : tests locaux OK")


# ==========================================
# EXECUTION
# ==========================================

def main():
    parser = argparse.ArgumentParser(
        description="Collecte PMU X1000 PHOENIX"
    )

    parser.add_argument(
        "--date",
        default=None,
        help="Date au format AAAA-MM-JJ"
    )

    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Verifier les fonctions sans reseau"
    )

    arguments = parser.parse_args()

    if arguments.self_test:
        self_test()
        return 0

    try:
        resultat = collecter(arguments.date)

    except (ValueError, TypeError) as erreur:
        print(
            f"ERREUR: {erreur}",
            file=sys.stderr
        )
        return 2

    destination = DATA / "collecte.json"

    # Ne pas remplacer une collecte valide
    # par une collecte vide en cas de panne.
    if (
        resultat["statut"] == "ECHEC"
        and destination.exists()
    ):
        enregistrer_json(
            DATA / "collecte_erreur.json",
            resultat
        )

        print(
            "ECHEC: ancienne collecte conservee."
        )
        return 1

    enregistrer_json(
        destination,
        resultat
    )

    statistiques = resultat["statistiques"]

    print("=" * 48)
    print("X1000 PHOENIX - COLLECTE PMU")
    print("=" * 48)

    print("Date :", resultat["date"])
    print("Statut :", resultat["statut"])
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

    for erreur in resultat["erreurs"]:
        print("ALERTE :", erreur)

    for avertissement in resultat["avertissements"]:
        print("INFO :", avertissement)

    print("Fichier :", destination)
    print("=" * 48)

    if resultat["statut"] == "ECHEC":
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
