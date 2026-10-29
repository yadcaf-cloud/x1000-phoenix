#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X1000 PHOENIX — renforcement consultatif M1-M5.

Lecture seule des donnees de collecte PMU. Aucune modification des
pronostics officiels, qualifications, PV, FIGES ou historiques.

Commandes :
    python renforcement_m1_m5.py --self-test
    python renforcement_m1_m5.py
    python renforcement_m1_m5.py --date 2026-10-29
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

VERSION = "1.0"
ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
PARIS = ZoneInfo("Europe/Paris")
SOURCE = DATA / "collecte.json"
DESTINATION = DATA / "renforcement_m1_m5.json"
MOTEURS = ("M1", "M2", "M3", "M4", "M5")
# Les poids sont des heuristiques transparentes, pas des probabilites.
POIDS = {
    "M1": (0.65, 0.25, 0.10),  # regularite, victoires, gains
    "M2": (0.35, 0.55, 0.10),  # capacite a gagner
    "M3": (0.70, 0.10, 0.20),  # constance et gains
    "M4": (0.45, 0.20, 0.35),  # experience et gains
    "M5": (0.50, 0.40, 0.10),  # contre-analyse
}


def maintenant():
    return dt.datetime.now(PARIS)


def lire_json(chemin):
    with chemin.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def ecrire_atomique(chemin, objet):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    temporaire = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=chemin.parent,
            prefix=chemin.name + ".", suffix=".tmp", delete=False
        ) as f:
            temporaire = Path(f.name)
            json.dump(objet, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporaire, chemin)
    finally:
        if temporaire is not None and temporaire.exists():
            temporaire.unlink()


def entier_positif(x):
    if isinstance(x, bool):
        return None
    try:
        n = int(x)
        return n if n > 0 and str(x).strip() == str(n) else None
    except (TypeError, ValueError, OverflowError):
        return None


def nombre(x):
    if x is None or isinstance(x, bool):
        return None
    try:
        v = float(str(x).replace(" ", "").replace(",", "."))
        return v if math.isfinite(v) and v >= 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def musique_positions(chaine):
    """Ne retenir que les positions clairement encodees (1a, 2p, 3m...).

    Les codes Da, Dp, 0a, etc. ne sont pas des classements chiffres
    exploitables pour ce score. Les nombres sans discipline sont ignores.
    """
    if not isinstance(chaine, str):
        return []
    tokens = re.findall(r"(\d{1,2})\s*[apmh](?![a-z])", chaine.lower())
    return [int(n) for n in tokens if 1 <= int(n) <= 20]


def indicateurs(cheval):
    positions = musique_positions(cheval.get("musique", ""))[:8]
    gains = nombre(cheval.get("gains"))
    if not positions:
        return {"positions": [], "regularite": None, "victoires": None,
                "gains": gains, "observations": 0}
    # 1er = 1, 2e = 0.8, 3e = 0.6, 4e = 0.4, 5e = 0.2, autres = 0.
    regularite = sum(max(0, 1 - (p - 1) / 5) for p in positions) / len(positions)
    victoires = positions.count(1) / len(positions)
    return {"positions": positions, "regularite": round(regularite, 5),
            "victoires": round(victoires, 5), "gains": gains,
            "observations": len(positions)}


def calculer_score(ind, moteur, maximum_gains):
    wreg, wvic, wgains = POIDS[moteur]
    valeurs = []
    if ind["regularite"] is not None:
        valeurs.append((wreg, ind["regularite"]))
    if ind["victoires"] is not None:
        valeurs.append((wvic, ind["victoires"]))
    if ind["gains"] is not None and maximum_gains > 0:
        valeurs.append((wgains, math.log1p(ind["gains"]) / math.log1p(maximum_gains)))
    if not valeurs:
        return None
    poids_disponible = sum(w for w, _ in valeurs)
    return round(100 * sum(w * v for w, v in valeurs) / poids_disponible, 2)


def analyser_course(course, date_cible, instant):
    if not isinstance(course, dict):
        return None
    cid = course.get("id") or course.get("course_id")
    if not isinstance(cid, str) or not cid.startswith(date_cible + "-R"):
        return None
    if course.get("localisation_france_verifiee") is not True:
        return None
    depart_texte = course.get("depart")
    if not isinstance(depart_texte, str) or not course.get("depart_verifie"):
        return None
    try:
        depart = dt.datetime.fromisoformat(depart_texte.replace("Z", "+00:00"))
        if depart.tzinfo is None:
            return None
        depart = depart.astimezone(PARIS)
    except ValueError:
        return None
    if depart.date().isoformat() != date_cible or depart <= instant:
        return None  # Aucun pronostic retrospectif
    partants = course.get("partants")
    if not isinstance(partants, list) or not partants:
        return None
    chevaux = []
    numeros = set()
    for c in partants:
        if not isinstance(c, dict):
            return None
        numero = entier_positif(c.get("numero"))
        nom = c.get("nom")
        if numero is None or numero in numeros or not isinstance(nom, str) or not nom.strip():
            return None
        numeros.add(numero)
        if c.get("non_partant") is True or numero in course.get("non_partants", []):
            continue
        ind = indicateurs(c)
        chevaux.append({"numero": numero, "nom": nom.strip(),
                        "musique": c.get("musique") or "", "indicateurs": ind})
    if len(chevaux) < 2:
        return None
    maximum_gains = max((c["indicateurs"]["gains"] or 0 for c in chevaux), default=0)
    moteurs = {}
    for moteur in MOTEURS:
        classement = []
        for c in chevaux:
            score = calculer_score(c["indicateurs"], moteur, maximum_gains)
            classement.append({"numero": c["numero"], "nom": c["nom"],
                                "score_heuristique": score,
                                "observations": c["indicateurs"]["observations"]})
        classement.sort(key=lambda x: (x["score_heuristique"] is None,
                                          -(x["score_heuristique"] or 0), x["numero"]))
        moteurs[moteur] = {
            "classement_exploratoire": classement,
            "chevaux_evaluables": sum(x["score_heuristique"] is not None for x in classement),
            "statut": "ETUDE_NON_VALIDEE",
            "pari_retenu": None,
            "gagnant_officiel": None,
            "fige": False,
        }
    # Des profils peu mis en avant par M1 mais mieux evalues par d'autres
    # ne sont pas necessairement negliges par le marche (cotes absentes).
    rang_m1 = {x["numero"]: i for i, x in enumerate(moteurs["M1"]["classement_exploratoire"])}
    profils = []
    for c in chevaux:
        num = c["numero"]
        rangs = [next(i for i, x in enumerate(moteurs[m]["classement_exploratoire"])
                      if x["numero"] == num) for m in MOTEURS]
        if rang_m1[num] >= 2 and min(rangs[1:]) < rang_m1[num] and c["indicateurs"]["observations"] >= 2:
            profils.append({"numero": num, "nom": c["nom"],
                            "motif": "Profil divergent entre moteurs; examen humain recommande"})
    return {
        "course_id": cid, "hippodrome": course.get("hippodrome"),
        "depart_paris": depart.isoformat(), "nombre_partants": len(chevaux),
        "non_partants": sorted(numeros - {c["numero"] for c in chevaux}),
        "moteurs": moteurs, "profils_a_reexaminer": profils,
        "faux_favoris": [],
        "avertissements": [
            "Les cotes et favoris de marche ne sont pas verifies : aucun faux favori affirme.",
            "Terrain, distance, forme detaillee, opposition et aptitude non evalues faute de donnees fiables.",
            "Scores heuristiques non calibres : ni probabilites ni conseils de mise."
        ]
    }


def construire(collecte, date_cible, instant=None):
    instant = instant or maintenant()
    if not isinstance(collecte, dict) or not isinstance(collecte.get("courses"), list):
        raise ValueError("Collecte invalide : courses absentes")
    if collecte.get("date") != date_cible:
        raise ValueError("Date de collecte differente de la date demandee")
    if collecte.get("statut") not in ("OK", "PARTIEL"):
        raise ValueError("Collecte non exploitable")
    courses = []
    vus = set()
    for course in collecte["courses"]:
        analyse = analyser_course(course, date_cible, instant)
        if analyse is not None and analyse["course_id"] not in vus:
            vus.add(analyse["course_id"])
            courses.append(analyse)
    courses.sort(key=lambda x: (x["depart_paris"], x["course_id"]))
    return {
        "version": VERSION, "module": "renforcement_m1_m5",
        "date": date_cible, "analyse_a": instant.isoformat(),
        "source": "data/collecte.json", "statut": "ETUDE_COMPLEMENTAIRE",
        "publication_officielle": False, "figes_modifies": False,
        "courses": courses,
        "statistiques": {"courses_etudiees": len(courses),
                         "analyses_moteurs": len(courses) * len(MOTEURS)},
        "note": "Lecture seule; aucune validation ni FIGE; aucune garantie de gain."
    }


def self_test():
    assert musique_positions("1a2aDa0a3p") == [1, 3]
    assert musique_positions("inconnue") == []
    assert entier_positif(True) is None
    instant = dt.datetime(2026, 10, 29, 10, 0, tzinfo=PARIS)
    course = {"id": "2026-10-29-R1-C1", "localisation_france_verifiee": True,
              "depart_verifie": True, "depart": "2026-10-29T14:00:00+01:00",
              "non_partants": [3], "partants": [
                  {"numero": 1, "nom": "TEST A", "musique": "1a2a", "gains": 1000},
                  {"numero": 2, "nom": "TEST B", "musique": "2a3a", "gains": 800},
                  {"numero": 3, "nom": "TEST NP", "non_partant": True}]}
    source = {"date": "2026-10-29", "statut": "OK", "courses": [course]}
    rapport = construire(source, "2026-10-29", instant)
    assert rapport["statistiques"]["analyses_moteurs"] == 5
    assert rapport["courses"][0]["nombre_partants"] == 2
    assert rapport["courses"][0]["non_partants"] == [3]
    assert analyser_course(course, "2026-10-29", instant + dt.timedelta(hours=5)) is None
    assert rapport["courses"][0]["moteurs"]["M1"]["fige"] is False
    print("SELF-TEST OK : cinq moteurs, NP, horodatage, aucune ecriture officielle")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="AAAA-MM-JJ (par defaut aujourd'hui a Paris)")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    try:
        instant = maintenant()
        date_cible = dt.date.fromisoformat(args.date).isoformat() if args.date else instant.date().isoformat()
        collecte = lire_json(SOURCE)
        rapport = construire(collecte, date_cible, instant)
        # Le seul fichier autorise en ecriture est la sortie complementaire.
        ecrire_atomique(DESTINATION, rapport)
        print(f"X1000 : {rapport['statistiques']['courses_etudiees']} courses etudiees")
        print(f"Rapport consultatif : {DESTINATION}")
        return 0
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as erreur:
        print(f"ECHEC sans modification des donnees officielles : {erreur}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
