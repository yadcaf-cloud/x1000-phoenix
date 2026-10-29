
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
🇸🇳🧠🔥 X1000 PHOENIX
RENFORCEMENT CONSULTATIF M1-M5

Lecture seule : aucune modification du site,
des moteurs existants, des pronostics,
des tâches automatiques ou des FIGÉS.

Utilisation :
    python renforcement_m1_m5.py

Test :
    python renforcement_m1_m5.py --self-test

Course particulière :
    python renforcement_m1_m5.py --course 2026-10-29-R1-C1

Ce module n'effectue aucune publication.
"""

import argparse
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

SOURCES = (
    "publication_courses.json",
    "courses_verifiees.json",
    "collecte.json",
    "courses_pmu.json",
    "courses.json",
)

MOTEURS = ("M1", "M2", "M3", "M4", "M5")

# Pondérations heuristiques consultatives.
# Elles ne représentent pas des probabilités.
POIDS = {
    "M1": {
        "forme": 0.25,
        "regularite": 0.35,
        "aptitude": 0.25,
        "entourage": 0.15,
    },
    "M2": {
        "forme": 0.35,
        "regularite": 0.15,
        "aptitude": 0.35,
        "entourage": 0.15,
    },
    "M3": {
        "forme": 0.20,
        "regularite": 0.15,
        "aptitude": 0.40,
        "entourage": 0.25,
    },
    "M4": {
        "forme": 0.25,
        "regularite": 0.25,
        "aptitude": 0.35,
        "entourage": 0.15,
    },
    "M5": {
        "forme": 0.25,
        "regularite": 0.20,
        "aptitude": 0.30,
        "entourage": 0.25,
    },
}

def nombre(valeur):
    if valeur is None or isinstance(valeur, bool):
        return None
    try:
        x = float(str(valeur).replace(",", "."))
        return x if math.isfinite(x) else None
    except (ValueError, TypeError):
        return None


def score_borne(valeur):
    x = nombre(valeur)
    if x is None or not 0 <= x <= 100:
        return None
    return x


def premier(obj, *cles):
    for cle in cles:
        valeur = obj.get(cle)
        if valeur is not None and valeur != "":
            return valeur
    return None


def lire_courses():
    for nom in SOURCES:
        chemin = DATA / nom
        if not chemin.is_file():
            continue

        try:
            with chemin.open(encoding="utf-8") as f:
                contenu = json.load(f)
        except (OSError, ValueError) as exc:
            print(f"Source illisible : {nom} : {exc}")
            continue

        if isinstance(contenu, list):
            courses = contenu
        elif isinstance(contenu, dict):
            courses = premier(
                contenu, "courses", "courses_verifiees"
            )
        else:
            continue

        if isinstance(courses, list) and courses:
            return (
                [c for c in courses if isinstance(c, dict)],
                nom,
            )

    return [], None


def musique_positions(valeur):
    """
    Extrait les classements explicites des musiques
    françaises, sans transformer 0, D ou A en place.
    Exemples : 1a, 3a, Da, 2m, 4p.
    """
    if not isinstance(valeur, str):
        return []

    resultats = []
    for rang in re.findall(
        r"(\d+|D|A|T)[apmh]", valeur, re.I
    ):
        if rang.isdigit():
            n = int(rang)
            resultats.append(n if n > 0 else None)
        else:
            resultats.append(None)

    return resultats[:8]


def forme_musique(cheval):
    positions = musique_positions(
        premier(cheval, "musique", "historique")
    )
    if not positions:
        return None, None

    valeurs = []
    for rang in positions:
        if rang is None:
            valeurs.append(0)
        else:
            valeurs.append(max(0, 100 - (rang - 1) * 12))

    # Heuristique : les premiers résultats de la
    # musique sont supposés être les plus récents.
    poids = list(range(len(valeurs), 0, -1))
    forme = sum(
        v * p for v, p in zip(valeurs, poids)
    ) / sum(poids)

    places = sum(
        1 for rang in positions
        if rang is not None and rang <= 3
    )
    regularite = 100 * places / len(positions)

    return round(forme, 2), round(regularite, 2)


def evaluer_cheval(cheval):
    """
    Les scores complémentaires doivent être
    fournis par une source vérifiée.

    Valeurs attendues : 0 à 100.
    Absence = information indisponible.
    """
    forme, regularite = forme_musique(cheval)

    # Champs facultatifs : non présents dans la
    # collecte PMU standard.
    aptitude = score_borne(
        cheval.get("score_aptitude_verifie")
    )
    entourage = score_borne(
        cheval.get("score_entourage_verifie")
    )

    criteres = {
        "forme": forme,
        "regularite": regularite,
        "aptitude": aptitude,
        "entourage": entourage,
    }

    scores = {}
    couverture = {}

    for moteur, poids in POIDS.items():
        disponibles = {
            cle: valeur
            for cle, valeur in criteres.items()
            if valeur is not None
        }

        masse = sum(poids[k] for k in disponibles)

        if masse == 0:
            scores[moteur] = None
        else:
            scores[moteur] = round(
                sum(
                    disponibles[k] * poids[k]
                    for k in disponibles
                ) / masse,
                2,
            )

        couverture[moteur] = round(masse * 100, 1)

    manquants = [
        cle for cle, valeur in criteres.items()
        if valeur is None
    ]

    return {
        "numero": premier(cheval, "numero", "num"),
        "nom": premier(cheval, "nom", "cheval")
               or "Nom indisponible",
        "jockey_driver": premier(
            cheval, "jockey", "driver"
        ),
        "entraineur": cheval.get("entraineur"),
        "musique": cheval.get("musique"),
        "scores": scores,
        "couverture": couverture,
        "criteres": criteres,
        "manquants": manquants,
        "alertes": [],
    }


def est_non_partant(cheval):
    if cheval.get("non_partant") is True:
        return True
    statut = str(cheval.get("statut") or "").upper()
    return statut in ("NP", "NON_PARTANT", "NON-PARTANT")


def analyser_course(course):
    partants = course.get("partants")

    if not isinstance(partants, list):
        return {
            "statut": "DONNEES_INSUFFISANTES",
            "motif": "Liste des partants indisponible",
        }

    chevaux = [
        evaluer_cheval(c)
        for c in partants
        if isinstance(c, dict)
        and not est_non_partant(c)
    ]

    if not chevaux:
        return {
            "statut": "DONNEES_INSUFFISANTES",
            "motif": "Aucun partant exploitable",
        }

    classements = {}

    for moteur in MOTEURS:
        candidats = [
            c for c in chevaux
            if c["scores"][moteur] is not None
        ]

        classements[moteur] = sorted(
            candidats,
            key=lambda c: (
                -c["scores"][moteur],
                -c["couverture"][moteur],
                str(c["numero"]),
            ),
        )

    # Deuxième passage : tous les chevaux sont
    # conservés, y compris ceux mal classés.
    for cheval in chevaux:
        if cheval["manquants"]:
            cheval["alertes"].append(
                "Renseignements complémentaires à rechercher : "
                + ", ".join(cheval["manquants"])
            )

        scores = [
            s for s in cheval["scores"].values()
            if s is not None
        ]

        if scores and max(scores) - min(scores) >= 10:
            cheval["alertes"].append(
                "Divergence entre moteurs : "
                "réexamen recommandé"
            )

        if cheval["criteres"]["forme"] is not None:
            if cheval["criteres"]["forme"] < 40:
                cheval["alertes"].append(
                    "Forme récente à examiner en détail"
                )

        # Aucun outsider ou faux favori n'est
        # affirmé sans cotes et contexte vérifiés.
        cheval["alertes"].append(
            "Contrôler cote, opposition, parcours, "
            "origines et incidents documentés"
        )

    return {
        "statut": "ANALYSE_CONSULTATIVE",
        "course_id": course.get("id"),
        "hippodrome": course.get("hippodrome"),
        "depart": course.get("depart"),
        "chevaux": chevaux,
        "classements": {
            moteur: [
                {
                    "numero": c["numero"],
                    "nom": c["nom"],
                    "score": c["scores"][moteur],
                    "couverture": c["couverture"][moteur],
                }
                for c in classement
            ]
            for moteur, classement in classements.items()
        },
    }


def afficher(rapport):
    print("\n" + "=" * 60)
    print("🇸🇳🧠🔥 X1000 PHOENIX — M1 À M5")
    print("RAPPORT CONSULTATIF — LECTURE SEULE")
    print("=" * 60)

    if rapport["statut"] == "DONNEES_INSUFFISANTES":
        print(rapport["motif"])
        return

    print("Course :", rapport.get("course_id"))
    print("Hippodrome :", rapport.get("hippodrome"))
    print("Départ :", rapport.get("depart"))

    for moteur, classement in rapport["classements"].items():
        print(f"\n{moteur} — Classement heuristique")
        if not classement:
            print("Aucune évaluation disponible")
            continue

        for cheval in classement:
            print(
                f"  N°{cheval['numero']} "
                f"{cheval['nom']} | "
                f"indice {cheval['score']}/100 | "
                f"couverture {cheval['couverture']}%"
            )

    print("\nRÉEXAMEN DES CHEVAUX")
    for cheval in rapport["chevaux"]:
        print(
            f"\nN°{cheval['numero']} — {cheval['nom']}"
        )
        for alerte in cheval["alertes"]:
            print(" •", alerte)

    print("\nAucune donnée officielle modifiée.")
    print("Aucun FIGÉ créé ou modifié.")
    print("Scores non assimilables à des probabilités.")


def self_test():
    exemple = {
        "id": "TEST-R1-C1",
        "partants": [
            {
                "numero": 1,
                "nom": "CHEVAL_TEST_A",
                "musique": "1a2a3a",
            },
            {
                "numero": 2,
                "nom": "CHEVAL_TEST_B",
                "musique": "Da5a2a",
            },
            {
                "numero": 3,
                "nom": "CHEVAL_TEST_NP",
                "non_partant": True,
            },
        ],
    }

    rapport = analyser_course(exemple)
    assert rapport["statut"] == "ANALYSE_CONSULTATIVE"
    assert len(rapport["chevaux"]) == 2
    assert len(rapport["classements"]) == 5
    assert forme_musique({"musique": "Da"})[0] == 0
    assert score_borne(None) is None
    print("Tests techniques réussis.")
    print("Données fictives utilisées uniquement en test.")
    print("Aucune publication effectuée.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--course", default=None)
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return

    courses, source = lire_courses()

    if not courses:
        print("Aucune source de courses exploitable.")
        print("Aucune donnée inventée.")
        return

    print("Source lue :", source)

    if args.course:
        courses = [
            c for c in courses
            if str(c.get("id")) == args.course
        ]

    if not courses:
        print("Course demandée introuvable.")
        return

    for course in courses:
        rapport = analyser_course(course)
        afficher(rapport)


if __name__ == "__main__":
    main()
