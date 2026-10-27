#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X1000 PHOENIX - Publication prudente M1-M5.

Aucune note, aucun partant et aucune arrivée inventés.
Les données non vérifiées restent non validées.
"""

import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from phoenix import (
    analyser, auditer, date_paris, ecrire,
    empreinte, figer, lire, maintenant
)

BASE = Path("data")
PARIS = ZoneInfo("Europe/Paris")
MOTEURS = ("M1", "M2", "M3", "M4", "M5")
CRITERES = (
    "forme", "aptitude", "regularite",
    "entourage", "valeur"
)


def enregistrer(nom, contenu):
    ecrire(BASE / nom, contenu)


def charger_liste(dossier):
    resultat = []
    for fichier in sorted((BASE / dossier).glob("*.json")):
        try:
            document = lire(fichier)
            if isinstance(document, dict):
                resultat.append(document)
        except (OSError, ValueError, TypeError) as erreur:
            print(f"Fichier ignore {fichier}: {erreur}")
    return resultat


def id_course(course):
    if course.get("id"):
        return str(course["id"])
    date = str(course.get("date", ""))
    reunion = course.get("reunion")
    numero = course.get("course")
    if not date or reunion is None or numero is None:
        raise ValueError("Identifiant de course incomplet")
    return f"{date}-R{reunion}-C{numero}"


def depart_course(course):
    valeur = course.get("depart")
    if valeur:
        return date_paris(valeur)
    ms = course.get("depart_ms")
    if type(ms) not in (int, float) or ms <= 0:
        raise ValueError("Heure de depart absente")
    return dt.datetime.fromtimestamp(ms / 1000, PARIS)


def source_valide(course):
    source = course.get("source")
    # Un libelle PMU seul n'est pas une preuve de provenance.
    return (
        isinstance(source, str)
        and source.startswith(("https://", "http://"))
        and bool(course.get("date"))
    )


def notes_completes(course):
    partants = course.get("partants")
    if not isinstance(partants, list):
        return False
    actifs = [
        c for c in partants
        if isinstance(c, dict) and not c.get("non_partant")
    ]
    if len(actifs) < 2:
        return False
    for cheval in actifs:
        notes = cheval.get("notes")
        if not isinstance(notes, dict):
            return False
        for critere in CRITERES:
            note = notes.get(critere)
            if type(note) not in (int, float):
                return False
            if not 0 <= note <= 10:
                return False
    return True


def preparer_course(original):
    if not isinstance(original, dict):
        raise ValueError("Objet course invalide")
    course = dict(original)
    course["id"] = id_course(course)
    course["depart"] = depart_course(course).isoformat()
    course["moteurs"] = {}
    course["statut"] = "SANS_PRONOSTIC"
    return course


def figes_verifies():
    documents = []
    for document in charger_liste("figes"):
        try:
            attendu = document["sha256"]
            contenu = {
                k: v for k, v in document.items()
                if k != "sha256"
            }
            rapport = document["rapport"]
            if empreinte(contenu) != attendu:
                raise ValueError("Empreinte incorrecte")
            if date_paris(document["fige_a"]) >= date_paris(
                rapport["depart"]
            ):
                raise ValueError("FIGE apres depart")
            if document.get("statut") != "FIGE_AVANT_DEPART":
                raise ValueError("Statut incorrect")
            documents.append(document)
        except (KeyError, TypeError, ValueError) as erreur:
            print("FIGE rejete:", erreur)
    return documents


def auditer_arrivees(figes):
    audits = []
    index = {
        f["rapport"]["course_id"]: f
        for f in figes
    }
    for arrivee in charger_liste("arrivees"):
        try:
            course_id = arrivee.get("course_id")
            if course_id not in index:
                continue
            if (
                arrivee.get("statut") != "definitive"
                or not isinstance(arrivee.get("source"), str)
                or not arrivee["source"].startswith("https://")
            ):
                continue
            audit = auditer(index[course_id], arrivee)
            audits.append(audit)
            ecrire(
                BASE / "audits" / f"{course_id}.json",
                audit
            )
        except (KeyError, TypeError, ValueError) as erreur:
            print("Audit refuse:", erreur)
    return audits


def main():
    horodatage = maintenant().isoformat()
    erreurs = []
    courses = []
    pv = []

    entree = BASE / "courses.json"
    if not entree.exists():
        erreurs.append("data/courses.json absent")
        originales = []
    else:
        try:
            document = lire(entree)
            originales = document.get("courses", [])
            if not isinstance(originales, list):
                raise ValueError("Liste courses invalide")
        except (OSError, ValueError, TypeError) as erreur:
            erreurs.append(str(erreur))
            originales = []

    for originale in originales:
        try:
            course = preparer_course(originale)
            depart = date_paris(course["depart"])

            if not source_valide(course):
                course["erreur"] = (
                    "Source primaire non verifiable : "
                    "analyse et FIGE refuses"
                )
            elif not notes_completes(course):
                course["erreur"] = (
                    "Notes documentees M1-M5 absentes : "
                    "aucun pronostic fabrique"
                )
            elif maintenant() >= depart:
                course["erreur"] = (
                    "Depart atteint : aucun pronostic retrospectif"
                )
            else:
                entree_analyse = {
                    "id": course["id"],
                    "depart": course["depart"],
                    "hippodrome": course["hippodrome"],
                    "source": course["source"],
                    "partants": course["partants"]
                }
                rapport = analyser(entree_analyse)
                course["moteurs"] = {
                    m["moteur"]: m
                    for m in rapport["moteurs"]
                }
                course["statut"] = "ANALYSE_INDICATIVE"
                pv.append({
                    "course_id": course["id"],
                    "created_at": horodatage,
                    "statut": "ANALYSE_INDICATIVE",
                    "moteurs": course["moteurs"]
                })
                # Le FIGE n'est cree que dans la fenetre
                # prevue par phoenix.py, avant le depart.
                figer(rapport)

            courses.append(course)

        except (KeyError, ValueError, TypeError) as erreur:
            erreurs.append(str(erreur))

    figes = figes_verifies()
    audits = auditer_arrivees(figes)

    # Format d'affichage du site.
    index_figes = []
    for document in figes:
        rapport = document["rapport"]
        index_figes.append({
            "course_id": rapport["course_id"],
            "heure_fige": document["fige_a"],
            "sha256": document["sha256"],
            "statut": document["statut"],
            "moteurs": {
                m["moteur"]: m
                for m in rapport["moteurs"]
            }
        })

    enregistrer("tableau_officiel.json", {
        "actualise": horodatage,
        "courses": courses
    })
    enregistrer("pv.json", {"pv": pv})
    enregistrer("figes.json", {"figes": index_figes})
    enregistrer("audits.json", {"audits": audits})

    rapport = {
        "execution": horodatage,
        "statut": "OK" if not erreurs else "PARTIEL",
        "courses": len(courses),
        "analyses": sum(
            c["statut"] == "ANALYSE_INDICATIVE"
            for c in courses
        ),
        "pv": len(pv),
        "figes": len(figes),
        "audits": len(audits),
        "erreurs_courses": len(erreurs),
        "difficultes": erreurs,
        "avertissement": (
            "Aucune donnee manquante n'est inventee. "
            "Les sources et les notes doivent etre verifiees."
        )
    }
    enregistrer("rapport.json", rapport)
    enregistrer("latest.json", rapport)
    print(json.dumps(rapport, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
