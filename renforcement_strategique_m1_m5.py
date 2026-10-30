#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X1000 PHOENIX — contrôle stratégique consultatif M1–M5.

Lecture seule. Ne modifie aucun fichier, workflow, FIGÉ ou pronostic.
Les indices sont des heuristiques, jamais des probabilités ou décisions de pari.

python renforcement_strategique_m1_m5.py --self-test
python renforcement_strategique_m1_m5.py
python renforcement_strategique_m1_m5.py --course 2026-10-30-R1-C1
"""
import argparse
import json
import math
import re
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
SOURCES = (
    "publication_courses.json", "courses_verifiees.json", "collecte.json",
    "courses_pmu.json", "courses.json",
)
MOTEURS = {
    "M1": {"forme": .35, "regularite": .40, "distance": .15, "terrain": .10},
    "M2": {"forme": .40, "progression": .30, "distance": .20, "terrain": .10},
    "M3": {"forme": .20, "progression": .25, "distance": .20, "entourage": .15, "pedigree": .20},
    "M4": {"forme": .25, "regularite": .30, "distance": .20, "terrain": .15, "entourage": .10},
    "M5": {"forme": .15, "distance": .20, "terrain": .15, "entourage": .25, "pedigree": .25},
}
EXTRAS = {
    "distance": "score_distance_verifie",
    "terrain": "score_terrain_verifie",
    "entourage": "score_entourage_verifie",
    "pedigree": "score_pedigree_verifie",
}


def nombre(valeur):
    if valeur is None or isinstance(valeur, bool):
        return None
    try:
        n = float(str(valeur).strip().replace(",", "."))
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


def borne(valeur):
    n = nombre(valeur)
    return n if n is not None and 0 <= n <= 100 else None


def musique(valeur):
    """Extrait les rangs d'une musique française (récents en premier).

    D/A/T/0 et autres codes non classés sont conservés comme inconnus :
    leur sens ne permet pas d'inférer une position ou une probabilité.
    """
    if not isinstance(valeur, str):
        return []
    tokens = re.findall(r"(?<!\w)(\d+|D|A|T)[apmh](?!\w)", valeur, re.I)
    # Les musiques compactes usuelles (1a2aDa...) n'ont pas de séparateurs.
    if not tokens:
        tokens = re.findall(r"(\d+|D|A|T)[apmh]", valeur, re.I)
    return [int(t) if t.isdigit() and int(t) > 0 else None for t in tokens[:8]]


def criteres(cheval):
    result = {k: None for k in ("forme", "regularite", "progression", *EXTRAS)}
    positions = musique(cheval.get("musique"))
    connus = [(i, p) for i, p in enumerate(positions) if p is not None]
    if connus:
        # Un rang inconnu n'est pas assimilé à une dernière place.
        notes = [(i, max(0, 100 - (p - 1) * 12)) for i, p in connus]
        poids = [(len(positions) - i, note) for i, note in notes]
        result["forme"] = round(sum(w * n for w, n in poids) / sum(w for w, _ in poids), 2)
        result["regularite"] = round(100 * sum(p <= 3 for _, p in connus) / len(connus), 2)
        # Progression uniquement avec au moins deux résultats classés
        # dans chaque moitié chronologique.
        milieu = len(positions) // 2
        recent = [n for i, n in notes if i < milieu]
        ancien = [n for i, n in notes if i >= milieu]
        if len(recent) >= 2 and len(ancien) >= 2:
            ecart = sum(recent) / len(recent) - sum(ancien) / len(ancien)
            result["progression"] = round(max(0, min(100, 50 + ecart / 2)), 2)
    preuves = cheval.get("preuves_scores")
    if isinstance(preuves, dict):
        for critere, champ in EXTRAS.items():
            preuve = preuves.get(critere)
            if (isinstance(preuve, dict)
                    and preuve.get("verifie") is True
                    and isinstance(preuve.get("source"), str)
                    and preuve["source"].strip()):
                result[critere] = borne(cheval.get(champ))
    return result


def evaluer(cheval):
    c = criteres(cheval)
    evaluations = {}
    for moteur, poids in MOTEURS.items():
        presents = {k: v for k, v in c.items() if k in poids and v is not None}
        couverture = sum(poids[k] for k in presents)
        evaluations[moteur] = {
            "indice": round(sum(v * poids[k] for k, v in presents.items()) / couverture, 2) if couverture else None,
            "couverture_pct": round(100 * couverture, 1),
            "fiabilite_donnees": "LIMITEE" if couverture < .70 else "PARTIELLE_A_VERIFIER",
        }
    return {
        "numero": cheval.get("numero"),
        "nom": cheval.get("nom") or "Nom indisponible",
        "criteres": c,
        "moteurs": evaluations,
        "informations_absentes": [k for k, v in c.items() if v is None],
        "controle_presse": "Non établi sans citations de presse datées et vérifiées",
        "controle_favori": "Non établi sans cotes, opposition et risques vérifiés",
        "controle_incidents": "Non établi sans incidents documentés",
        "second_examen": "À approfondir : parcours, engagement, progression, entourage, origines",
        "statut": "CONSULTATIF_NON_VALIDE",
    }


def non_partant(cheval):
    return (cheval.get("non_partant") is True or
            str(cheval.get("statut") or "").strip().upper() in
            {"NP", "NON_PARTANT", "NON-PARTANT"})


def analyser(course):
    identifiant = course.get("id")
    localisation = course.get("localisation_france_verifiee")
    if localisation is not True:
        return {"course_id": identifiant,
                "statut": "HORS_FRANCE" if localisation is False else "LOCALISATION_A_VERIFIER"}
    partants = course.get("partants")
    if not isinstance(partants, list):
        return {"course_id": identifiant, "statut": "PARTANTS_INDISPONIBLES"}
    chevaux = [evaluer(p) for p in partants if isinstance(p, dict) and not non_partant(p)]
    if not chevaux:
        return {"course_id": identifiant, "statut": "AUCUN_PARTANT_EXPLOITABLE"}
    classements = {}
    for moteur in MOTEURS:
        eligibles = [c for c in chevaux if c["moteurs"][moteur]["indice"] is not None]
        classes = sorted(eligibles, key=lambda c: (
            -c["moteurs"][moteur]["indice"],
            -c["moteurs"][moteur]["couverture_pct"], str(c["numero"])))
        classements[moteur] = [
            {"numero": c["numero"], "nom": c["nom"], **c["moteurs"][moteur]}
            for c in classes
        ]
    return {
        "course_id": identifiant, "hippodrome": course.get("hippodrome"),
        "depart": course.get("depart"), "statut": "AUDIT_CONSULTATIF",
        "chevaux": chevaux, "classements": classements,
        "limites": [
            "Scores heuristiques, non probabilistes, sans validation de pari.",
            "Aucun favori trompeur ni outsider crédible affirmé sans preuve.",
            "Couverture faible : classement exploratoire, non décisionnel.",
            "Aucun fichier officiel ni FIGÉ modifié.",
        ],
    }


def charger():
    for nom in SOURCES:
        chemin = DATA / nom
        if not chemin.is_file():
            continue
        try:
            contenu = json.loads(chemin.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"Source illisible {nom}: {exc}")
            continue
        if isinstance(contenu, list):
            courses = contenu
        elif isinstance(contenu, dict):
            courses = contenu.get("courses")
            if not isinstance(courses, list):
                courses = contenu.get("courses_verifiees")
        else:
            courses = None
        if isinstance(courses, list):
            valides = [c for c in courses if isinstance(c, dict)]
            if valides:
                return valides, nom
    return [], None


def self_test():
    assert musique("1a2aDa4p") == [1, 2, None, 4]
    assert musique("Da") == [None]
    assert borne("75,5") == 75.5
    assert borne("nan") is None
    assert borne(True) is None
    assert criteres({"musique": "Da"})["forme"] is None
    assert criteres({"score_distance_verifie": 95})["distance"] is None
    cheval = {"musique": "1a2a3a4a", "score_distance_verifie": 90,
              "preuves_scores": {"distance": {"verifie": True, "source": "Résultat officiel"}}}
    assert criteres(cheval)["distance"] == 90
    test = {"id": "TEST", "localisation_france_verifiee": True,
            "partants": [{"numero": 1, "nom": "TEST_A", "musique": "1a2a3a4a"},
                         {"numero": 2, "nom": "TEST_NP", "non_partant": True}]}
    rapport = analyser(test)
    assert len(rapport["chevaux"]) == 1
    assert len(rapport["classements"]) == 5
    assert rapport["chevaux"][0]["criteres"]["pedigree"] is None
    assert analyser({"id": "X", "partants": []})["statut"] == "LOCALISATION_A_VERIFIER"
    assert analyser({"id": "X", "localisation_france_verifiee": False})["statut"] == "HORS_FRANCE"
    print("Tests réussis. Données de test uniquement, aucune publication.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--course", help="Identifiant exact de course")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    courses, source = charger()
    if not courses:
        print("Aucune source exploitable. Aucun pronostic inventé.")
        return
    if args.course:
        courses = [c for c in courses if str(c.get("id")) == args.course]
    if not courses:
        print("Course introuvable.")
        return
    print("Source consultée en lecture seule :", source)
    for course in courses:
        print(json.dumps(analyser(course), ensure_ascii=False, indent=2))
    print("Aucun fichier modifié. Aucun FIGÉ créé. Aucun pronostic officiel publié.")


if __name__ == "__main__":
    main()
