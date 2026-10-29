#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
X1000 PHOENIX - ANALYSEUR M1-M5
Version unifiee 5.0

- Compatible pmu_engine.py 5.0
- Lecture des collectes PMU
- Analyse M1 a M5
- Controle des non-partants
- Classements heuristiques
- Horodatage Europe/Paris
- Aucun FIGE automatique
- Aucun pronostic retroactif
- Aucune probabilite inventee
- Publication atomique JSON
- Tests locaux sans reseau

Execution :
    python analyser_moteurs.py

Tests :
    python analyser_moteurs.py --self-test
"""

import argparse
import datetime as dt
import json
import math
import os
import re
import sys
import tempfile

from pathlib import Path
from zoneinfo import ZoneInfo


# ==========================================
# CONFIGURATION
# ==========================================

VERSION = "5.0"

PARIS = ZoneInfo("Europe/Paris")

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

SOURCE_COLLECTE = DATA / "collecte.json"
SOURCE_PUBLICATION = DATA / "publication_courses.json"

DEST = DATA / "publication_analyses.json"

MOTEURS = ("M1", "M2", "M3", "M4", "M5")

MAX_MUSIQUE = 10
MAX_CLASSEMENT = 5


# ==========================================
# TEMPS
# ==========================================

def maintenant():
    return dt.datetime.now(PARIS)


def instant_utc(valeur=None):
    if valeur is None:
        return dt.datetime.now(dt.timezone.utc)

    if isinstance(valeur, str):
        valeur = dt.datetime.fromisoformat(
            valeur.replace("Z", "+00:00")
        )

    if (
        not isinstance(valeur, dt.datetime)
        or valeur.tzinfo is None
        or valeur.utcoffset() is None
    ):
        raise ValueError(
            "Date ou heure sans fuseau horaire"
        )

    return valeur.astimezone(dt.timezone.utc)


def instant_paris(valeur=None):
    return instant_utc(valeur).astimezone(PARIS)


# ==========================================
# VALIDATION
# ==========================================

def numero_cheval(valeur):
    if type(valeur) is int and valeur > 0:
        return valeur

    if isinstance(valeur, str):
        valeur = valeur.strip()

        if re.fullmatch(r"[1-9]\d*", valeur):
            return int(valeur)

    raise ValueError(
        "Numero de cheval invalide"
    )


def non_partant(cheval):
    statut = str(
        cheval.get("statut") or ""
    ).strip().upper()

    statut = statut.replace(
        "-", "_"
    ).replace(
        " ", "_"
    )

    return (
        cheval.get("non_partant") is True
        or statut in (
            "NON_PARTANT",
            "NONPARTANT",
            "NP",
            "FORFAIT"
        )
    )


def identifiant_course(course):
    cid = (
        course.get("id")
        or course.get("course_id")
    )

    if (
        cid is None
        or isinstance(cid, bool)
        or not str(cid).strip()
    ):
        raise ValueError(
            "Identifiant de course absent"
        )

    return str(cid).strip()


# ==========================================
# MUSIQUE DES CHEVAUX
# ==========================================

def musique(valeur):
    """
    Extrait les classements chiffres.

    Les lettres A, D, T et J ne sont pas
    converties en classements.

    Les codes zero ne sont pas interpretes
    comme des victoires.
    """

    if isinstance(valeur, list):
        valeur = " ".join(
            str(x)
            for x in valeur
            if x is not None
        )

    texte = str(valeur or "")

    texte = re.sub(
        r"\(\d{2,4}\)",
        "",
        texte
    )

    resultats = []

    correspondances = re.findall(
        r"(\d+|[AaDdTtJj])([pPhHsSmMaA])",
        texte
    )

    for rang, discipline in correspondances:
        if not rang.isdigit():
            continue

        n = int(rang)

        if n > 0:
            resultats.append(n)

        if len(resultats) >= MAX_MUSIQUE:
            break

    return resultats


# ==========================================
# INDICATEURS
# ==========================================

def indicateurs(cheval):
    rangs = musique(
        cheval.get("musique")
    )

    if not rangs:
        return None

    points = [
        max(
            0.0,
            12 - min(n, 12)
        ) / 11
        for n in rangs
    ]

    poids = (
        0.5,
        0.3,
        0.2
    )[:min(3, len(points))]

    forme = sum(
        p * w
        for p, w in zip(points, poids)
    ) / sum(poids)

    regularite = (
        sum(n <= 3 for n in rangs)
        / len(rangs)
    )

    victoires = (
        sum(n == 1 for n in rangs)
        / len(rangs)
    )

    constance = (
        sum(points) / len(points)
    )

    confiance = min(
        1.0,
        len(rangs) / 5
    )

    return {
        "forme": forme,
        "regularite": regularite,
        "victoires": victoires,
        "constance": constance,
        "confiance_donnees": confiance,
        "courses_musique": len(rangs)
    }


# ==========================================
# SCORES M1-M5
# ==========================================

def scores(cheval):
    valeurs = indicateurs(cheval)

    if valeurs is None:
        return None

    forme = valeurs["forme"]
    regularite = valeurs["regularite"]
    victoires = valeurs["victoires"]
    constance = valeurs["constance"]
    confiance = valeurs["confiance_donnees"]

    resultats = {
        "M1": (
            0.75 * forme
            + 0.25 * constance
        ),

        "M2": (
            0.75 * regularite
            + 0.25 * constance
        ),

        "M3": (
            0.65 * victoires
            + 0.35 * forme
        ),

        "M4": (
            0.60 * regularite
            + 0.25 * constance
            + 0.15 * confiance
        ),

        "M5": (
            0.30 * forme
            + 0.30 * regularite
            + 0.20 * victoires
            + 0.20 * confiance
        )
    }

    for moteur, valeur in resultats.items():
        if not math.isfinite(valeur):
            raise ValueError(
                f"Score invalide pour {moteur}"
            )

    return resultats


# ==========================================
# ANALYSE D'UNE COURSE
# ==========================================

def analyser(course, instant=None):
    """
    Analyse exploratoire.

    Ne cree pas de FIGE.
    Ne valide aucun pari.
    """

    if not isinstance(course, dict):
        raise ValueError(
            "Course invalide"
        )

    cid = identifiant_course(course)

    depart_str = course.get("depart")

    if not isinstance(depart_str, str):
        raise ValueError(
            "Heure de depart absente"
        )

    depart = instant_utc(depart_str)
    analyse_a = instant_utc(instant)

    bruts = course.get("partants")

    if not isinstance(bruts, list):
        raise ValueError(
            "Liste des partants absente"
        )

    if not bruts:
        raise ValueError(
            "Aucun participant"
        )

    numeros = set()
    actifs = []
    candidats = []

    for cheval in bruts:
        if not isinstance(cheval, dict):
            raise ValueError(
                "Fiche cheval invalide"
            )

        numero = numero_cheval(
            cheval.get("numero")
        )

        if numero in numeros:
            raise ValueError(
                f"Numero duplique : {numero}"
            )

        numeros.add(numero)

        if non_partant(cheval):
            continue

        actifs.append(numero)

        valeurs = scores(cheval)

        if valeurs is None:
            continue

        candidats.append({
            "numero": numero,
            "nom": str(
                cheval.get("nom") or ""
            ).strip(),
            "scores": valeurs,
            "indicateurs": indicateurs(cheval)
        })

    moteurs = []

    for nom in MOTEURS:
        classement = sorted(
            candidats,
            key=lambda c: (
                -c["scores"][nom],
                c["numero"]
            )
        )

        ordre = [
            c["numero"]
            for c in classement
        ]

        top = ordre[:MAX_CLASSEMENT]

        moteurs.append({
            "moteur": nom,
            "gagnant_espere": (
                top[0] if top else None
            ),
            "meilleur_place": (
                top[1]
                if len(top) > 1
                else None
            ),
            "ordre_espere": top,
            "ordre_arrivee_espere": top,
            "classement_complet": ordre,
            "scores": {
                str(c["numero"]): round(
                    c["scores"][nom],
                    6
                )
                for c in classement
            },
            "qualification": "ETUDE_NON_VALIDEE",
            "validation": "NON_FIGE",
            "pari_retenu": None,
            "fige": False
        })

    france_verifiee = (
        course.get(
            "localisation_france_verifiee"
        ) is True
    )

    depart_verifie = (
        course.get(
            "depart_verifie"
        ) is True
    )

    avant_depart = analyse_a < depart

    donnees_suffisantes = (
        len(candidats) >= 2
    )

    eligible = (
        france_verifiee
        and depart_verifie
        and avant_depart
        and donnees_suffisantes
    )

    if not candidats:
        statut = "DONNEES_INSUFFISANTES"

    elif not avant_depart:
        statut = "ANALYSE_HORS_DELAI"

    else:
        statut = "ANALYSE_EXPLORATOIRE"

    return {
        "id": cid,
        "course_id": cid,
        "reunion": course.get("reunion"),
        "course": course.get("course"),
        "hippodrome": course.get("hippodrome"),
        "nom": course.get("nom"),
        "depart": depart_str,
        "source": course.get("source"),
        "collecte_a": course.get("collecte_a"),
        "analyse_a": analyse_a.astimezone(
            PARIS
        ).isoformat(),
        "nombre_partants": len(actifs),
        "chevaux_evalues": len(candidats),
        "chevaux_sans_musique": (
            len(actifs) - len(candidats)
        ),
        "moteurs": moteurs,
        "statut": statut,
        "qualification": "ETUDE_NON_VALIDEE",
        "validation": "NON_FIGE",
        "fige": False,
        "pari_officiel": False,
        "eligible_fige": eligible,
        "controles": {
            "france_verifiee": france_verifiee,
            "depart_verifie": depart_verifie,
            "avant_depart": avant_depart,
            "donnees_suffisantes": donnees_suffisantes
        },
        "avertissement": (
            "Classements heuristiques bases "
            "uniquement sur la musique. "
            "Les scores ne sont pas des "
            "probabilites de victoire. "
            "Aucun pari valide ou FIGE "
            "n'est cree par cet analyseur."
        )
    }


# ==========================================
# LECTURE JSON
# ==========================================

def lire_json(chemin):
    with chemin.open(
        "r",
        encoding="utf-8"
    ) as fichier:
        return json.load(fichier)


def charger_courses():
    """
    Priorite a la collecte PMU.

    La publication est utilisee en secours
    si la collecte n'existe pas ou si son
    format est invalide.
    """

    erreurs = []

    for chemin in (
        SOURCE_COLLECTE,
        SOURCE_PUBLICATION
    ):
        if not chemin.is_file():
            continue

        try:
            donnees = lire_json(chemin)

            if not isinstance(donnees, dict):
                raise ValueError(
                    "Document JSON non objet"
                )

            courses = donnees.get("courses")

            if not isinstance(courses, list):
                raise ValueError(
                    "Champ courses invalide"
                )

            if donnees.get("statut") == "ECHEC":
                raise ValueError(
                    "Collecte en echec"
                )

            return courses, chemin, donnees

        except (
            OSError,
            ValueError,
            TypeError,
            json.JSONDecodeError
        ) as erreur:
            erreurs.append(
                f"{chemin.name}: {erreur}"
            )

    raise ValueError(
        "Aucune source de courses exploitable. "
        + " | ".join(erreurs)
    )


# ==========================================
# SAUVEGARDE ATOMIQUE
# ==========================================

def ecrire_atomique(chemin, document):
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
            prefix=".analyses_",
            suffix=".tmp",
            delete=False
        ) as fichier:

            temporaire = Path(fichier.name)

            json.dump(
                document,
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
    assert musique("1p2p3p") == [1, 2, 3]
    assert musique("ApDp") == []
    assert musique("0p1p") == [1]

    cheval = {
        "numero": 4,
        "nom": "CHEVAL TEST",
        "musique": "1p2p3p",
        "non_partant": False
    }

    valeurs = scores(cheval)

    assert valeurs is not None
    assert set(valeurs) == set(MOTEURS)

    course = {
        "id": "2026-10-29-R1-C1",
        "depart": "2026-10-29T15:00:00+01:00",
        "localisation_france_verifiee": True,
        "depart_verifie": True,
        "partants": [
            cheval,
            {
                "numero": 5,
                "nom": "AUTRE CHEVAL",
                "musique": "2p1p4p",
                "non_partant": False
            },
            {
                "numero": 6,
                "nom": "NON PARTANT",
                "musique": "1p1p",
                "non_partant": True
            }
        ]
    }

    instant = (
        "2026-10-29T12:00:00+01:00"
    )

    resultat = analyser(course, instant)

    assert len(resultat["moteurs"]) == 5
    assert resultat["nombre_partants"] == 2
    assert resultat["chevaux_evalues"] == 2
    assert resultat["fige"] is False
    assert resultat["eligible_fige"] is True

    apres = analyser(
        course,
        "2026-10-29T16:00:00+01:00"
    )

    assert apres["eligible_fige"] is False
    assert apres["statut"] == "ANALYSE_HORS_DELAI"

    print(
        "X1000 PHOENIX : "
        "tests M1-M5 OK"
    )


# ==========================================
# EXECUTION PRINCIPALE
# ==========================================

def main():
    parser = argparse.ArgumentParser(
        description=(
            "X1000 PHOENIX - "
            "Analyse heuristique M1-M5"
        )
    )

    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Tests sans reseau"
    )

    arguments = parser.parse_args()

    if arguments.self_test:
        self_test()
        return 0

    try:
        courses, source, donnees = charger_courses()

    except (ValueError, OSError) as erreur:
        print(
            f"ERREUR SOURCE : {erreur}",
            file=sys.stderr
        )
        return 1

    instant = maintenant()

    analyses = []
    erreurs = []
    ignorees = 0

    for course in courses:
        try:
            if not isinstance(course, dict):
                raise ValueError(
                    "Course invalide"
                )

            if (
                course.get(
                    "localisation_france_verifiee"
                ) is not True
                or course.get(
                    "depart_verifie"
                ) is not True
            ):
                ignorees += 1
                continue

            analyses.append(
                analyser(course, instant)
            )

        except (
            KeyError,
            TypeError,
            ValueError,
            OverflowError
        ) as erreur:
            erreurs.append({
                "id": (
                    course.get("id")
                    or course.get("course_id")
                ) if isinstance(course, dict) else None,
                "erreur": str(erreur)
            })

    if not analyses and courses:
        print(
            "ALERTE : aucune analyse exploitable. "
            "Publication precedente preservee.",
            file=sys.stderr
        )
        return 1

    payload = {
        "version": VERSION,
        "genere_a": instant.isoformat(),
        "source": str(
            source.relative_to(ROOT)
        ),
        "date_source": donnees.get("date"),
        "analyses": analyses,
        "erreurs": erreurs,
        "courses_ignorees": ignorees,
        "statistiques": {
            "courses_source": len(courses),
            "courses_analysees": len(analyses),
            "courses_ignorees": ignorees,
            "erreurs": len(erreurs),
            "moteurs": len(MOTEURS)
        }
    }

    try:
        ecrire_atomique(DEST, payload)

    except (OSError, ValueError) as erreur:
        print(
            f"ERREUR PUBLICATION : {erreur}",
            file=sys.stderr
        )
        return 1

    print("=" * 50)
    print("X1000 PHOENIX - M1-M5")
    print("=" * 50)
    print("Source :", source)
    print("Courses :", len(analyses))
    print("Ignorees :", ignorees)
    print("Erreurs :", len(erreurs))
    print("Destination :", DEST)
    print("=" * 50)

    return 0


if __name__ == "__main__":
    sys.exit(main())
